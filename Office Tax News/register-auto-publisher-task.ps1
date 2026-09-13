$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Auto Publisher'
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$autoPubScript = Join-Path $PSScriptRoot 'auto-publish-release.py'

Write-Host "Registering Windows Task Scheduler Task: $taskName for 09:00, 13:00, 17:00..."

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "-X utf8 `"$autoPubScript`" --scheduled"

# Triggers for 09:00, 13:00, 17:00 daily
$trigger1 = New-ScheduledTaskTrigger -Daily -At '09:00'
$trigger2 = New-ScheduledTaskTrigger -Daily -At '13:00'
$trigger3 = New-ScheduledTaskTrigger -Daily -At '17:00'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($trigger1, $trigger2, $trigger3) `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Write-Host "Task '$taskName' registered successfully for 09:00, 13:00, 17:00!"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
