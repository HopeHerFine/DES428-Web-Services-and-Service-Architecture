param(
    [string]$Python = 'python',
    [string]$DatabasePath = (Join-Path $PSScriptRoot 'notifications-local.db'),
    [string]$Issuer = 'http://localhost:8080/realms/homeservice',
    [string]$JwksUrl = 'http://localhost:8080/realms/homeservice/protocol/openid-connect/certs',
    [int]$Port = 8001
)
$ErrorActionPreference = 'Stop'
# SQLite is for local API development only. Docker deployment uses PostgreSQL.
# Protected endpoints still require a real token from the configured issuer.
$env:DATABASE_URL = 'sqlite:///' + [IO.Path]::GetFullPath($DatabasePath).Replace('\', '/')
$env:JWT_ISSUER = $Issuer
$env:JWT_AUDIENCE = 'notifications'
$env:JWT_JWKS_URL = $JwksUrl
Push-Location $PSScriptRoot
try {
    & $Python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --log-level info
    if ($LASTEXITCODE -ne 0) { throw "Notifications exited with code $LASTEXITCODE" }
}
finally { Pop-Location }
