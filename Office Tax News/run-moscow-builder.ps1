$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

$logDir = Join-Path $PSScriptRoot 'runtime-logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runnerLog = Join-Path $logDir 'auto-builder-runner.log'
function Write-RunnerLog([string]$Message) {
    Add-Content -LiteralPath $runnerLog -Value "[$((Get-Date).ToString('o'))] $Message" -Encoding UTF8
}

$moscowZone = [TimeZoneInfo]::FindSystemTimeZoneById('Russian Standard Time')
$moscowNow = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $moscowZone)

# The builder runs 15 minutes before publication (08:45, 12:45, 16:45 MSK)
Write-RunnerLog "Started Moscow slot builder $($moscowNow.ToString('yyyy-MM-dd HH:mm:ss zzz'))"

$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
$builderScript = Join-Path $PSScriptRoot 'auto_build_editorial.py'

& $pythonExe -X utf8 $builderScript
$exitCode = $LASTEXITCODE
Write-RunnerLog "Finished Moscow slot builder with exit code $exitCode"
exit $exitCode
