$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/probe-result.ps1')
$composeArgs = @('compose', '-f', 'docker-compose.yml')
& docker @composeArgs up --build -d --wait --wait-timeout 360
if ($LASTEXITCODE -ne 0) { throw 'Observability stack did not start; inspect Compose logs.' }
# Mounted nginx configuration needs an explicit reload for an existing container.
& docker @composeArgs exec -T gateway nginx -s reload
if ($LASTEXITCODE -ne 0) { throw 'Gateway configuration reload failed.' }
$proof = Invoke-NotificationsProbe -ComposeArgs $composeArgs -Service 'notifications-worker' -Check 'observability'
if ($proof.result -ne 'PASS') { throw 'Observability verification did not return PASS.' }
$proof | Add-Member -NotePropertyName recorded_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o'))
New-Item -ItemType Directory -Force -Path 'docs/evidence' | Out-Null
$proof | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 'docs/evidence/observability-latest.json'
$proof | ConvertTo-Json -Compress -Depth 10
Write-Host 'Dashboard: http://localhost:3000/d/notifications'
Write-Host 'Traces: http://localhost:16686'
Write-Host 'Scrape targets: http://localhost:9090/targets'
