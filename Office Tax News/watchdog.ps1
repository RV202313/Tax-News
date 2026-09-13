$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

# Watchdog не открывает Telegram и не читает редакционный чат: это запрещённый
# периодический polling. Он проверяет только локальные receipts и SLA.
$rootDir = $PSScriptRoot
$logDir = Join-Path $rootDir 'runtime-logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$watchdogLog = Join-Path $logDir 'watchdog.log'
$watchdogStatusFile = Join-Path $logDir 'watchdog-status.json'
$now = Get-Date

function Log-Message([string]$Message) {
    $entry = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] $Message"
    Write-Host $entry
    Add-Content -LiteralPath $watchdogLog -Value $entry -Encoding UTF8
}

function Add-Issue($Status, [string]$Message) {
    [void]$Status.issues.Add($Message)
    Log-Message "ISSUE: $Message"
}

Log-Message '=== Watchdog check started ==='
$status = @{
    timestamp = $now.ToString('o'); portal_healthy = $false; tasks_healthy = $true
    release_sla_healthy = $false; issues = [System.Collections.ArrayList]::new()
    warnings = [System.Collections.ArrayList]::new(); actions_taken = [System.Collections.ArrayList]::new()
}

# Local portal is useful for observation, but a listening TCP port alone is not a release success.
try {
    $tcp = [System.Net.Sockets.TcpClient]::new()
    $pending = $tcp.BeginConnect('127.0.0.1', 8765, $null, $null)
    if (-not $pending.AsyncWaitHandle.WaitOne(1500, $false) -or -not $tcp.Connected) { throw 'TCP timeout' }
    $tcp.Close(); $status.portal_healthy = $true
    Log-Message 'Portal check: OK'
} catch {
    if ($tcp) { $tcp.Close() }
    Add-Issue $status "Portal unavailable: $_"
    $portalScript = Join-Path $rootDir 'run-portal.ps1'
    if (Test-Path -LiteralPath $portalScript) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$portalScript`"" -WindowStyle Hidden
        [void]$status.actions_taken.Add('Requested portal restart')
    }
}

# A scheduled task must exist, be enabled, and report its own real exit code.
$requiredTasks = @('Academy BEPS - Website collection', 'Academy BEPS - Auto Publisher')
foreach ($taskName in $requiredTasks) {
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
        if ($task.State -eq 'Disabled') {
            Enable-ScheduledTask -TaskName $taskName | Out-Null
            [void]$status.actions_taken.Add("Enabled $taskName")
            Add-Issue $status "Task was disabled: $taskName"
        }
        if ($info.LastTaskResult -ne 0) {
            Add-Issue $status "Task last run failed: $taskName (code $($info.LastTaskResult))"
            $status.tasks_healthy = $false
        }
        Log-Message "Task check: $taskName; state=$($task.State); last_result=$($info.LastTaskResult)"
    } catch {
        Add-Issue $status "Task missing or unreadable: $taskName"
        $status.tasks_healthy = $false
    }
}

# The SLA verifier reads delivery sidecars and immutable run_records. It has no
# Telegram client, so it is safe to run every 15 minutes.
$pythonExe = Join-Path $rootDir '.venv\Scripts\python.exe'
$verifier = Join-Path $rootDir 'verify-release-sla.py'
if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath $verifier)) {
    Add-Issue $status 'SLA verifier or project Python is missing'
} else {
    $result = & $pythonExe -X utf8 $verifier 2>&1
    $verifyExit = $LASTEXITCODE
    $healthPath = Join-Path $logDir 'health-status.json'
    try {
        $health = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $status.release_sla_healthy = [bool]$health.healthy
        foreach ($issue in @($health.critical)) { Add-Issue $status "SLA: $issue" }
        foreach ($warning in @($health.warnings)) {
            [void]$status.warnings.Add($warning)
            Log-Message "WARNING: $warning"
        }
    } catch {
        Add-Issue $status "Cannot read SLA status (exit $verifyExit): $result"
    }
}

$status.healthy = ($status.issues.Count -eq 0)
try { $status | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $watchdogStatusFile -Encoding UTF8 } catch { Log-Message "Cannot write watchdog status: $_" }
Log-Message "=== Watchdog check completed: healthy=$($status.healthy) ==="
if ($status.healthy) { exit 0 }
exit 1
