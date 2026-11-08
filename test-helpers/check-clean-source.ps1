$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $sourceRoot 'scripts/clean-source.ps1')
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('clean-source-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
$paths = @('app/page.js','app/.env.local','app/private.key','app/node_modules/no.js',
    'services/notifications/app/main.py','services/notifications/.env.example','services/notifications/.env',
    'services/notifications/__pycache__/main.pyc','docs/guide.md','docs/evidence/pass.json',
    '.github/workflows/test.yml','contracts/pacts/contract.json','contracts/node_modules/no.js',
    'package.json','.env.notifications','data/private.db','runtime/probes/token.json')
foreach ($path in $paths) {
    $destination = Join-Path $fixture $path
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    'test-only' | Set-Content -LiteralPath $destination
}
@{directories=@('app','services','docs','.github','contracts');files=@('package.json','.env.notifications');required=@('package.json')} |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $fixture '.clean-source.json')
$files = @(Get-NotificationsCleanSourceFiles -Root $fixture)
$expected = @('.github/workflows/test.yml','app/page.js','contracts/pacts/contract.json','docs/guide.md','package.json','services/notifications/.env.example','services/notifications/app/main.py')
if (@(Compare-Object ($expected | Sort-Object) ($files | Sort-Object)).Count -ne 0) { throw 'Clean-source selection included private/generated files or omitted source.' }
# Exercise real preparation without Git, local settings or Docker calls.
function git { throw 'Git must not be required for clean-source preparation.' }
function docker { throw 'PrepareOnly must not require Docker.' }
& (Join-Path $sourceRoot 'check-clean-start.ps1') -PrepareOnly
Write-Host 'PASS: source export works without Git and excludes local secrets, databases and generated files.'
