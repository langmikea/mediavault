@echo off
REM Launch the MediaVault watchdog in a hidden Windows PowerShell window.
REM Double-click to start. To stop: open Task Manager, find "Windows
REM PowerShell" (powershell.exe), right-click, End task.
REM
REM Uses powershell.exe (PS 5.1, always on PATH from Explorer) rather than
REM pwsh.exe (PS 7, not always resolvable from the double-click context).
REM The watchdog script is compatible with both.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0v06_watchdog.ps1"
