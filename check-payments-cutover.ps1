# Briefly stops the regular stack, tests clean isolated volumes, then restores it.
param([switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/clean-source.ps1')
$previousProject = $env:COMPOSE_PROJECT_NAME
$testProject = 'payments-rehearsal-' + ([Guid]::NewGuid().ToString('N').Substring(0,12))
$scratch = Join-Path ([IO.Path]::GetTempPath()) $testProject
$compose = @('compose','-f','docker-compose.yml')
$originalStopped = $false
$passed = $false
try {
    $files = @(Get-NotificationsCleanSourceFiles -Root $PSScriptRoot)
    if ($files.Count -eq 0) { throw 'Clean-source manifest did not select any files.' }
    New-Item -ItemType Directory -Path $scratch | Out-Null
    $separator = [IO.Path]::DirectorySeparatorChar
    $sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd($separator) + $separator
    foreach ($relative in $files) {
        $source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $relative))
        $destination = [IO.Path]::GetFullPath((Join-Path $scratch $relative))
        if (-not $source.StartsWith($sourceRoot,[StringComparison]::OrdinalIgnoreCase) -or
            -not $destination.StartsWith(($scratch + $separator),[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Source path escaped the clean-test directory.'
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }
    if (Test-Path -LiteralPath (Join-Path $scratch '.env.notifications')) { throw 'Clean source unexpectedly contains local secrets.' }
    if ($PrepareOnly) {
        Write-Host "Prepared $($files.Count) source files without inherited secrets. Docker was not changed."
        return
    }
    $configuration = & docker @compose config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Original Compose configuration is invalid.' }
    $originalProject = (($configuration -join "`n") | ConvertFrom-Json).name
    if ($originalProject -eq $testProject) { throw 'Clean-test project must be separate.' }
    Write-Host 'Temporarily stopping the regular stack; its database volumes will be preserved.'
    & docker @compose down
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the regular stack.' }
    $originalStopped = $true
    $env:COMPOSE_PROJECT_NAME = $testProject
    Push-Location $scratch
    try {
        New-Item -ItemType Directory -Force -Path 'runtime/payments-cutover' | Out-Null
        & docker compose up --build -d --wait --wait-timeout 360
        if ($LASTEXITCODE -ne 0) { & docker compose logs --tail 60; throw 'Raw-source docker compose up failed.' }
        if (Test-Path -LiteralPath '.env.notifications') { throw 'Raw boot unexpectedly wrote host-side credentials.' }
        & docker compose run --rm --no-deps -e CUTOVER_FIXTURE=synthetic notifications-worker python -m app.seed_payments_cutover
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic legacy history setup failed.' }
        & (Join-Path $scratch 'switch-payments.ps1') -PauseBeforeOpen
        $publicOpen=$false
        try { $response=Invoke-WebRequest -Uri 'http://localhost:8080/gateway-health' -UseBasicParsing -TimeoutSec 2; $publicOpen=$response.StatusCode -eq 200 } catch {}
        if ($publicOpen) { throw 'Public ingress unexpectedly opened before cutover release.' }
        & (Join-Path $scratch 'switch-payments.ps1') -RollbackBeforeOpen
        & docker compose -f docker-compose.yml -f compose.payments.yml -f compose.payments-cutover.yml run --rm --no-deps -e GATEWAY_CONNECT_HOST=gateway cutover-read-check python -m app.check_payments_cutover --legacy
        if ($LASTEXITCODE -ne 0) { throw 'Legacy wallet did not survive pre-release rollback.' }
        & (Join-Path $scratch 'switch-payments.ps1')
        $receipt=Get-Content -Raw -Encoding UTF8 'runtime/payments-cutover/active.json' | ConvertFrom-Json
        if ($receipt.phase -ne 'released' -or $receipt.run_id -notmatch '^[a-f0-9-]{36}$') { throw 'Invalid cutover receipt.' }
        $volumeOverride=Join-Path $scratch ('runtime/payments-cutover/'+$receipt.run_id+'/volume.json')
        & docker compose -f docker-compose.yml -f compose.payments.yml -f $volumeOverride run --rm --no-deps notifications-worker python -m app.smoke_payments
        if ($LASTEXITCODE -ne 0) { throw 'New financial operations failed after history cutover.' }
        & (Join-Path $scratch 'start-payments.ps1')
        $passed = $true
    } finally { Pop-Location }
} finally {
    if ($originalStopped) {
        # Stop only the unique fixture project. Backups and imported copies are retained.
        & docker compose --project-name $testProject -f (Join-Path $scratch 'docker-compose.yml') -f (Join-Path $scratch 'compose.payments.yml') -f (Join-Path $scratch 'compose.payments-cutover.yml') down --remove-orphans
        $cleanupExit = $LASTEXITCODE
        $env:COMPOSE_PROJECT_NAME = $previousProject
        $activeReceipt=Join-Path $PSScriptRoot 'runtime/payments-cutover/active.json'
        $isMigrated=$false
        if (Test-Path -LiteralPath $activeReceipt) { $isMigrated=((Get-Content -Raw -Encoding UTF8 $activeReceipt | ConvertFrom-Json).phase -eq 'released') }
        if ($isMigrated) { & (Join-Path $PSScriptRoot 'start-payments.ps1'); $restoreExit=0 }
        else { & docker compose --project-name $originalProject -f docker-compose.yml up -d --wait --wait-timeout 360; $restoreExit=$LASTEXITCODE }
        if ($cleanupExit -ne 0 -or $restoreExit -ne 0) { throw 'Clean-test cleanup or original-stack restoration failed.' }
    }
    $env:COMPOSE_PROJECT_NAME = $previousProject
    Pop-Location
}
if ($passed) {
    $evidence = Join-Path $PSScriptRoot 'docs/evidence'
    New-Item -ItemType Directory -Force -Path $evidence | Out-Null
    @{result='PASS';probe='payments-cutover-rehearsal';source_files=$files.Count;fresh_project=$testProject;
      inherited_secrets=$false;fixture_only=$true;copies_retained=$true;pre_release_rollback=$true;boot_command='switch-payments.ps1';fresh_volumes=$true;original_stack_restored=$true;recorded_at=[DateTime]::UtcNow.ToString('o')} |
      ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $evidence 'payments-cutover-rehearsal-latest.json')
    Write-Host 'PASS: synthetic history cutover and pre-release rollback passed; original stack restored. Fixture copies retained.' -ForegroundColor Green
}

