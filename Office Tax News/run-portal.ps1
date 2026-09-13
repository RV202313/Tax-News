$env:PYTHONUTF8 = '1'
& "$PSScriptRoot\.venv\Scripts\python.exe" -u "$PSScriptRoot\News Claude\portal\server.py" *> "$PSScriptRoot\portal-runtime.log"
exit $LASTEXITCODE
