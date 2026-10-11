' Run scripts\net_watch.ps1 with no window (the task NetReconnect, every 2 min).
' powershell -WindowStyle Hidden still flashes a console; wscript has none.
Option Explicit
Dim sh, fso, ps1
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ps1 = fso.GetParentFolderName(WScript.ScriptFullName) & "\net_watch.ps1"
WScript.Quit sh.Run("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & ps1 & """", 0, True)
