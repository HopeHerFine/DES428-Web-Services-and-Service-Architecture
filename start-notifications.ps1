param([switch]$WithMonolith)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        $dockerExe = $dockerCommand.Source
    } else {
        $dockerPaths = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
            'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
        )
        $dockerExe = $dockerPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $dockerExe) { throw 'Docker Desktop was not found.' }
    $env:PATH = (Split-Path -Parent $dockerExe) + ';' + $env:PATH
    & $dockerExe info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop and wait for Engine running, then retry.' }

    function New-LocalPassword {
            $bytes = New-Object byte[] 24
            $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
            return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    if (-not (Test-Path -LiteralPath '.env.notifications')) {
        $dbPassword = New-LocalPassword
        $brokerPassword = New-LocalPassword
        @(
            "NOTIFICATIONS_DB_PASSWORD=$dbPassword"
            "RABBITMQ_PASSWORD=$brokerPassword"
            'JWT_ISSUER=http://localhost:8080/realms/homeservice'
            'JWT_JWKS_URL=http://keycloak:8080/realms/homeservice/protocol/openid-connect/certs'
        ) | Set-Content -LiteralPath '.env.notifications' -Encoding ascii
        Write-Host 'Created local settings. Passwords are stored in the git-ignored .env.notifications.'
    }
    # Upgrade only managed identity settings; never replace database/broker passwords.
    $settingsLines = @(Get-Content -LiteralPath '.env.notifications')
    $settingsLines = @($settingsLines | Where-Object { $_ -notmatch '^JWT_(ISSUER|JWKS_URL)=' })
    $settingsLines += 'JWT_ISSUER=http://localhost:8080/auth/realms/homeservice'
    $settingsLines += 'JWT_JWKS_URL=http://keycloak:8080/auth/realms/homeservice/protocol/openid-connect/certs'
    foreach ($settingName in @('JWT_SECRET', 'KEYCLOAK_ADMIN_PASSWORD')) {
        if (-not ($settingsLines | Where-Object { $_ -match "^$settingName=.+" })) {
            $settingsLines = @($settingsLines | Where-Object { $_ -notmatch "^$settingName=" })
            $settingsLines += "$settingName=$(New-LocalPassword)"
        }
    }
    $settingsLines | Set-Content -LiteralPath '.env.notifications' -Encoding ascii
    $composeArgs = @('compose', '--env-file', '.env.notifications', '-f', 'compose.notifications.yml')
    if ($WithMonolith) { $composeArgs += @('--profile', 'migration') }
    & $dockerExe @composeArgs config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose settings validation failed.' }
    & $dockerExe @composeArgs up --build -d --wait --wait-timeout 360
    if ($LASTEXITCODE -ne 0) {
        & $dockerExe @composeArgs logs --tail 60
        throw 'Containers did not become ready; see logs above.'
    }
    & $dockerExe @composeArgs run --rm --no-deps notifications-worker python -m app.smoke
    if ($LASTEXITCODE -ne 0) {
        & $dockerExe @composeArgs logs --tail 60 notifications-worker
        throw 'RabbitMQ/PostgreSQL integration probe failed.'
    }
    if ($WithMonolith) {
        & $dockerExe @composeArgs run --build --rm --no-deps keycloak-config
        if ($LASTEXITCODE -ne 0) { throw 'Keycloak client scope update failed; existing realm has been preserved.' }
        & $dockerExe @composeArgs run --rm --no-deps notifications-worker python -m app.smoke_monolith
        if ($LASTEXITCODE -ne 0) {
            & $dockerExe @composeArgs logs --tail 60 edemand notifications-worker
            throw 'Real monolith outbox integration probe failed.'
        }
        & $dockerExe @composeArgs run --rm --no-deps notifications-worker python -m app.smoke_gateway
        if ($LASTEXITCODE -ne 0) {
            & $dockerExe @composeArgs logs --tail 60 gateway keycloak edemand notifications
            throw 'Keycloak/gateway/browser inbox integration probe failed.'
        }
        Write-Host 'Homeservice through nginx: http://localhost:8080'
    }
    & $dockerExe @composeArgs ps
    Write-Host ''
    Write-Host 'PASS: Notifications, PostgreSQL and RabbitMQ are running.' -ForegroundColor Green
    if ($WithMonolith) { Write-Host 'API docs: http://localhost:8080/notification-docs' }
    Write-Host 'RabbitMQ screen: http://127.0.0.1:15672'
    Write-Host 'Use the seven seeded accounts for Keycloak login. New account provisioning is not implemented yet.'
} finally {
    Pop-Location
}
