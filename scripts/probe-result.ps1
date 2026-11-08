function Invoke-NotificationsProbe {
    param([string]$DockerExe = 'docker', [string[]]$ComposeArgs,
          [string]$Service, [string]$Check)
    New-Item -ItemType Directory -Force -Path 'runtime/probes' | Out-Null
    $name = 'probe-result-' + [Guid]::NewGuid().ToString('N') + '.json'
    $path = Join-Path (Get-Location).Path ('runtime/probes/' + $name)
    try {
        & $DockerExe @ComposeArgs run --rm --no-deps -T -v './runtime/probes:/probe-data' $Service python -m app.probe_runner $Check --report "/probe-data/$name" |
            ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { throw "Probe failed: $Check. No PASS evidence was saved." }
        if (-not (Test-Path -LiteralPath $path)) { throw "Probe report missing: $Check" }
        $proof = Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json
        if ($proof.result -ne 'PASS') { throw "Probe did not pass: $Check" }
        return $proof
    } finally {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
}
