$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Watchdog'
$watchdogScript = Join-Path $PSScriptRoot 'watchdog.ps1'

Write-Host "Registering Windows Task Scheduler Task: $taskName..."

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Write-Host "Task '$taskName' registered successfully!"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
