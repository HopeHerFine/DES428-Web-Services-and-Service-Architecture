# Briefly stops the regular stack, tests clean isolated volumes, then restores it.
param([switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/clean-source.ps1')
$previousProject = $env:COMPOSE_PROJECT_NAME
$testProject = 'payments-pilot-' + ([Guid]::NewGuid().ToString('N').Substring(0,12))
$scratch = Join-Path ([IO.Path]::GetTempPath()) $testProject
$compose = @('compose','-f','compose.migration-base.yml')
$originalStopped = $false
$passed = $false
try {
    $files = @(Get-NotificationsCleanSourceFiles -Root $PSScriptRoot)
    if ($files.Count -eq 0) { throw 'Clean-source manifest did not select any files.' }
    New-Item -ItemType Directory -Path $scratch | Out-Null
    $separator = [IO.Path]::DirectorySeparatorChar
    $sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd($separator) + $separator
    foreach ($relative in $files) {
        $source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $relative))
        $destination = [IO.Path]::GetFullPath((Join-Path $scratch $relative))
        if (-not $source.StartsWith($sourceRoot,[StringComparison]::OrdinalIgnoreCase) -or
            -not $destination.StartsWith(($scratch + $separator),[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Source path escaped the clean-test directory.'
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }
    if (Test-Path -LiteralPath (Join-Path $scratch '.env.notifications')) { throw 'Clean source unexpectedly contains local secrets.' }
    if ($PrepareOnly) {
        Write-Host "Prepared $($files.Count) source files without inherited secrets. Docker was not changed."
        return
    }
    $configuration = & docker @compose config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Original Compose configuration is invalid.' }
    $originalProject = (($configuration -join "`n") | ConvertFrom-Json).name
    if ($originalProject -eq $testProject) { throw 'Clean-test project must be separate.' }
    Write-Host 'Temporarily stopping the regular stack; its database volumes will be preserved.'
    & docker @compose down
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the regular stack.' }
    $originalStopped = $true
    $env:COMPOSE_PROJECT_NAME = $testProject
    Push-Location $scratch
    try {
        & docker compose -f compose.migration-base.yml -f compose.payments.yml up --build -d --wait --wait-timeout 360
        if ($LASTEXITCODE -ne 0) { & docker compose -f compose.migration-base.yml -f compose.payments.yml logs --tail 60; throw 'Raw-source docker compose up failed.' }
        if (Test-Path -LiteralPath '.env.notifications') { throw 'Raw boot unexpectedly wrote host-side credentials.' }
        foreach ($module in @('smoke_payments')) {
            & docker compose -f compose.migration-base.yml -f compose.payments.yml run --rm --no-deps notifications-worker python -m "app.$module"
            if ($LASTEXITCODE -ne 0) { throw "Raw-source integration check failed: $module" }
        }
        $passed = $true
    } finally { Pop-Location }
} finally {
    if ($originalStopped) {
        # Delete only volumes belonging to this freshly generated test project.
        & docker compose --project-name $testProject -f (Join-Path $scratch 'compose.migration-base.yml') -f (Join-Path $scratch 'compose.payments.yml') down --volumes --remove-orphans
        $cleanupExit = $LASTEXITCODE
        $env:COMPOSE_PROJECT_NAME = $previousProject
        & docker compose --project-name $originalProject -f compose.migration-base.yml up -d --wait --wait-timeout 360
        $restoreExit = $LASTEXITCODE
        if ($cleanupExit -ne 0 -or $restoreExit -ne 0) { throw 'Clean-test cleanup or original-stack restoration failed.' }
    }
    $env:COMPOSE_PROJECT_NAME = $previousProject
    Pop-Location
}
if ($passed) {
    $evidence = Join-Path $PSScriptRoot 'docs/evidence'
    New-Item -ItemType Directory -Force -Path $evidence | Out-Null
    @{result='PASS';probe='payments-pilot';source_files=$files.Count;fresh_project=$testProject;
      inherited_secrets=$false;host_settings_required=$false;boot_command='docker compose -f compose.migration-base.yml -f compose.payments.yml up';fresh_volumes=$true;original_stack_restored=$true;recorded_at=[DateTime]::UtcNow.ToString('o')} |
      ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $evidence 'payments-pilot-latest.json')
    Write-Host 'PASS: Payments pilot passed with isolated data; original Notifications stack restored.' -ForegroundColor Green
}
