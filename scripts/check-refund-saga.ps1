$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$project = 'homeservice-saga-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$override = Join-Path ([IO.Path]::GetTempPath()) "$project.yml"
$stack = @('--project-name', $project, '-f', 'docker-compose.yml', '-f', 'compose.payments.yml', '-f', $override)

Push-Location -LiteralPath $repo
try {
    @"
services:
  gateway:
    ports: !reset []
  grafana:
    ports: !reset []
  jaeger:
    ports: !reset []
  prometheus:
    ports: !reset []
  rabbitmq:
    ports: !reset []
"@ | Set-Content -LiteralPath $override -Encoding ascii
    docker compose @stack config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Saga Compose configuration is invalid.' }

    try {
        docker compose @stack up --build -d --wait --wait-timeout 360
        if ($LASTEXITCODE -ne 0) { throw 'Could not start disposable Saga stack.' }
        docker compose @stack run --rm --no-deps notifications-worker python -m app.smoke_payments --saga-only
        if ($LASTEXITCODE -ne 0) { throw 'Saga probe failed.' }
    } finally {
        docker compose @stack down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw "Could not clean up disposable project $project." }
    }
    Write-Host 'PASS: refund Saga verified on disposable data.' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $override) { Remove-Item -LiteralPath $override }
    Pop-Location
}
