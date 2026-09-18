Option Explicit
Const ForAppending = 8

Dim shell, fso, base, source, pythonw, desktop, logPath, logFile
Dim command, rc, i

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\NHRA Velocity Dev"
source = base & "\source"
pythonw = source & "\.venv\Scripts\pythonw.exe"
desktop = source & "\desktop.py"
logPath = base & "\launcher.log"

If Not fso.FolderExists(base) Then
  fso.CreateFolder(base)
End If

Set logFile = fso.OpenTextFile(logPath, ForAppending, True)
logFile.WriteLine ""
logFile.WriteLine "============================================================"
logFile.WriteLine "[" & Now & "] NHRA Velocity direct launcher starting"
logFile.WriteLine "Source: " & source
logFile.Close

If Not fso.FileExists(pythonw) Then
  MsgBox "NHRA Velocity Python environment is missing:" & vbCrLf & pythonw, vbCritical, "NHRA Velocity"
  WScript.Quit 1
End If
If Not fso.FileExists(desktop) Then
  MsgBox "NHRA Velocity desktop application is missing:" & vbCrLf & desktop, vbCritical, "NHRA Velocity"
  WScript.Quit 1
End If

shell.CurrentDirectory = source
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & desktop & Chr(34)
For i = 0 To WScript.Arguments.Count - 1
  command = command & " " & Chr(34) & WScript.Arguments(i) & Chr(34)
Next

' IMPORTANT: launch pythonw.exe directly with a NORMAL show state. pythonw.exe has
' no console window, so this remains visually clean while allowing Qt to show its
' own top-level windows normally. Do not insert a hidden cmd.exe parent here:
' Windows can propagate the hidden startup state to the Qt process and make the
' application appear to do nothing even though it is running.
rc = shell.Run(command, 1, True)

Set logFile = fso.OpenTextFile(logPath, ForAppending, True)
logFile.WriteLine "[" & Now & "] NHRA Velocity exited with code " & rc
logFile.Close

If rc <> 0 Then
  MsgBox "NHRA Velocity exited unexpectedly (code " & rc & ")." & vbCrLf & _
         "Run the diagnostic launcher or review:" & vbCrLf & logPath, _
         vbCritical, "NHRA Velocity"
End If
WScript.Quit rc
