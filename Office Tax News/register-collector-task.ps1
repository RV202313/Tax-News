$ErrorActionPreference = 'Stop'

$taskName = 'Academy BEPS - Website collection'
$runner = Join-Path $PSScriptRoot 'run-collector.ps1'

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Collector runner not found: $runner"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$triggers = @(
    New-ScheduledTaskTrigger -Daily -At '08:00'
    New-ScheduledTaskTrigger -Daily -At '12:00'
    New-ScheduledTaskTrigger -Daily -At '16:00'
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

Write-Host "Registered '$taskName' for 08:00, 12:00, and 16:00 with bounded retries."
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath
