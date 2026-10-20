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
        if ($info.LastRunTime -gt [datetime]'2000-01-01' -and
            $task.State -ne 'Running' -and $info.LastTaskResult -ne 0) {
            Add-Issue $status "Task last run failed: $taskName (code $($info.LastTaskResult))"
            $status.tasks_healthy = $false
        }
        Log-Message "Task check: $taskName; state=$($task.State); last_result=$($info.LastTaskResult)"
    } catch {
        Add-Issue $status "Task missing or unreadable: $taskName"
        $status.tasks_healthy = $false
    }
}

$collectorTaskName = 'Academy BEPS - Website collection'
$collectorRegistration = Join-Path $rootDir 'register-collector-task.ps1'
try {
    $collectorTask = Get-ScheduledTask -TaskName $collectorTaskName -ErrorAction Stop
} catch {
    if (Test-Path -LiteralPath $collectorRegistration) {
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $collectorRegistration *>> $watchdogLog
            if ($LASTEXITCODE -ne 0) { throw "Registration exited with code $LASTEXITCODE" }
            $collectorTask = Get-ScheduledTask -TaskName $collectorTaskName -ErrorAction Stop
            [void]$status.actions_taken.Add('Registered missing website collection task')
            Log-Message 'Recovered missing website collection task'
        } catch {
            Add-Issue $status "Cannot register website collection task: $_"
        }
    }
}

if ($collectorTask) {
    try {
        $collectorInfo = Get-ScheduledTaskInfo -TaskName $collectorTaskName -ErrorAction Stop
        $runPath = Join-Path $logDir 'last-run.json'
        $retryPath = Join-Path $logDir 'collector-retry.json'
        $lastRun = $null
        if (Test-Path -LiteralPath $runPath) {
            $lastRun = Get-Content -LiteralPath $runPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        $failedRun = ($lastRun -and [int]$lastRun.exit_code -ne 0) -or
            ($collectorInfo.LastRunTime -gt [datetime]'2000-01-01' -and
             $collectorInfo.LastTaskResult -ne 0)

        $dueSlots = @(8, 12, 16) | ForEach-Object { $now.Date.AddHours($_).AddMinutes(12) } |
            Where-Object { $now -ge $_ }
        $staleRun = $false
        if ($dueSlots.Count -gt 0 -and $collectorTask.State -ne 'Running') {
            $finishedAt = [datetime]::MinValue
            if ($lastRun -and $lastRun.finished) {
                try { $finishedAt = [datetime]::Parse($lastRun.finished).ToLocalTime() } catch {}
            }
            $staleRun = $finishedAt -lt $dueSlots[-1]
        }

        $retryState = $null
        if (Test-Path -LiteralPath $retryPath) {
            try { $retryState = Get-Content -LiteralPath $retryPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
        }
        $retrySlot = if ($dueSlots.Count -gt 0) { $dueSlots[-1].ToString('yyyy-MM-dd-HH') } else { $null }
        $retryCount = if ($retryState -and $retryState.slot -eq $retrySlot) {
            [int]$retryState.attempts
        } else { 0 }
        $retryIntervalElapsed = -not $retryState -or $retryState.slot -ne $retrySlot -or
            $now - [datetime]::Parse($retryState.started) -ge [TimeSpan]::FromMinutes(30)
        $retryAllowed = $retrySlot -and $retryCount -lt 3 -and $retryIntervalElapsed
        if ($collectorTask.State -ne 'Running' -and ($failedRun -or $staleRun) -and $retryAllowed) {
            Start-ScheduledTask -TaskName $collectorTaskName -ErrorAction Stop
            @{started=$now.ToString('o'); slot=$retrySlot; attempts=($retryCount + 1);
              reason=$(if ($failedRun) { 'failed' } else { 'stale' })} |
                ConvertTo-Json | Set-Content -LiteralPath $retryPath -Encoding UTF8
            [void]$status.actions_taken.Add('Restarted website collection after failure or missed run')
            Log-Message "Started recovery run $($retryCount + 1)/3 for collection slot $retrySlot"
        }
    } catch {
        Add-Issue $status "Cannot recover website collection task: $_"
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
