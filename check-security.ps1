$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/probe-result.ps1')
try {
    $docker = Get-Command docker -ErrorAction Stop
    $compose = @('compose', '--env-file', '.env.notifications', '-f', 'compose.notifications.yml', '--profile', 'migration')
    & $docker.Source @compose ps
    & $docker.Source @compose build security-probe
    if ($LASTEXITCODE -ne 0) { throw 'Security probe image build failed.' }
    $result = Invoke-NotificationsProbe -DockerExe $docker.Source -ComposeArgs $compose -Service 'security-probe' -Check 'security'
    if ($result.result -ne 'PASS') { throw 'Security check returned an unexpected result.' }
    New-Item -ItemType Directory -Path 'docs\evidence' -Force | Out-Null
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath 'docs\evidence\security-latest.json' -Encoding utf8
    Write-Host 'PASS: live Keycloak/Gateway checks saved to docs/evidence/security-latest.json' -ForegroundColor Green
} finally { Pop-Location }
