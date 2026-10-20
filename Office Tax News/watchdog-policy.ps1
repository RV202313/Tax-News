function Get-NewsRecoveryDecision {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][DateTimeOffset]$MoscowNow,
        [Parameter(Mandatory)][DateTimeOffset]$LastRun,
        [Parameter(Mandatory)][int]$LastResult,
        [Parameter(Mandatory)][string]$TaskState,
        [bool]$Completed = $false
    )

    $hours = if ($TaskName -eq 'Academy BEPS - Website collection') {
        @(8, 12, 16)
    } elseif ($TaskName -eq 'Academy BEPS - Auto Publisher') {
        @(9, 13, 17)
    } else {
        return [pscustomobject]@{ Retry = $false; Reason = 'unknown task' }
    }
    if (($hours -notcontains $MoscowNow.Hour) -or $MoscowNow.Minute -gt 10) {
        return [pscustomobject]@{ Retry = $false; Reason = 'outside Moscow recovery window' }
    }
    if ($TaskState -ne 'Ready') {
        return [pscustomobject]@{ Retry = $false; Reason = "task state $TaskState" }
    }
    if ($Completed) {
        return [pscustomobject]@{ Retry = $false; Reason = 'current slot already completed' }
    }
    $due = [DateTimeOffset]::new(
        $MoscowNow.Year, $MoscowNow.Month, $MoscowNow.Day,
        $MoscowNow.Hour, 0, 0, [TimeSpan]::FromHours(3)
    )
    if ($LastRun -lt $due) {
        return [pscustomobject]@{ Retry = $true; Reason = 'scheduled launch missing' }
    }
    if ($LastResult -ne 0) {
        return [pscustomobject]@{ Retry = $true; Reason = "process failed with code $LastResult" }
    }
    return [pscustomobject]@{ Retry = $false; Reason = 'current slot launched successfully' }
}
