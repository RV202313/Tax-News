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
    $newsDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($PSScriptRoot))
    if ($newsDrive.AvailableFreeSpace -lt 128MB) { throw 'Insufficient disk space for safe news collection (need 128 MB)' }
    $newsStamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
    $newsBackup = Join-Path $newsLogDir "state-$newsStamp.sqlite"
    $statePath = Join-Path $newsRoot 'state\news_state.sqlite'
    $backupWarning = $null
    if (Test-Path -LiteralPath $statePath) {
        try {
            Copy-Item -LiteralPath $statePath -Destination $newsBackup -ErrorAction Stop
        } catch {
            $backupWarning = "State backup failed; continuing collection: $_"
        }
    }
    $newsLog = Join-Path $newsLogDir "$newsStamp.log"
    Set-Location -LiteralPath $newsRoot
    & $newsPython -u 'scripts\daily_run.py' --root $newsRoot --no-telegram *> $newsLog
    $newsExit = $LASTEXITCODE
    if ($backupWarning) { Add-Content -LiteralPath $newsLog -Value $backupWarning -Encoding UTF8 }
    $manifestPath = Join-Path $newsRoot "pipeline\raw\$((Get-Date).ToString('yyyy-MM-dd'))\collection_manifest.json"
    $digestPath = Join-Path $newsRoot "pipeline\digest\$((Get-Date).ToString('yyyy-MM-dd'))_digest.md"
    $verified = $false
    $sourceCount = 0
    $sourcesOk = 0
    $sourcesFailed = 0
    $digestBytes = 0
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $sourceValues = @($manifest.sources.PSObject.Properties | ForEach-Object { $_.Value })
        $sourceCount = $sourceValues.Count
        $sourcesOk = @($sourceValues | Where-Object { $_.state -eq 'ok' }).Count
        $sourcesFailed = @($sourceValues | Where-Object { $_.state -in @('failed', 'missing') }).Count
        if (Test-Path -LiteralPath $digestPath) {
            $digestBytes = (Get-Item -LiteralPath $digestPath).Length
        }
        $verified = $manifest.date -eq (Get-Date).ToString('yyyy-MM-dd') -and
            $sourceCount -gt 0 -and $sourcesOk -gt 0 -and
            $digestBytes -gt 0 -and $sourcesFailed -eq 0
    } catch {
        Add-Content -LiteralPath $newsLog -Value "Run verification failed: $_" -Encoding UTF8
    }
    if ($newsExit -eq 0 -and -not $verified) { $newsExit = 1 }
    @{
        finished=(Get-Date -Format o); exit_code=$newsExit; log=$newsLog
        verified=$verified; source_count=$sourceCount; sources_ok=$sourcesOk
        sources_failed=$sourcesFailed; digest_bytes=$digestBytes
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $newsLogDir 'last-run.json') -Encoding UTF8
    exit $newsExit
} finally {
    if ($newsAcquired) { $newsMutex.ReleaseMutex() }
    $newsMutex.Dispose()
}
