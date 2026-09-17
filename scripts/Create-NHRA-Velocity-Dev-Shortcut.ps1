param(
  [string]$Base = "$env:LOCALAPPDATA\NHRA Velocity Dev",
  [string]$ShortcutPath = ""
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
  $desktop = [Environment]::GetFolderPath('Desktop')
  if ([string]::IsNullOrWhiteSpace($desktop)) {
    $desktop = (New-Object -ComObject WScript.Shell).SpecialFolders('Desktop')
  }
  $ShortcutPath = Join-Path $desktop 'NHRA Velocity Dev.lnk'
}

$launcher = Join-Path $Base 'Launch-NHRA-Velocity-Dev.vbs'
$icon = Join-Path $Base 'NHRA-Velocity.ico'
if (-not (Test-Path $launcher)) { throw "Velocity launcher not found: $launcher" }

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($ShortcutPath)
$s.TargetPath = "$env:SystemRoot\System32\wscript.exe"
$s.Arguments = '"' + $launcher + '"'
$s.WorkingDirectory = $Base
$s.Description = 'NHRA Velocity development build - hidden auto-update launcher'
if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
$s.Save()
Write-Host "Desktop shortcut created: $ShortcutPath"
