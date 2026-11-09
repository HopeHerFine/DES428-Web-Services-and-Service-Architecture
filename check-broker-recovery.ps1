$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/probe-result.ps1')
try {
    $docker = (Get-Command docker -ErrorAction Stop).Source
    $compose = @('compose', '-f', 'compose.migration-base.yml')
    New-Item -ItemType Directory -Path 'runtime\probes', 'docs\evidence' -Force | Out-Null
    function Run-RecoveryStage([string]$stage) {
        & $docker @compose run --rm --no-deps broker-recovery python -m app.broker_recovery $stage
        if ($LASTEXITCODE -ne 0) { throw "Broker recovery stage failed: $stage" }
    }
    Write-Host 'This test stops RabbitMQ and Notifications worker briefly. User events may be delayed until recovery.'
    & $docker @compose up -d --wait --wait-timeout 180 rabbitmq notifications notifications-worker
    if ($LASTEXITCODE -ne 0) { throw 'Required services are not ready.' }
    & $docker @compose build broker-recovery
    if ($LASTEXITCODE -ne 0) { throw 'Recovery probe image build failed.' }
    Run-RecoveryStage 'cleanup'
    Run-RecoveryStage 'prepare'
    Write-Host '1/3: Stop worker, queue duplicate events, restart RabbitMQ while the worker stays stopped.'
    & $docker @compose stop --timeout 10 notifications-worker
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stop worker.' }
    Run-RecoveryStage 'queue'
    & $docker @compose stop --timeout 15 rabbitmq
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stop RabbitMQ.' }
    & $docker @compose up -d --wait --wait-timeout 120 rabbitmq
    if ($LASTEXITCODE -ne 0) { throw 'RabbitMQ did not recover.' }
    Run-RecoveryStage 'check-queued'
    Write-Host '2/3: Start worker and confirm eight deliveries have one effect.'
    & $docker @compose up -d --wait --wait-timeout 120 notifications-worker
    if ($LASTEXITCODE -ne 0) { throw 'Worker did not restart.' }
    Run-RecoveryStage 'verify-worker'
    Write-Host '3/3: Stop RabbitMQ, perform a domain change, then restore RabbitMQ and check outbox delivery.'
    & $docker @compose stop --timeout 15 rabbitmq
    if ($LASTEXITCODE -ne 0) { throw 'Unable to stop RabbitMQ.' }
    Run-RecoveryStage 'approve-while-down'
    & $docker @compose up -d --wait --wait-timeout 120 rabbitmq
    if ($LASTEXITCODE -ne 0) { throw 'RabbitMQ did not recover.' }
    $result = Invoke-NotificationsProbe -DockerExe $docker -ComposeArgs $compose -Service 'broker-recovery' -Check 'recovery'
    if ($result.result -ne 'PASS' -or $result.checks.Count -ne 3) { throw 'Incomplete recovery evidence.' }
    $result | Add-Member -NotePropertyName recorded_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o'))
    $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath 'docs\evidence\broker-recovery-latest.json' -Encoding utf8
    Write-Host 'PASS: queued events survived broker restart; worker resumed; pending outbox reached PostgreSQL once.' -ForegroundColor Green
} finally {
    if ($docker -and $compose) {
        & $docker @compose up -d --wait --wait-timeout 180 rabbitmq notifications-worker
        if ($LASTEXITCODE -eq 0) {
            & $docker @compose run --rm --no-deps broker-recovery python -m app.broker_recovery cleanup
        } else {
            Write-Warning 'Service restoration failed. Keep the probe manifest and restore RabbitMQ/worker before retrying.'
        }
    }
    Pop-Location
}
