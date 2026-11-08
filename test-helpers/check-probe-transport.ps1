$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $sourceRoot 'scripts/probe-result.ps1')
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('probe-shell-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
Push-Location $scratch
try {
    $script:simulateFailure = $false
    function docker {
        Write-Output '. noisy Docker build output'
        Write-Output 'Container Created - not JSON'
        if ($script:simulateFailure) { $global:LASTEXITCODE = 1; return }
        $index = [Array]::IndexOf($args,'--report')
        if ($index -lt 0) { throw 'Report argument missing' }
        $name = ($args[$index + 1] -split '/')[-1]
        '{"result":"PASS","probe":"test-only"}' | Set-Content -Encoding UTF8 ('runtime/probes/' + $name)
        $global:LASTEXITCODE = 0
    }
    foreach ($check in @('security','resilience','recovery','observability')) {
        $result = Invoke-NotificationsProbe -ComposeArgs @('compose') -Service 'test-only' -Check $check
        if ($result.result -ne 'PASS') { throw 'Noisy stdout broke result transport' }
    }
    $script:simulateFailure = $true
    $rejected = $false
    try { Invoke-NotificationsProbe -ComposeArgs @('compose') -Service 'test-only' -Check 'security' | Out-Null }
    catch { $rejected = $true }
    if (-not $rejected) { throw 'Failed Docker command incorrectly passed' }
    if (@(Get-ChildItem 'runtime/probes').Count -ne 0) { throw 'Temporary reports were not removed' }
    Write-Host 'PASS: all four probe transports ignore Docker stdout, reject failures and clean reports.'
} finally { Pop-Location }
