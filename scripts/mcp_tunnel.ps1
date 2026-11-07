[CmdletBinding()]
param(
    [switch]$Enabled,
    [ValidateRange(1, 120)]
    [int]$MaxDurationMinutes = 30,
    [string]$Command,
    [string[]]$ArgumentList = @()
)

$ErrorActionPreference = 'Stop'

if (-not $Enabled) {
    Write-Output 'MCP tunnel is disabled. Re-run with -Enabled to start a bounded tunnel process.'
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Command)) {
    throw 'Specify the tunnel executable with -Command.'
}

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $Command
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
foreach ($argument in $ArgumentList) {
    $startInfo.ArgumentList.Add($argument)
}

$tunnelProcess = [System.Diagnostics.Process]::Start($startInfo)
if ($null -eq $tunnelProcess) {
    throw 'The tunnel process could not be started.'
}

try {
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $tunnelProcess.HasExited -and $timer.Elapsed.TotalMinutes -lt $MaxDurationMinutes) {
        Start-Sleep -Seconds 1
        $tunnelProcess.Refresh()
    }
}
finally {
    $tunnelProcess.Refresh()
    if (-not $tunnelProcess.HasExited) {
        $tunnelProcess.Kill($true)
        [void]$tunnelProcess.WaitForExit(5000)
    }
    $tunnelProcess.Dispose()
}
