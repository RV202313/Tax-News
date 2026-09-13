$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$newsRoot = Join-Path $PSScriptRoot 'News Claude'
$newsPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$newsLogDir = Join-Path $PSScriptRoot 'runtime-logs'
New-Item -ItemType Directory -Path $newsLogDir -Force | Out-Null
$newsMutex = [Threading.Mutex]::new($false, 'Local\AcademyBEPSNewsCollector')
$newsAcquired = $false
try {
    try { $newsAcquired = $newsMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $newsAcquired = $true }
    # Код 75 означает «временный конфликт», а не успех. Планировщик выполнит
    # настроенный retry и watchdog не примет старый last-run за новый сбор.
    if (-not $newsAcquired) { exit 75 }
    $newsStamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
    $newsBackup = Join-Path $newsLogDir "state-$newsStamp.sqlite"
    Copy-Item -LiteralPath (Join-Path $newsRoot 'state\news_state.sqlite') -Destination $newsBackup
    $newsLog = Join-Path $newsLogDir "$newsStamp.log"
    Set-Location -LiteralPath $newsRoot
    & $newsPython -u 'scripts\daily_run.py' --root $newsRoot --no-telegram *> $newsLog
    $newsExit = $LASTEXITCODE
    @{finished=(Get-Date -Format o); exit_code=$newsExit; log=$newsLog} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $newsLogDir 'last-run.json') -Encoding UTF8
    exit $newsExit
} finally {
    if ($newsAcquired) { $newsMutex.ReleaseMutex() }
    $newsMutex.Dispose()
}
