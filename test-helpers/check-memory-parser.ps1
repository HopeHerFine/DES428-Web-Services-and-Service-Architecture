$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/memory-sample.ps1')
$cases = @(@('0B',0),@('512KiB',524288),@('1.5MiB',1572864),@('2GiB',2147483648),@('1.5GB',1500000000),@('10kB',10000))
foreach ($case in $cases) {
    if ((Convert-DockerMemoryBytes $case[0]) -ne [long]$case[1]) { throw 'Memory unit conversion is incorrect.' }
}
$rejected = $false
try { Convert-DockerMemoryBytes 'not-a-measurement' | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'Malformed memory samples must not be counted as zero.' }
Write-Host 'PASS: Docker memory units are parsed correctly and malformed samples are rejected.'
