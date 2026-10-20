$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

$logDir = Join-Path $PSScriptRoot 'runtime-logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runnerLog = Join-Path $logDir 'auto-publisher-runner.log'
function Write-RunnerLog([string]$Message) {
    Add-Content -LiteralPath $runnerLog -Value "[$((Get-Date).ToString('o'))] $Message" -Encoding UTF8
}

# The scheduler uses Windows local time, while editorial promises are Moscow
# time. This is a final gate for the paired DST triggers in
# register-auto-publisher-task.ps1.
$moscowZone = [TimeZoneInfo]::FindSystemTimeZoneById('Russian Standard Time')
$moscowNow = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $moscowZone)
$validHours = @(9, 13, 17)

# A short grace window covers a late Task Scheduler wake-up. The publisher has
# a single-run lock and durable receipt check, so retries cannot duplicate a
# confirmed release.
if (($validHours -notcontains $moscowNow.Hour) -or $moscowNow.Minute -gt 10) {
    Write-RunnerLog "Skipped outside Moscow delivery window: $($moscowNow.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    exit 0
}

$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$autoPubScript = Join-Path $PSScriptRoot 'auto-publish-release.py'
Write-RunnerLog "Started Moscow slot $($moscowNow.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
# Keep the wait strictly inside the Scheduler's 15-minute execution limit.
# This avoids a terminated process being mistaken for a missing publisher run.
& $pythonExe -X utf8 $autoPubScript --scheduled --handoff-wait-seconds 480
$exitCode = $LASTEXITCODE
Write-RunnerLog "Finished Moscow slot $($moscowNow.ToString('HH:mm')) with exit code $exitCode"
exit $exitCode
