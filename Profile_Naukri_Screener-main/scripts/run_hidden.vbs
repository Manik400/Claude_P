' Run a batch file with nothing on the screen.
'
'   wscript.exe //B //Nologo scripts\run_hidden.vbs <batch file> [args...]
'
' This is what scripts\schedule_jobs_agent.ps1 registers as the Task Scheduler
' action. Pointing the task straight at a .bat opens a console window for the
' whole run; wscript has no console, and Run(..., 0, ...) starts the batch with
' its window hidden, so neither cmd nor Python ever appear.
'
' It also sets NAUKRI_BACKGROUND=1 for the batch and everything it starts,
' which makes main.py run its browser headless (naukri\session.py) - so no
' Chrome window either. Everything the batch would have printed goes to
' logs\scheduled.log instead, since there is no console to show it in.
'
' An argument written NAME=VALUE (upper-case name) is set as an environment
' variable for the batch instead of being passed to it. The scheduler uses
' this for NAUKRI_APPLY_LIMIT=5, the per-run application cap.
'
' To watch a run from a terminal instead, call the batch file directly.

Option Explicit

Dim sh, fso, root, batch, args, i, logFile, cmd, rc

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 1 Then
    WScript.Echo "Usage: wscript //B //Nologo run_hidden.vbs <batch file> [args...]"
    WScript.Quit 2
End If

root  = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
batch = fso.GetAbsolutePathName(WScript.Arguments(0))

If Not fso.FileExists(batch) Then
    WScript.Echo "Cannot find " & batch
    WScript.Quit 2
End If

args = ""
For i = 1 To WScript.Arguments.Count - 1
    If IsEnvAssignment(WScript.Arguments(i)) Then
        sh.Environment("PROCESS")(Split(WScript.Arguments(i), "=")(0)) = Mid(WScript.Arguments(i), InStr(WScript.Arguments(i), "=") + 1)
    Else
        args = args & " """ & WScript.Arguments(i) & """"
    End If
Next

If Not fso.FolderExists(root & "\logs") Then fso.CreateFolder root & "\logs"
logFile = root & "\logs\scheduled.log"

sh.Environment("PROCESS")("NAUKRI_BACKGROUND") = "1"
sh.CurrentDirectory = fso.GetParentFolderName(batch)

' cmd /S /C strips the outer pair of quotes and runs the rest verbatim.
cmd = "cmd.exe /S /C """ & _
      "echo. >> """ & logFile & """ && " & _
      "echo ===== %DATE% %TIME%  " & fso.GetFileName(batch) & " ===== >> """ & logFile & """ && " & _
      """" & batch & """" & args & " >> """ & logFile & """ 2>&1"""

' 0 = hidden window, True = wait for it to finish so the task shows the real
' exit code and Task Scheduler's own time limit still applies to the run.
rc = sh.Run(cmd, 0, True)
WScript.Quit rc

Function IsEnvAssignment(arg)
    Dim eq, name
    eq = InStr(arg, "=")
    IsEnvAssignment = False
    If eq > 1 Then
        name = Left(arg, eq - 1)
        If name = UCase(name) Then
            IsEnvAssignment = (InStr(name, " ") = 0 And InStr(name, "\") = 0 And InStr(name, ":") = 0)
        End If
    End If
End Function
