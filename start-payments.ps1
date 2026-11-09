# Starts the exact retained PostgreSQL volume selected by a verified cutover.
$ErrorActionPreference='Stop'
Push-Location $PSScriptRoot
try {
    $active=Join-Path $PSScriptRoot 'runtime/payments-cutover/active.json'
    if (-not (Test-Path -LiteralPath $active)) { throw 'No cutover receipt exists. Use switch-payments.ps1 first.' }
    $receipt=Get-Content -Raw -Encoding UTF8 -LiteralPath $active | ConvertFrom-Json
    if ($receipt.run_id -notmatch '^[a-f0-9-]{36}$') { throw 'Invalid retained cutover receipt.' }
    if ($receipt.phase -ne 'released' -or $receipt.project -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Cutover has not been publicly released. Resume switch-payments.ps1 instead.' }
    $override=Join-Path $PSScriptRoot ('runtime/payments-cutover/'+$receipt.run_id+'/volume.json')
    if (-not (Test-Path -LiteralPath $override)) { throw 'Retained Payments volume configuration is missing; do not substitute an empty database.' }
    & docker compose --project-name $receipt.project -f docker-compose.yml -f compose.payments.yml -f $override up -d --wait --wait-timeout 360
    if ($LASTEXITCODE -ne 0) { throw 'Payments startup failed. Its volumes were preserved.' }
} finally { Pop-Location }
