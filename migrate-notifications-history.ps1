$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$snapshotName = 'legacy-' + [Guid]::NewGuid().ToString('N') + '.json'
$reportName = 'legacy-report-' + [Guid]::NewGuid().ToString('N') + '.json'
$snapshotPath = Join-Path $PSScriptRoot ('runtime/probes/' + $snapshotName)
$reportPath = Join-Path $PSScriptRoot ('runtime/probes/' + $reportName)
try {
    New-Item -ItemType Directory -Force -Path 'runtime/probes' | Out-Null
    $compose = @('compose','-f','compose.migration-base.yml')
    # Keep build/progress output separate from data. JSON travels in shared UTF-8
    # files, never through Compose stdout or PowerShell's native text pipeline.
    & docker @compose build legacy-export notifications-worker
    if ($LASTEXITCODE -ne 0) { throw 'Historical migration image build failed.' }
    & docker @compose run --rm --no-deps -T -e "LEGACY_EXPORT_FILE=/probe-data/$snapshotName" legacy-export
    if ($LASTEXITCODE -ne 0) { throw 'Historical export failed; source was not changed.' }
    if (-not (Test-Path -LiteralPath $snapshotPath)) { throw 'Historical export did not create its snapshot.' }
    & docker @compose run --rm --no-deps -T -v './runtime/probes:/probe-data' notifications-worker python -m app.import_legacy --file "/probe-data/$snapshotName" --report "/probe-data/$reportName"
    if ($LASTEXITCODE -ne 0) { throw 'Historical import failed; inspect the error before retrying.' }
    if (-not (Test-Path -LiteralPath $reportPath)) { throw 'Historical importer did not create its report.' }
    $proof = Get-Content -Raw -Encoding UTF8 -LiteralPath $reportPath | ConvertFrom-Json
    if ($proof.result -ne 'PASS' -or ($proof.imported + $proof.already_imported) -ne $proof.source_rows) {
        throw 'Historical import verification failed.'
    }
    New-Item -ItemType Directory -Force -Path 'docs/evidence' | Out-Null
    $proof | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 'docs/evidence/legacy-import-latest.json'
    $proof | ConvertTo-Json -Compress
} finally {
    foreach ($temporaryPath in @($snapshotPath,$reportPath)) {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
    }
    Pop-Location
}
