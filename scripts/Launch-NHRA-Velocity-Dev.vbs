Option Explicit
Dim shell, fso, base, cmd, quoted
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\NHRA Velocity Dev"
cmd = base & "\Launch-NHRA-Velocity-Dev.cmd"
If Not fso.FileExists(cmd) Then
  MsgBox "NHRA Velocity launcher is missing:" & vbCrLf & cmd, vbCritical, "NHRA Velocity"
  WScript.Quit 1
End If
quoted = "cmd.exe /d /s /c """ & cmd & """"
' Keep the hidden command process alive until Velocity exits.  The command
' process in turn waits on pythonw.exe, so Windows Terminal cannot orphan/kill
' the application during a short launcher handoff.
shell.Run quoted, 0, True
