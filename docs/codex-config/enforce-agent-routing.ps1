[CmdletBinding()]
param(
    [switch]$ApplyWorktreeOverrides,
    [string[]]$OwnedWorktree = @(),
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$arguments = @((Join-Path $PSScriptRoot "agent_routing.py"))
if ($ApplyWorktreeOverrides) { $arguments += "--apply" }
foreach ($worktree in $OwnedWorktree) {
    $arguments += @("--owned-worktree", $worktree)
}
& $PythonExecutable @arguments
if ($LASTEXITCODE -ne 0) { throw "Routing audit failed with exit code $LASTEXITCODE" }
