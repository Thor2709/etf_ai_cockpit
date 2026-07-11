param(
    [string]$ShortcutName = "ETF AI Evidence Cockpit"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Target = Join-Path $ProjectRoot "Launch_Latest_ETF_AI_Cockpit.bat"
$PortableExe = Join-Path $ProjectRoot "build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop ($ShortcutName + ".lnk")

if (-not (Test-Path -LiteralPath $Target)) {
    throw "Launcher not found: $Target"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Build and launch the latest local ETF AI Evidence Cockpit."
if (Test-Path -LiteralPath $PortableExe) {
    $Shortcut.IconLocation = "$PortableExe,0"
} else {
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
}
$Shortcut.Save()

Write-Output "Desktop shortcut created or updated: $ShortcutPath"
