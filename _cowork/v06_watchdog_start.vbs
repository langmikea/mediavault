' v06_watchdog_start.vbs — truly silent watchdog launcher.
'
' Use this instead of v06_watchdog_start.cmd when you don't want to see
' even a brief console-window flash on double-click. Both do the same job.
'
' To stop the watchdog: Task Manager -> find "Windows PowerShell"
' (powershell.exe) -> End task.

Set fso = CreateObject("Scripting.FileSystemObject")
folder  = fso.GetParentFolderName(WScript.ScriptFullName)
ps1     = folder & "\v06_watchdog.ps1"

Set sh = CreateObject("WScript.Shell")
' Window style 0 = hidden; bWaitOnReturn = False (don't block).
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """", 0, False
