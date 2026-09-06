[CmdletBinding()]
param(
    [switch]$ApplyWorktreeOverrides,
    [switch]$PruneMissingWorktrees
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$liveConfig = Join-Path $codexRoot "config.toml"
$liveAgents = Join-Path $codexRoot "agents"
$canonicalPolicy = Join-Path $repoRoot "AGENTS.md"
$overrideMarker = "<!-- generated-by: docs/codex-config/enforce-agent-routing.ps1 -->"

$expected = [ordered]@{
    benchmark_guard          = @("gpt-5.6-luna", "high")
    diagnostician            = @("gpt-6-astra", "medium")
    documentation_maintainer = @("gpt-5.6-luna", "high")
    documentation_researcher = @("gpt-5.6-luna", "high")
    implementer              = @("gpt-6-astra", "low")
    performance_refactorer   = @("gpt-6-astra", "low")
    planner                  = @("gpt-5.6-sol", "medium")
    release_verifier         = @("gpt-5.6-sol", "medium")
    reviewer                 = @("gpt-6-astra", "low")
    risk_reviewer            = @("gpt-6-astra", "medium")
    scout                    = @("gpt-5.6-luna", "high")
    test_engineer            = @("gpt-5.6-sol", "medium")
}

function Get-TomlString([string]$text, [string]$key) {
    $pattern = '(?m)^\s*' + [regex]::Escape($key) + '\s*=\s*["'']([^"'']+)["'']\s*$'
    $match = [regex]::Match($text, $pattern)
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

$problems = [System.Collections.Generic.List[string]]::new()
$configText = Get-Content -LiteralPath $liveConfig -Raw

if ((Get-TomlString $configText "model") -ne "gpt-6-astra") { $problems.Add("Root model is not gpt-6-astra.") }
if ((Get-TomlString $configText "model_reasoning_effort") -ne "low") { $problems.Add("Root reasoning is not low.") }
if ((Get-TomlString $configText "plan_mode_reasoning_effort") -ne "medium") { $problems.Add("Plan reasoning is not medium.") }
if ($configText -notmatch "(?m)^\s*multi_agent_v2\s*=\s*true\s*$") { $problems.Add("multi_agent_v2 is not enabled.") }
if ($configText -notmatch "(?m)^\s*max_concurrent_threads_per_session\s*=\s*2\s*$") { $problems.Add("Routine child concurrency is not capped at 2.") }

foreach ($role in $expected.Keys) {
    $path = Join-Path $liveAgents ($role + ".toml")
    if (-not (Test-Path -LiteralPath $path)) {
        $problems.Add("Missing live role: $role")
        continue
    }
    $text = Get-Content -LiteralPath $path -Raw
    $actualModel = Get-TomlString $text "model"
    $actualEffort = Get-TomlString $text "model_reasoning_effort"
    if ($actualModel -ne $expected[$role][0] -or $actualEffort -ne $expected[$role][1]) {
        $problems.Add("Role $role is $actualModel/$actualEffort; expected $($expected[$role][0])/$($expected[$role][1]).")
    }
}

$worktreeLines = & git -C $repoRoot worktree list --porcelain
$worktrees = @($worktreeLines | Where-Object { $_ -like "worktree *" } | ForEach-Object { $_.Substring(9) })
$existing = @($worktrees | Where-Object { Test-Path -LiteralPath $_ })
$missing = @($worktrees | Where-Object { -not (Test-Path -LiteralPath $_) })
$canonicalBytes = [System.IO.File]::ReadAllBytes($canonicalPolicy)
$canonicalHash = (Get-FileHash -LiteralPath $canonicalPolicy -Algorithm SHA256).Hash
$overridden = 0
$current = 0

if ($ApplyWorktreeOverrides) {
    $excludePath = & git -C $repoRoot rev-parse --git-path info/exclude
    $excludeText = if (Test-Path -LiteralPath $excludePath) { Get-Content -LiteralPath $excludePath -Raw } else { "" }
    if ($excludeText -notmatch "(?m)^AGENTS\.override\.md$") {
        [System.IO.File]::AppendAllText($excludePath, "`r`nAGENTS.override.md`r`n")
    }
}

foreach ($worktree in $existing) {
    $policy = Join-Path $worktree "AGENTS.md"
    $override = Join-Path $worktree "AGENTS.override.md"
    $matches = (Test-Path -LiteralPath $policy) -and ((Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash -eq $canonicalHash)

    if ($matches) {
        $current++
        if ($ApplyWorktreeOverrides -and (Test-Path -LiteralPath $override)) {
            $firstLine = Get-Content -LiteralPath $override -TotalCount 1
            if ($firstLine -eq $overrideMarker) { Remove-Item -LiteralPath $override -Force }
        }
        continue
    }

    $overridden++
    if ($ApplyWorktreeOverrides) {
        $header = [System.Text.Encoding]::UTF8.GetBytes($overrideMarker + "`n<!-- canonical-sha256: $canonicalHash -->`n")
        $bytes = [byte[]]::new($header.Length + $canonicalBytes.Length)
        [Array]::Copy($header, 0, $bytes, 0, $header.Length)
        [Array]::Copy($canonicalBytes, 0, $bytes, $header.Length, $canonicalBytes.Length)
        [System.IO.File]::WriteAllBytes($override, $bytes)
    }
}

if ($PruneMissingWorktrees -and $missing.Count -gt 0) {
    & git -C $repoRoot worktree prune --verbose
    if ($LASTEXITCODE -ne 0) { throw "git worktree prune failed with exit code $LASTEXITCODE" }
}

[pscustomobject]@{
    RoutingProblems = $problems.Count
    RegisteredWorktrees = $worktrees.Count
    ExistingWorktrees = $existing.Count
    MissingWorktrees = $missing.Count
    WorktreesAlreadyCanonical = $current
    WorktreesNeedingOrUsingOverride = $overridden
    OverridesApplied = [bool]$ApplyWorktreeOverrides
    MissingMetadataPruned = [bool]$PruneMissingWorktrees
} | Format-List

if ($problems.Count -gt 0) {
    $problems | ForEach-Object { Write-Error $_ }
    exit 1
}
