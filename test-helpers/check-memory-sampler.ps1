$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('sampler-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
$stop = Join-Path $scratch 'stop'
$samples = Join-Path $scratch 'samples.jsonl'
$errors = Join-Path $scratch 'errors.jsonl'
$script:polls = 0
function docker {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'ps') { 'fixture-id'; return }
    $script:polls++
    if ($script:polls -eq 1) { $global:LASTEXITCODE = 1; return }
    '{"Name":"sampler-test-notifications-1","MemUsage":"1.5MiB / 512MiB"}'
    if ($script:polls -ge 3) { 'stop' | Set-Content -LiteralPath $stop }
}
& (Join-Path $sourceRoot 'scripts/memory-sampler.ps1') -DockerExe docker -ProjectName sampler-test -StopFile $stop -OutputFile $samples -DiagnosticFile $errors
$rows = @(Get-Content -LiteralPath $samples | ForEach-Object { $_ | ConvertFrom-Json })
$failures = @(Get-Content -LiteralPath $errors | ForEach-Object { $_ | ConvertFrom-Json })
if ($rows.Count -ne 2 -or $rows[0].total_bytes -ne 1572864 -or $failures.Count -ne 1) {
    throw 'A transient stats failure lost valid samples or was not recorded.'
}
Write-Host 'PASS: memory samples persist despite an incomplete Docker poll; gaps are recorded.'
$fakeDocker = Join-Path $scratch 'fake-docker.cmd'
@'
@echo off
if "%1"=="ps" (
echo fixture-id
exit /b 0
)
echo {"Name":"sampler-test-notifications-1","MemUsage":"1.5MiB / 512MiB"}
exit /b 0
'@ | Set-Content -Encoding ASCII -LiteralPath $fakeDocker
$jobStop = Join-Path $scratch 'job-stop'
$jobSamples = Join-Path $scratch 'job-samples.jsonl'
$jobErrors = Join-Path $scratch 'job-errors.jsonl'
. (Join-Path $sourceRoot 'scripts/memory-sample.ps1')
$job = Start-NotificationsMemorySampler -DockerExe $fakeDocker -ProjectName sampler-test -StopFile $jobStop `
    -OutputFile $jobSamples -DiagnosticFile $jobErrors -SamplerScript (Join-Path $sourceRoot 'scripts/memory-sampler.ps1') `
    -StdoutFile (Join-Path $scratch 'stdout.log') -StderrFile (Join-Path $scratch 'stderr.log')
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $count = if (Test-Path -LiteralPath $jobSamples) { @(Get-Content -LiteralPath $jobSamples).Count } else { 0 }
    } while ($count -lt 2 -and -not $job.HasExited -and [DateTime]::UtcNow -lt $deadline)
} finally {
    'stop' | Set-Content -LiteralPath $jobStop
    if (-not $job.WaitForExit(20000)) { $job.Kill(); $job.WaitForExit() }
    $exitCode = $job.ExitCode
    $job.Dispose()
}
if ($exitCode -ne 0) { throw ('Sampler subprocess failed: ' + (Get-Content -Raw (Join-Path $scratch 'stderr.log'))) }
if ($count -lt 2) { throw 'Real Windows background job did not persist samples.' }
Write-Host 'PASS: hidden Windows PowerShell subprocess persists readable memory samples without remoting jobs.'
