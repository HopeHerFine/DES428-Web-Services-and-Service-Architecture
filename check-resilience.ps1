$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/probe-result.ps1')
try {
    $docker = (Get-Command docker -ErrorAction Stop).Source
    $compose = @('compose', '--env-file', '.env.notifications', '-f', 'compose.notifications.yml', '--profile', 'migration')
    New-Item -ItemType Directory -Path 'runtime\faults', 'runtime\probes', 'docs\evidence' -Force | Out-Null
    '{"mode":"none"}' | Set-Content -LiteralPath 'runtime\faults\notifications.json' -Encoding ascii
    Write-Host 'This local demo briefly delays/fails Notifications requests; normal behavior is restored in finally.'
    & $docker @compose up --build -d --wait --wait-timeout 180 notifications notifications-worker
    if ($LASTEXITCODE -ne 0) { throw 'Notifications did not become ready.' }
    # Resolve a newly recreated upstream through nginx before starting the fault tests.
    $reachable = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Invoke-WebRequest -Uri 'http://localhost:8080/api/notifications' -UseBasicParsing -TimeoutSec 3 | Out-Null }
        catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { $reachable = $true; break } }
        Start-Sleep -Seconds 1
    }
    if (-not $reachable) { throw 'Gateway cannot reach the Notifications API; start the full stack first.' }
    & $docker @compose build resilience-fixture
    if ($LASTEXITCODE -ne 0) { throw 'Fixture image build failed.' }
    & $docker @compose pull resilience-probe
    if ($LASTEXITCODE -ne 0) { throw 'Unable to prepare the Node probe image.' }
    & $docker @compose run --rm --no-deps resilience-fixture python -m app.resilience_fixture cleanup
    if ($LASTEXITCODE -ne 0) { throw 'Unable to clean up a previous incomplete probe.' }
    & $docker @compose run --rm --no-deps resilience-fixture python -m app.resilience_fixture prepare
    if ($LASTEXITCODE -ne 0) { throw 'Fixture setup failed.' }
    & $docker @compose run --rm --no-deps resilience-probe
    if ($LASTEXITCODE -ne 0) { throw 'HTTP fault/retry/concurrency tests failed.' }
    $result = Invoke-NotificationsProbe -DockerExe $docker -ComposeArgs $compose -Service 'resilience-fixture' -Check 'resilience'
    if ($result.result -ne 'PASS') { throw 'Probe returned an unexpected result.' }
    $result | Add-Member -NotePropertyName recorded_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o'))
    $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath 'docs\evidence\resilience-latest.json' -Encoding utf8
    Write-Host 'PASS: three faults survived; 8 concurrent requests committed one receipt.' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath 'runtime\faults') {
        '{"mode":"none"}' | Set-Content -LiteralPath 'runtime\faults\notifications.json' -Encoding ascii
    }
    if ($docker -and $compose) {
        & $docker @compose run --rm --no-deps resilience-fixture python -m app.resilience_fixture cleanup
    }
    Pop-Location
}
