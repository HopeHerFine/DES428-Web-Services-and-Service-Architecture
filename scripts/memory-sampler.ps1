param([Parameter(Mandatory=$true)][string]$DockerExe,
      [Parameter(Mandatory=$true)][string]$ProjectName,
      [Parameter(Mandatory=$true)][string]$StopFile,
      [Parameter(Mandatory=$true)][string]$OutputFile,
      [Parameter(Mandatory=$true)][string]$DiagnosticFile)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'memory-sample.ps1')
$deadline = [DateTime]::UtcNow.AddMinutes(15)
while (-not (Test-Path -LiteralPath $StopFile) -and [DateTime]::UtcNow -lt $deadline) {
    try {
        $ids = @(& $DockerExe ps -q --filter "label=com.docker.compose.project=$ProjectName")
        if ($LASTEXITCODE -ne 0) { throw 'Docker cannot list test containers.' }
        if ($ids.Count -gt 0) {
            $lines = @(& $DockerExe stats --no-stream --format '{{json .}}' @ids)
            if ($LASTEXITCODE -ne 0) { throw 'Docker stats returned a nonzero exit code (a container may have exited during sampling).' }
            $total = [long]0
            $containers = @()
            foreach ($line in $lines) {
                $row = $line | ConvertFrom-Json
                if (-not $row.Name.StartsWith($ProjectName + '-')) { throw 'Docker stats returned a container outside the test project.' }
                $bytes = Convert-DockerMemoryBytes ($row.MemUsage.Split('/')[0])
                $total += $bytes
                $containers += @{name=$row.Name;memory_bytes=$bytes}
            }
            if ($containers.Count -gt 0) {
                @{time=[DateTime]::UtcNow.ToString('o');total_bytes=$total;containers=$containers} |
                    ConvertTo-Json -Compress -Depth 6 | Add-Content -Encoding UTF8 -LiteralPath $OutputFile
            }
        }
    } catch {
        # One-shot probes can exit between ps and stats. Discard that incomplete
        # poll, retain earlier samples and make the gap visible in the report.
        @{time=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message} |
            ConvertTo-Json -Compress | Add-Content -Encoding UTF8 -LiteralPath $DiagnosticFile
    }
    Start-Sleep -Seconds 1
}
