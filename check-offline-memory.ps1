param([ValidateRange(10,180)][int]$ObserveSeconds = 60)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/clean-source.ps1')
. (Join-Path $PSScriptRoot 'scripts/memory-sample.ps1')
$docker = (Get-Command docker -ErrorAction Stop).Source
$previousProject = $env:COMPOSE_PROJECT_NAME
$project = 'noti-offline-' + [Guid]::NewGuid().ToString('N').Substring(0,12)
$scratch = Join-Path $PSScriptRoot ('runtime/offline/' + $project)
$stopFile = Join-Path $scratch 'stop-memory-sampling'
$sampleFile = Join-Path $scratch 'memory-samples.jsonl'
$diagnosticFile = Join-Path $scratch 'memory-sampling-errors.jsonl'
$samplerStdout = Join-Path $scratch 'memory-sampler.stdout.log'
$samplerStderr = Join-Path $scratch 'memory-sampler.stderr.log'
$originalStopped = $false
$testCreated = $false
$sampler = $null
$samples = @()
$samplingErrors = @()
$samplingJobError = $null
$passed = $false
try {
    $engineBytes = & $docker info --format '{{.MemTotal}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop must be running.' }
    $engineBytes = [long]$engineBytes
    if ($engineBytes -le 0 -or $engineBytes -gt 8589934592) {
        throw 'This rehearsal requires Docker Engine memory at or below 8 GiB. Set the Docker/WSL memory limit first, then retry.'
    }
    if (-not (Test-Path '.env.notifications')) { & .\start-notifications.ps1 -PrepareOnly }
    $original = @('compose','--env-file','.env.notifications','-f','docker-compose.yml')
    $raw = & $docker @original config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Original stack configuration is invalid.' }
    $originalProject = (($raw -join "`n") | ConvertFrom-Json).name
    $running = @(& $docker ps -q --filter "label=com.docker.compose.project=$originalProject")
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect original stack.' }
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    $files = @(Get-NotificationsCleanSourceFiles -Root $PSScriptRoot)
    foreach ($relative in $files) {
        $destination = Join-Path $scratch $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $relative) -Destination $destination
    }
    if (Test-Path (Join-Path $scratch '.env.notifications')) { throw 'Clean source unexpectedly inherited local credentials.' }
    $env:COMPOSE_PROJECT_NAME = $project
    & (Join-Path $scratch 'start-notifications.ps1') -PrepareOnly
    Push-Location $scratch
    try {
        $prepare = @('compose','--env-file','.env.notifications','-f','compose.notifications.yml','--profile','identity-config')
        Write-Host 'ONLINE PREPARATION: pulling tools and building two local application images.'
        & $docker @prepare pull keycloak gateway notifications-db rabbitmq jaeger prometheus grafana
        if ($LASTEXITCODE -ne 0) { throw 'Unable to cache tool images.' }
        & $docker @prepare build edemand notifications
        if ($LASTEXITCODE -ne 0) { throw 'Unable to build local application images.' }
        $raw = & $docker @prepare config --format json
        if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve prepared configuration.' }
        [IO.File]::WriteAllText((Join-Path $scratch 'resolved.json'),($raw -join "`n"),[Text.UTF8Encoding]::new($false))
        $appImage = "$project-edemand"
        $apiImage = "$project-notifications"
        & $docker run --rm --user 0:0 -v "${scratch}:/source" -w /source $apiImage python scripts/offline_compose.py --input resolved.json --output docker-compose.yml --project $project --source-root $scratch --app-image $appImage --api-image $apiImage
        if ($LASTEXITCODE -ne 0) { throw 'Unable to freeze offline configuration.' }
        & $docker compose -f docker-compose.yml config --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Frozen offline configuration is invalid.' }
        $images = @(& $docker compose -f docker-compose.yml config --images | Sort-Object -Unique)
        foreach ($image in $images) {
            & $docker image inspect --format '{{.Id}}' $image | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Prepared image is missing: $image" }
        }
        if ($running.Count -gt 0) {
            & $docker compose --project-name $originalProject --env-file (Join-Path $PSScriptRoot '.env.notifications') -f (Join-Path $PSScriptRoot 'docker-compose.yml') down
            if ($LASTEXITCODE -ne 0) { throw 'Unable to release original stack ports.' }
            $originalStopped = $true
        }
        $sampler = Start-NotificationsMemorySampler -DockerExe $docker -ProjectName $project -StopFile $stopFile `
            -OutputFile $sampleFile -DiagnosticFile $diagnosticFile -SamplerScript (Join-Path $PSScriptRoot 'scripts/memory-sampler.ps1') `
            -StdoutFile $samplerStdout -StderrFile $samplerStderr
        Write-Host 'OFFLINE PHASE: image pulls/builds disabled; containers have no external network.'
        $testCreated = $true
        & $docker compose -f docker-compose.yml up -d --wait --wait-timeout 360
        if ($LASTEXITCODE -ne 0) { & $docker compose logs --tail 60; throw 'Offline cold boot failed.' }
        $network = & $docker network inspect --format '{{.Internal}}' "${project}_default"
        if ($LASTEXITCODE -ne 0 -or $network -ne 'true') { throw 'Offline network is not isolated.' }
        foreach ($module in @('smoke','smoke_monolith','smoke_gateway','smoke_registration','observability_probe')) {
            & $docker compose run --rm --no-deps notifications-worker python -m "app.$module"
            if ($LASTEXITCODE -ne 0) { throw "Offline functional check failed: $module" }
        }
        $workloadStart = [DateTime]::UtcNow
        & $docker compose run --rm --no-deps -v './runtime/probes:/probe-data' notifications-worker python -m app.offline_workload --seconds $ObserveSeconds --report /probe-data/offline-workload.json
        if ($LASTEXITCODE -ne 0) { throw 'Authenticated offline workload failed.' }
        $workloadEnd = [DateTime]::UtcNow
        $loadResult = Get-Content -Raw -Encoding UTF8 'runtime/probes/offline-workload.json' | ConvertFrom-Json
        if ($loadResult.result -ne 'PASS' -or $loadResult.successful_read_updates -lt 1) { throw 'Offline workload evidence is incomplete.' }
        $ids = @(& $docker compose ps -a -q)
        foreach ($id in $ids) {
            $oom = & $docker inspect --format '{{.State.OOMKilled}}' $id
            if ($LASTEXITCODE -ne 0 -or $oom -ne 'false') { throw 'A test container was killed by the memory limit.' }
        }
        $passed = $true
    } finally { Pop-Location }
} finally {
    if ($sampler) {
        [IO.File]::WriteAllText($stopFile,'stop')
        if (-not $sampler.WaitForExit(30000)) {
            $sampler.Kill()
            $sampler.WaitForExit()
            $samplingJobError = 'Memory sampler did not stop within 30 seconds.'
        } elseif ($sampler.ExitCode -ne 0) {
            $detail = if (Test-Path -LiteralPath $samplerStderr) { Get-Content -Raw -LiteralPath $samplerStderr } else { 'No stderr log was created.' }
            $samplingJobError = "Sampler exit code $($sampler.ExitCode): $detail"
        }
        if (Test-Path -LiteralPath $sampleFile) {
            $samples = @(Get-Content -Encoding UTF8 -LiteralPath $sampleFile | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        }
        if (Test-Path -LiteralPath $diagnosticFile) {
            $samplingErrors = @(Get-Content -Encoding UTF8 -LiteralPath $diagnosticFile | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        }
        $sampler.Dispose()
    }
    $cleanupExit = 0
    $restoreExit = 0
    if ($testCreated) {
        & $docker compose --project-name $project -f (Join-Path $scratch 'docker-compose.yml') down --volumes --remove-orphans
        $cleanupExit = $LASTEXITCODE
    }
    $env:COMPOSE_PROJECT_NAME = $previousProject
    if ($originalStopped) {
        & $docker compose --project-name $originalProject --env-file .env.notifications -f docker-compose.yml up -d --wait --wait-timeout 360
        $restoreExit = $LASTEXITCODE
    }
    Pop-Location
    if ($cleanupExit -ne 0 -or $restoreExit -ne 0) { throw 'Test cleanup or original-stack restoration failed.' }
}
if (-not $passed) { throw 'Offline functional checks did not complete; no PASS evidence was saved.' }
if ($samplingJobError) { throw "Offline functional checks passed, but the memory sampler failed: $samplingJobError" }
if ($samples.Count -lt 5) {
    $detail = if ($samplingErrors.Count) { $samplingErrors[-1].error } else { 'No samples were written by the background process.' }
    throw "Offline functional checks passed, but only $($samples.Count) RAM samples were captured. $detail Raw files: $scratch"
}
$loadSamples = @($samples | Where-Object {
    $time = [DateTime]::Parse($_.time).ToUniversalTime()
    $time -ge $workloadStart -and $time -le $workloadEnd
})
$minimumLoadSamples = [Math]::Max(2,[Math]::Min(5,[Math]::Floor($ObserveSeconds / 4)))
if ($loadSamples.Count -lt $minimumLoadSamples) { throw 'Too few RAM samples during the workload. Raw sampling files remain in the test directory.' }
$lastSampleTime = [DateTime]::Parse($loadSamples[-1].time).ToUniversalTime()
if (($workloadEnd - $lastSampleTime).TotalSeconds -gt 15) { throw 'RAM sampling stopped before the workload finished; no PASS evidence was saved.' }
$peak = [long](($samples | Measure-Object -Property total_bytes -Maximum).Maximum)
if ($peak -ge 8589934592) { throw 'Sampled container usage exceeded 8 GiB.' }
$evidence = Join-Path $PSScriptRoot 'docs/evidence'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$samples | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $evidence 'offline-memory-samples.json')
@{result='PASS';probe='offline-memory';project=$project;source_files=$files.Count;
    cached_images=$images.Count;pulls_and_builds_during_boot=$false;internal_network=$true;
    engine_memory_bytes=$engineBytes;peak_sampled_container_bytes=$peak;samples=$samples.Count;workload_samples=$loadSamples.Count;discarded_sampling_polls=$samplingErrors.Count;
    workload=$loadResult;memory_method='Docker CLI usage excluding cache; sampled maximum, not continuous peak';
    fresh_volumes=$true;original_stack_restored=[bool]$originalStopped;recorded_at=[DateTime]::UtcNow.ToString('o')} |
    ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $evidence 'offline-memory-latest.json')
Write-Host ('PASS: offline cold boot; peak sampled containers {0:N2} GiB within Docker Engine {1:N2} GiB.' -f ($peak/1GB),($engineBytes/1GB)) -ForegroundColor Green
