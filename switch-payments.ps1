# All stages before public release are frozen; financial copies are never deleted.
param([switch]$RollbackBeforeOpen,[switch]$PauseBeforeOpen)
$ErrorActionPreference='Stop'
if ($RollbackBeforeOpen -and $PauseBeforeOpen) { throw 'Choose either pause or rollback.' }
Push-Location $PSScriptRoot
$base=@('compose','-f','docker-compose.yml')
$tools=$base+@('-f','compose.payments.yml','-f','compose.payments-cutover.yml')
$selected=$tools
$maintenance=$null
$state=$null
$released=$false
$frozen=$false
$resultDirectory=Join-Path $PSScriptRoot 'runtime/payments-cutover'
function Invoke-Checked([string[]]$Arguments) {
    & docker @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw ('Docker operation failed: '+($Arguments -join ' ')) }
}
function Read-Cutover([string]$Action) {
    $container='cutover-node-'+[Guid]::NewGuid().ToString('N')
    $file=Join-Path $resultDirectory ($container+'.json')
    try {
        Invoke-Checked ($script:selected+@('run','--no-deps','--name',$container,'cutover-node',$Action))
        Invoke-Checked @('cp',($container+':/migration/source/status.json'),$file)
        $document=Get-Content -Raw -Encoding UTF8 -LiteralPath $file | ConvertFrom-Json
        if ($document.result -ne 'PASS') { throw 'Invalid cutover status.' }
        return $document
    } finally {
        # Only this invocation's randomly named operator container is removed.
        $previousPreference=$ErrorActionPreference
        $ErrorActionPreference='Continue'
        & docker rm $container | Out-Null
        $ErrorActionPreference=$previousPreference
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
}
function Select-CutoverTarget($Document) {
    if ($Document.run_id -notmatch '^[a-f0-9-]{36}$') { throw 'Invalid cutover run ID.' }
    $directory=Join-Path $resultDirectory $Document.run_id
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $volume=($script:project+'-payments-cutover-'+$Document.run_id).ToLowerInvariant()
    $path=Join-Path $directory 'volume.json'
    $json=@{volumes=@{'payments-data'=@{name=$volume}}}|ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($path,$json,[Text.UTF8Encoding]::new($false))
    $receipt=@{project=$script:project;run_id=$Document.run_id;snapshot_sha256=$Document.snapshot_sha256;phase=$Document.phase}
    [IO.File]::WriteAllText((Join-Path $resultDirectory 'active.json'),($receipt|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
    $script:selected=$script:tools+@('-f',$path)
    $script:maintenance=$script:selected+@('-f','compose.payments-maintenance.yml')
}
function Check-Imported([string]$Action) {
    Invoke-Checked ($script:selected+@('run','--rm','--no-deps','cutover-import',$Action,'--run-id',$script:state.run_id))
}
function Stop-Writers {
    Invoke-Checked ($script:selected+@('stop','gateway','edemand','payments-worker','payments'))
}
function Rollback-Frozen {
    Stop-Writers
    Check-Imported 'check'
    $script:state=Read-Cutover 'rollback'
    Select-CutoverTarget $script:state
    Invoke-Checked ($script:selected+@('stop','cutover-probe-gateway'))
    Invoke-Checked ($script:base+@('up','-d','--wait','--wait-timeout','360'))
    Write-Host 'PASS: original financial tables restored to service; PostgreSQL copy and backup retained.' -ForegroundColor Green
}
try {
    New-Item -ItemType Directory -Force -Path $resultDirectory | Out-Null
    $raw=& docker @base config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve original Compose project.' }
    $project=(($raw -join "`n")|ConvertFrom-Json).name
    if ($project -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Invalid Compose project name.' }
    # Pin the same namespace even when the caller started it with -p previously.
    $base=@('compose','--project-name',$project,'-f','docker-compose.yml')
    $tools=$base+@('-f','compose.payments.yml','-f','compose.payments-cutover.yml')
    $selected=$tools
    Invoke-Checked ($tools+@('build','bootstrap','edemand','payments','payments-worker','keycloak-config','cutover-node','cutover-import','cutover-read-check'))
    Invoke-Checked ($tools+@('run','--rm','--no-deps','bootstrap'))
    $state=Read-Cutover 'status'
    if ($state.phase -eq 'external-pilot') { throw 'This project already uses the fresh Payments pilot. It has no legacy cutover to run.' }
    if ($RollbackBeforeOpen -and $state.phase -in @('legacy','rolled_back')) { throw 'There is no unfinished cutover to roll back.' }
    if ($state.phase -eq 'released') {
        if ($RollbackBeforeOpen) { throw 'Public release already occurred. Rollback is refused; restart the migrated system instead.' }
        Select-CutoverTarget $state
        $released=$true
        Invoke-Checked ($selected+@('up','-d','--wait','--wait-timeout','360'))
        Write-Host 'PASS: committed Payments target restarted.' -ForegroundColor Green
        return
    }
    Write-Host 'Maintenance: stopping public ingress and financial writers. All existing volumes are kept.'
    Stop-Writers
    $frozen=$true
    if ($state.phase -in @('legacy','rolled_back')) {
        $state=Read-Cutover 'prepare'
    }
    Select-CutoverTarget $state
    Invoke-Checked ($selected+@('up','-d','--wait','--wait-timeout','360','payments-db'))
    if ($RollbackBeforeOpen) { Rollback-Frozen; $frozen=$false; return }
    Check-Imported 'import'
    if ($state.phase -eq 'prepared') { $state=Read-Cutover 'activate' }
    Invoke-Checked ($selected+@('up','-d','--wait','--wait-timeout','360','keycloak','notifications'))
    Invoke-Checked ($selected+@('run','--rm','--no-deps','keycloak-config'))
    Invoke-Checked ($maintenance+@('up','-d','--wait','--wait-timeout','360','payments','payments-worker','edemand','cutover-probe-gateway'))
    Invoke-Checked ($maintenance+@('run','--rm','--no-deps','cutover-read-check'))
    Stop-Writers
    Check-Imported 'check'
    if ($PauseBeforeOpen) {
        Select-CutoverTarget $state
        Write-Host 'PASS: imported target verified; public access remains closed for review or rollback.' -ForegroundColor Green
        return
    }
    $state=Read-Cutover 'release'
    $released=$true
    Select-CutoverTarget $state
    Invoke-Checked ($selected+@('stop','cutover-probe-gateway'))
    Invoke-Checked ($selected+@('up','-d','--wait','--wait-timeout','360'))
    Write-Host 'PASS: Payments history reconciled, read-only gateway checks passed, public service opened. Use start-payments.ps1 for future starts.' -ForegroundColor Green
} catch {
    $originalError=$_
    if ($frozen -and -not $released) {
        try {
            $state=Read-Cutover 'status'
            if ($state.phase -eq 'released') { $released=$true; Select-CutoverTarget $state }
            elseif ($state.run_id) {
                Select-CutoverTarget $state
                Invoke-Checked ($selected+@('up','-d','--wait','--wait-timeout','360','payments-db'))
                Rollback-Frozen; $frozen=$false
            } else {
                Invoke-Checked ($base+@('up','-d','--wait','--wait-timeout','360'))
                $frozen=$false
            }
        } catch { Write-Host 'Maintenance remains closed. Automatic rollback could not prove the target unchanged; all copies were retained.' -ForegroundColor Red }
    }
    if ($released) { Write-Host 'Release was committed. Do not restore an old wallet; use start-payments.ps1 to recover forward.' -ForegroundColor Yellow }
    throw $originalError
} finally { Pop-Location }

