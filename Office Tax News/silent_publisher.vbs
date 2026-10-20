Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ""C:\Users\vakhi\Downloads\Tax News\Office Tax News\run-moscow-publisher.ps1""", 0, False
