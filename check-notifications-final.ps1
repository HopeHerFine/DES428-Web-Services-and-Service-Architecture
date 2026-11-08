param([switch]$CleanStart)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & .\start-notifications.ps1
    & .\migrate-notifications-history.ps1
    $replay = Get-Content -Raw 'docs/evidence/legacy-import-latest.json' | ConvertFrom-Json
    if ($replay.imported -ne 0) { throw 'Historical replay unexpectedly imported additional rows.' }
    & .\check-security.ps1
    & .\check-resilience.ps1
    & .\check-broker-recovery.ps1
    & .\check-observability.ps1
    if ($CleanStart) { & .\check-clean-start.ps1 }
    $proof = @{
        result='PASS';scope='Notifications runtime acceptance';
        history_replay_without_duplicates=$true;security=$true;http_faults=$true;
        broker_worker_recovery=$true;observability=$true;clean_source_start=[bool]$CleanStart;
        github_ci='pending remote run';recorded_at=[DateTime]::UtcNow.ToString('o')
    }
    $proof | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 'docs/evidence/notifications-final-latest.json'
    Write-Host 'PASS: Notifications runtime acceptance completed. GitHub CI remains a separate check.' -ForegroundColor Green
} finally { Pop-Location }
