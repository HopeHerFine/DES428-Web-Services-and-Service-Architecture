function Get-NotificationsCleanSourceFiles {
    param([Parameter(Mandatory=$true)][string]$Root)
    $separator = [IO.Path]::DirectorySeparatorChar
    $base = [IO.Path]::GetFullPath($Root).TrimEnd($separator)
    $prefix = $base + $separator
    $manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $base '.clean-source.json') | ConvertFrom-Json
    $excludedDirectories = @('.git','node_modules','.next','.next-check','.pytest_cache','__pycache__','.venv','venv','__MACOSX','runtime','coverage')
    $excludedFiles = @('*.db','*.db-wal','*.db-shm','*.db-journal','*.sqlite','*.sqlite3','*.log','*.pyc','*.pyo','*.pfx','*.p12','*.key','*.pem','*.jks','.DS_Store','npm-debug.log')
    $found = New-Object 'System.Collections.Generic.List[string]'
    function Add-CleanSourceItem([string]$Path) {
        $absolute = [IO.Path]::GetFullPath($Path)
        if (-not $absolute.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Clean-source path escaped source root.' }
        if (-not (Test-Path -LiteralPath $absolute)) { return }
        $item = Get-Item -Force -LiteralPath $absolute
        $relative = $absolute.Substring($prefix.Length).Replace('\','/')
        if ($relative -eq 'docs/evidence' -or $relative.StartsWith('docs/evidence/')) { return }
        if ($item.PSIsContainer) {
            if ($excludedDirectories -contains $item.Name) { return }
        } else {
            if ($item.Name -like '.env*' -and $item.Name -ne '.env.example') { return }
            foreach ($pattern in $excludedFiles) { if ($item.Name -like $pattern) { return } }
        }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Clean-source export refuses links: $relative" }
        if ($item.PSIsContainer) {
            foreach ($child in Get-ChildItem -Force -LiteralPath $absolute) { Add-CleanSourceItem $child.FullName }
        } else { $found.Add($relative) }
    }
    foreach ($relative in @($manifest.files) + @($manifest.directories)) { Add-CleanSourceItem (Join-Path $base $relative) }
    foreach ($required in $manifest.required) {
        if (-not $found.Contains($required)) { throw "Required clean-source file missing: $required" }
    }
    $found | Sort-Object -Unique
}
