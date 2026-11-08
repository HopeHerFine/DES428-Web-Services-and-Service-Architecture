# Regression check with a fake Docker command; never touches application data.
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('history-shell-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'migrate-notifications-history.ps1') -Destination $testRoot
function docker {
    $global:LASTEXITCODE = 0
    if ($args -contains 'build') { Write-Output '. noisy build output'; return }
    if ($args -contains 'legacy-export') {
        $setting = $args | Where-Object { $_ -like 'LEGACY_EXPORT_FILE=*' }
        $name = ($setting -split '/')[-1]
        '{"version":1,"source":"test-only","rows":[]}' | Set-Content -Encoding UTF8 (Join-Path $testRoot ('runtime/probes/' + $name))
        Write-Output 'Container Created - not JSON'
        return
    }
    $index = [Array]::IndexOf($args,'--report')
    if ($index -lt 0) { throw 'Missing report argument' }
    $name = ($args[$index + 1] -split '/')[-1]
    '{"result":"PASS","source_rows":0,"imported":0,"already_imported":0}' |
        Set-Content -Encoding UTF8 (Join-Path $testRoot ('runtime/probes/' + $name))
    Write-Output '. noisy importer output'
}
& (Join-Path $testRoot 'migrate-notifications-history.ps1') | Out-Null
$report = Get-Content -Raw (Join-Path $testRoot 'docs/evidence/legacy-import-latest.json') | ConvertFrom-Json
if ($report.result -ne 'PASS') { throw 'Noisy output broke migration transport' }
if (@(Get-ChildItem (Join-Path $testRoot 'runtime/probes')).Count -ne 0) { throw 'Temporary snapshots were not removed' }
Write-Host 'PASS: migration transport ignores Docker stdout and removes temporary snapshots.'
