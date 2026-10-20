$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Auto Publisher'
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runnerScript = Join-Path $PSScriptRoot 'run-moscow-publisher.ps1'

Write-Host "Registering Windows Task Scheduler Task for 09:00, 13:00, 17:00 Moscow time..."

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`""

# Amsterdam is UTC+1 in winter and UTC+2 in summer, Moscow is UTC+3 all
# year. Two local triggers per Moscow slot cover both DST offsets; the runner
# performs the final Moscow-time gate, so an extra trigger never sends a post.
$trigger1 = New-ScheduledTaskTrigger -Daily -At '07:00'
$trigger2 = New-ScheduledTaskTrigger -Daily -At '08:00'
$trigger3 = New-ScheduledTaskTrigger -Daily -At '11:00'
$trigger4 = New-ScheduledTaskTrigger -Daily -At '12:00'
$trigger5 = New-ScheduledTaskTrigger -Daily -At '15:00'
$trigger6 = New-ScheduledTaskTrigger -Daily -At '16:00'

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
    -Trigger @($trigger1, $trigger2, $trigger3, $trigger4, $trigger5, $trigger6) `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Write-Host "Task '$taskName' registered successfully for Moscow editorial slots."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
