function Convert-DockerMemoryBytes([string]$Text) {
    $match = [regex]::Match($Text.Trim(), '^(\d+(?:\.\d+)?)\s*(B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)$')
    if (-not $match.Success) { throw "Unknown Docker memory format: $Text" }
    $units = @{B=1;kB=1000;KiB=1024;MB=1000000;MiB=1048576;GB=1000000000;GiB=1073741824;TB=1000000000000;TiB=1099511627776}
    $number = [double]::Parse($match.Groups[1].Value,[Globalization.CultureInfo]::InvariantCulture)
    [long]($number * $units[$match.Groups[2].Value])
}

function Start-NotificationsMemorySampler {
    param([string]$DockerExe,[string]$ProjectName,[string]$StopFile,[string]$OutputFile,
          [string]$DiagnosticFile,[string]$SamplerScript,[string]$StdoutFile,[string]$StderrFile)
    $hostExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$SamplerScript,
        '-DockerExe',$DockerExe,'-ProjectName',$ProjectName,'-StopFile',$StopFile,
        '-OutputFile',$OutputFile,'-DiagnosticFile',$DiagnosticFile)
    # Arguments are fixed switches or Windows filenames; filenames cannot contain
    # a double quote. Quote each separately so paths containing spaces survive.
    $quoted = @($arguments | ForEach-Object { if ($_ -match '"') { throw 'Invalid sampler argument' }; '"' + $_ + '"' })
    $process = Start-Process -FilePath $hostExe -ArgumentList ($quoted -join ' ') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $StdoutFile -RedirectStandardError $StderrFile
    # Keep a process handle open so Windows PowerShell 5.1 retains ExitCode
    # even when the child finishes before the next status check.
    $null = $process.Handle
    return $process
}
