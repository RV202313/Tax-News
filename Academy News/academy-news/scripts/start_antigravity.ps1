# Проверяем, запущен ли процесс Antigravity
$process = Get-Process -Name "Antigravity" -ErrorAction SilentlyContinue

if (-not $process) {
    $AppPath = "C:\Users\vakhi\AppData\Local\Programs\antigravity\Antigravity.exe"
    if (Test-Path $AppPath) {
        Start-Process -FilePath $AppPath
        Write-Output "Antigravity desktop app started successfully."
    } else {
        Write-Error "Antigravity.exe not found at $AppPath"
    }
} else {
    Write-Output "Antigravity desktop app is already running."
}
