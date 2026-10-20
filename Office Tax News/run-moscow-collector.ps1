$ErrorActionPreference = 'Stop'

# Сбор должен начаться за час до московского редакционного слота. Парные
# локальные триггеры покрывают CET/CEST, а этот шлюз не даёт второму триггеру
# запустить лишний сбор.
$moscowZone = [TimeZoneInfo]::FindSystemTimeZoneById('Russian Standard Time')
$moscowNow = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, $moscowZone)
$collectionHours = @(8, 12, 16)
if (($collectionHours -notcontains $moscowNow.Hour) -or $moscowNow.Minute -gt 10) {
    exit 0
}

& (Join-Path $PSScriptRoot 'run-collector.ps1')
exit $LASTEXITCODE
