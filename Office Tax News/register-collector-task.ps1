$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Website collection'
$runnerScript = Join-Path $PSScriptRoot 'run-moscow-collector.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`""

# Moscow is UTC+3 without DST; Amsterdam is UTC+1/UTC+2. The runner makes the
# final Moscow-time decision, so the six local triggers are safe year-round.
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At '06:00'),
    (New-ScheduledTaskTrigger -Daily -At '07:00'),
    (New-ScheduledTaskTrigger -Daily -At '10:00'),
    (New-ScheduledTaskTrigger -Daily -At '11:00'),
    (New-ScheduledTaskTrigger -Daily -At '14:00'),
    (New-ScheduledTaskTrigger -Daily -At '15:00')
)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
