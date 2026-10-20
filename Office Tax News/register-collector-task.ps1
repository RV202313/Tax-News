$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Website collection'
$launcher = Join-Path $PSScriptRoot 'silent_collector.vbs'

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Collector launcher not found: $launcher"
}

$action = New-ScheduledTaskAction `
    -Execute 'wscript.exe' `
    -Argument "`"$launcher`""
# Московские слоты сбора 08/12/16; парные локальные триггеры покрывают CET/CEST,
# а run-moscow-collector.ps1 отсекает лишний запуск.
$triggers = @(
    foreach ($hour in 6, 7, 10, 11, 14, 15) {
        New-ScheduledTaskTrigger -Daily -At ('{0:00}:00' -f $hour)
    }
)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -User $env:USERNAME `
    -Force | Out-Null

Write-Host "Registered '$taskName' for 08:00, 12:00, and 16:00 MSK with bounded retries."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
