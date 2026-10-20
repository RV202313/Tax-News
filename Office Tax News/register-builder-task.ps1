$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Auto Builder'
$vbsScript = Join-Path $PSScriptRoot 'silent_builder.vbs'

Write-Host "Registering Windows Task Scheduler Task for 08:45, 12:45, 16:45 Moscow time..."

$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$vbsScript`""

# Paired local triggers cover CET (UTC+1) and CEST (UTC+2) for Moscow (UTC+3)
$trigger1 = New-ScheduledTaskTrigger -Daily -At '06:45'
$trigger2 = New-ScheduledTaskTrigger -Daily -At '07:45'
$trigger3 = New-ScheduledTaskTrigger -Daily -At '10:45'
$trigger4 = New-ScheduledTaskTrigger -Daily -At '11:45'
$trigger5 = New-ScheduledTaskTrigger -Daily -At '14:45'
$trigger6 = New-ScheduledTaskTrigger -Daily -At '15:45'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 3) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($trigger1, $trigger2, $trigger3, $trigger4, $trigger5, $trigger6) `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Write-Host "Task '$taskName' registered successfully (100% silent execution, ZERO popups)."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
