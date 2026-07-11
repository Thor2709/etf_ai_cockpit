[CmdletBinding()]
param(
    [string]$EvidenceRoot = (Join-Path (Get-Location) "evidence\clean-environment"),
    [string]$SourceRoot = (Get-Location),
    [switch]$InstallRequirements,
    [string]$RequirementsPath = "requirements.txt",
    [string]$VenvPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# The explicit commands represented below are ``python -m venv`` and
# ``python -m pip check``.  The script resolves ``python`` once and then uses
# the created venv interpreter for every subsequent stage.

function Get-StringHash {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-FileDigest {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Redact-Text {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) {
        return ""
    }
    $redacted = [regex]::Replace(
        $Value,
        "(?i)\b(api[_-]?key|authorization|password|secret|token)\b\s*([:=])\s*([^\s,;]+)",
        '$1$2[REDACTED]'
    )
    return [regex]::Replace($redacted, "(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]")
}

function Get-SourceDigest {
    param([Parameter(Mandatory = $true)][string]$Root)

    $excluded = @(".git", ".venv", ".verification-venv", "__pycache__", ".pytest_cache", "build", "dist", "logs")
    $rows = New-Object System.Collections.Generic.List[string]
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object {
        $relative = $_.FullName.Substring($Root.Length).TrimStart("\", "/")
        $parts = $relative -split "[\\/]"
        @($parts | Where-Object { $excluded -contains $_ }).Count -eq 0 -and
        (($parts[0] -in @("src", "scripts", "configs")) -or ($relative -match "^(pyproject\.toml|requirements[^\\/]*\.txt|README_FIRST_RUN\.md)$"))
    }
    foreach ($file in ($files | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($Root.Length).TrimStart("\", "/").Replace("\", "/")
        $rows.Add("$relative=$(Get-FileDigest -Path $file.FullName)")
    }
    return Get-StringHash -Value ($rows -join "`n")
}

function Get-EnvironmentDigest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$PythonPath
    )

    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add("python=$PythonPath")
    try {
        $version = & $PythonPath --version 2>&1 | Out-String
        $rows.Add("version=$(Redact-Text $version).Trim()")
    }
    catch {
        $rows.Add("version=unavailable")
    }
    foreach ($file in (Get-ChildItem -LiteralPath $Root -File -Filter "requirements*.txt" | Sort-Object Name)) {
        $rows.Add("$($file.Name)=$(Get-FileDigest -Path $file.FullName)")
    }
    if (Test-Path -LiteralPath (Join-Path $Root "pyproject.toml") -PathType Leaf) {
        $rows.Add("pyproject.toml=$(Get-FileDigest -Path (Join-Path $Root 'pyproject.toml'))")
    }
    return Get-StringHash -Value ($rows -join "`n")
}

function New-Stage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Result,
        [int]$ExitCode = 0,
        [string]$Command = "",
        [string[]]$OutputPaths = @(),
        [string[]]$OutputChecksums = @(),
        [string]$SourceHash = "",
        [string]$EnvironmentHash = "",
        [string]$Limitation = ""
    )

    if ([string]::IsNullOrWhiteSpace($SourceHash)) {
        $SourceHash = [string]$script:sourceHash
    }
    if ([string]::IsNullOrWhiteSpace($EnvironmentHash)) {
        $EnvironmentHash = [string]$script:environmentHash
    }
    $normalisedResult = $Result.ToLowerInvariant()
    return [ordered]@{
        verification_run_id = "clean-$Name"
        verification_type = $Name
        command = $Command
        source_hash = $SourceHash
        environment_hash = $EnvironmentHash
        result = $normalisedResult
        exit_code = $ExitCode
        output_paths = @($OutputPaths)
        output_checksums = @($OutputChecksums)
        issue_ids = @("CLEAN-ENVIRONMENT")
        gates = @($Name)
        skipped = ($normalisedResult -eq "blocked" -and [string]::IsNullOrWhiteSpace($Command))
        informational = $false
        limitation = $Limitation
    }
}

function Invoke-LocalStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Evidence
    )

    $stageRoot = Join-Path $Evidence "stages"
    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    $safeName = ($Name -replace "[^A-Za-z0-9_.-]", "_")
    $stdoutFile = Join-Path $stageRoot "$safeName.stdout.txt"
    $stderrFile = Join-Path $stageRoot "$safeName.stderr.txt"
    $relativeStdout = (Resolve-Path -LiteralPath $stdoutFile -ErrorAction SilentlyContinue)
    if ($null -eq $relativeStdout) {
        New-Item -ItemType File -Force -Path $stdoutFile | Out-Null
    }
    if ($null -eq (Resolve-Path -LiteralPath $stderrFile -ErrorAction SilentlyContinue)) {
        New-Item -ItemType File -Force -Path $stderrFile | Out-Null
    }

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return New-Stage -Name $Name -Result "BLOCKED" -ExitCode 127 -Command (($Executable) + " " + ($Arguments -join " ")) -Limitation "required tool is unavailable: $Executable"
    }

    try {
        & $Executable @Arguments 1> $stdoutFile 2> $stderrFile
        $exitCode = $LASTEXITCODE
    }
    catch {
        [System.IO.File]::WriteAllText($stderrFile, (Redact-Text $_.Exception.ToString()), [System.Text.Encoding]::UTF8)
        $exitCode = 1
    }
    $stdout = Redact-Text (Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue)
    $stderr = Redact-Text (Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue)
    [System.IO.File]::WriteAllText($stdoutFile, $stdout, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($stderrFile, $stderr, [System.Text.Encoding]::UTF8)
    $relativeStdout = $stdoutFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    $relativeStderr = $stderrFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    $result = if ($exitCode -eq 0) { "pass" } else { "fail" }
    return New-Stage -Name $Name -Result $result -ExitCode $exitCode -Command (($Executable) + " " + ($Arguments -join " ")) -OutputPaths @($relativeStdout, $relativeStderr) -OutputChecksums @((Get-FileDigest $stdoutFile), (Get-FileDigest $stderrFile)) -Limitation $(if ($exitCode -eq 0) { "" } else { "command failed" })
}

function Invoke-PackageStage {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [switch]$PackageToolAvailable
    )

    $stageRoot = Join-Path $Evidence "stages"
    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    $stdoutFile = Join-Path $stageRoot "package.stdout.txt"
    $stderrFile = Join-Path $stageRoot "package.stderr.txt"
    $packagePathFile = Join-Path $Root "build\portable_outdir.txt"
    $command = "verify package launcher artefact from $packagePathFile"
    $result = "blocked"
    $exitCode = 127
    $stdout = ""
    $limitation = ""
    try {
        if (-not $PackageToolAvailable) {
            throw "package tool or script is unavailable"
        }
        if (-not (Test-Path -LiteralPath $packagePathFile -PathType Leaf)) {
            throw "package output marker is unavailable: $packagePathFile"
        }
        $packageValue = (Get-Content -LiteralPath $packagePathFile -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($packageValue)) {
            throw "package output marker is empty"
        }
        $packagePath = if ([System.IO.Path]::IsPathRooted($packageValue)) { $packageValue } else { Join-Path $Root $packageValue }
        $rootResolved = [System.IO.Path]::GetFullPath($Root)
        $packageResolved = [System.IO.Path]::GetFullPath($packagePath)
        $rootPrefix = $rootResolved.TrimEnd("\") + "\"
        if ($packageResolved -ne $rootResolved -and -not $packageResolved.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "package output escapes source root"
        }
        if (-not (Test-Path -LiteralPath $packageResolved -PathType Container)) {
            throw "package output directory is unavailable: $packageResolved"
        }
        $launcher = Join-Path $packageResolved "ETF_AI_Cockpit.bat"
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf) -or (Get-Item -LiteralPath $launcher).Length -le 0) {
            throw "package launcher artefact is unavailable: $launcher"
        }
        $stdout = "package_root=$packageResolved`nlauncher=$launcher"
        $result = "pass"
        $exitCode = 0
    }
    catch {
        $limitation = "real package output/launcher artefact is unavailable: $($_.Exception.Message)"
    }
    [System.IO.File]::WriteAllText($stdoutFile, (Redact-Text $stdout), [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($stderrFile, (Redact-Text $limitation), [System.Text.Encoding]::UTF8)
    $relativeStdout = $stdoutFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    $relativeStderr = $stderrFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    return New-Stage -Name "package" -Result $result -ExitCode $exitCode -Command $command -OutputPaths @($relativeStdout, $relativeStderr) -OutputChecksums @((Get-FileDigest $stdoutFile), (Get-FileDigest $stderrFile)) -Limitation $limitation
}

function Invoke-BrowserStage {
    param(
        [Parameter(Mandatory = $true)][string]$Evidence
    )

    $stageRoot = Join-Path $Evidence "stages"
    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    $stdoutFile = Join-Path $stageRoot "browser.stdout.txt"
    $stderrFile = Join-Path $stageRoot "browser.stderr.txt"
    $chromeCommand = Get-Command chrome.exe -ErrorAction SilentlyContinue
    $chromePath = if ($null -ne $chromeCommand) { $chromeCommand.Source } else { "" }
    if ([string]::IsNullOrWhiteSpace($chromePath)) {
        $chromeCandidates = New-Object System.Collections.Generic.List[string]
        foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
            if (-not [string]::IsNullOrWhiteSpace($base)) {
                $chromeCandidates.Add((Join-Path $base "Google\Chrome\Application\chrome.exe"))
            }
        }
        foreach ($candidate in $chromeCandidates) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $chromePath = $candidate
                break
            }
        }
    }
    $command = "chrome.exe --headless=new --disable-gpu --dump-dom about:blank"
    if ([string]::IsNullOrWhiteSpace($chromePath)) {
        [System.IO.File]::WriteAllText($stdoutFile, "", [System.Text.Encoding]::UTF8)
        [System.IO.File]::WriteAllText($stderrFile, "required Chrome executable is unavailable", [System.Text.Encoding]::UTF8)
        $relativeStdout = $stdoutFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
        $relativeStderr = $stderrFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
        return New-Stage -Name "browser" -Result "blocked" -ExitCode 127 -Command $command -OutputPaths @($relativeStdout, $relativeStderr) -OutputChecksums @((Get-FileDigest $stdoutFile), (Get-FileDigest $stderrFile)) -Limitation "required Chrome executable is unavailable"
    }
    $profile = Join-Path $Evidence ".chrome-profile"
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    $arguments = @("--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=$profile", "--dump-dom", "about:blank")
    $exitCode = 1
    try {
        & $chromePath @arguments 1> $stdoutFile 2> $stderrFile
        $exitCode = $LASTEXITCODE
    }
    catch {
        [System.IO.File]::WriteAllText($stderrFile, (Redact-Text $_.Exception.ToString()), [System.Text.Encoding]::UTF8)
        $exitCode = 1
    }
    $stdout = Redact-Text (Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue)
    $stderr = Redact-Text (Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue)
    [System.IO.File]::WriteAllText($stdoutFile, $stdout, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($stderrFile, $stderr, [System.Text.Encoding]::UTF8)
    $result = if ($exitCode -eq 0 -and $stdout -match "<html") { "pass" } else { "fail" }
    $limitation = if ($result -eq "pass") { "" } elseif ($exitCode -eq 0) { "Chrome did not return HTML for the browser smoke stage" } else { "Chrome headless smoke command failed" }
    $relativeStdout = $stdoutFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    $relativeStderr = $stderrFile.Substring($Evidence.Length).TrimStart("\", "/").Replace("\", "/")
    return New-Stage -Name "browser" -Result $result -ExitCode $exitCode -Command $command -OutputPaths @($relativeStdout, $relativeStderr) -OutputChecksums @((Get-FileDigest $stdoutFile), (Get-FileDigest $stderrFile)) -Limitation $limitation
}

$resolvedSourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$resolvedEvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
New-Item -ItemType Directory -Force -Path $resolvedEvidenceRoot | Out-Null
$script:sourceHash = Get-SourceDigest -Root $resolvedSourceRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonPath = if ($null -eq $pythonCommand) { "unavailable" } else { $pythonCommand.Source }
$script:environmentHash = Get-EnvironmentDigest -Root $resolvedSourceRoot -PythonPath $pythonPath
$sourceHash = $script:sourceHash
$environmentHash = $script:environmentHash
$stages = New-Object System.Collections.Generic.List[object]
$limitations = New-Object System.Collections.Generic.List[string]

if ($null -eq $pythonCommand) {
    $stages.Add((New-Stage -Name "venv" -Result "BLOCKED" -ExitCode 127 -Limitation "Get-Command python did not find a local Python interpreter"))
    $limitations.Add("Python is unavailable; environment verification is BLOCKED.")
}
else {
    $verificationVenv = if ([string]::IsNullOrWhiteSpace($VenvPath)) { Join-Path $resolvedEvidenceRoot ".verification-venv" } else { [System.IO.Path]::GetFullPath($VenvPath) }
    $venvPython = Join-Path $verificationVenv "Scripts\python.exe"
    try {
        & $pythonCommand.Source -m venv $verificationVenv
        $venvExit = $LASTEXITCODE
    }
    catch {
        $venvExit = 1
    }
    if ($venvExit -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $stages.Add((New-Stage -Name "venv" -Result "BLOCKED" -ExitCode $venvExit -Command "$($pythonCommand.Source) -m venv $verificationVenv" -Limitation "explicit verification venv could not be created"))
        $limitations.Add("The explicit verification venv is unavailable; environment verification is BLOCKED.")
    }
    else {
        $stages.Add((New-Stage -Name "venv" -Result "pass" -ExitCode 0 -Command "$($pythonCommand.Source) -m venv $verificationVenv"))
        if ($InstallRequirements) {
            $requirementsFile = if ([System.IO.Path]::IsPathRooted($RequirementsPath)) { $RequirementsPath } else { Join-Path $resolvedSourceRoot $RequirementsPath }
            if (Test-Path -LiteralPath $requirementsFile -PathType Leaf) {
                $stages.Add((Invoke-LocalStage -Name "install" -Executable $venvPython -Arguments @("-m", "pip", "install", "-r", $requirementsFile) -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
            }
            else {
                $stages.Add((New-Stage -Name "install" -Result "BLOCKED" -ExitCode 127 -Limitation "declared requirements file is unavailable"))
                $limitations.Add("Declared requirements are unavailable; install verification is BLOCKED.")
            }
        }

        $stages.Add((Invoke-LocalStage -Name "pip_check" -Executable $venvPython -Arguments @("-m", "pip", "check") -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
        & $venvPython -c "import pytest" 1> $null 2> $null
        if ($LASTEXITCODE -eq 0) {
            $stages.Add((Invoke-LocalStage -Name "tests" -Executable $venvPython -Arguments @("-m", "pytest", "tests", "-q") -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
        }
        else {
            $stages.Add((New-Stage -Name "tests" -Result "BLOCKED" -ExitCode 127 -Limitation "pytest is not installed in the explicit verification venv"))
            $limitations.Add("pytest is unavailable; test verification is BLOCKED.")
        }

        $migrationTarget = Join-Path $resolvedSourceRoot "src\etf_cockpit\core\migrations.py"
        if (Test-Path -LiteralPath $migrationTarget -PathType Leaf) {
            $stages.Add((Invoke-LocalStage -Name "migrations" -Executable $venvPython -Arguments @("-m", "compileall", "-q", $migrationTarget) -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
        }
        else {
            $stages.Add((New-Stage -Name "migrations" -Result "BLOCKED" -ExitCode 127 -Limitation "migration tool is unavailable"))
            $limitations.Add("Migration verification tool is unavailable; stage is BLOCKED.")
        }

        $buildScript = Join-Path $resolvedSourceRoot "scripts\build_windows.bat"
        $cmdCommand = Get-Command cmd.exe -ErrorAction SilentlyContinue
        if ($null -ne $cmdCommand -and (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
            $stages.Add((Invoke-LocalStage -Name "build" -Executable $cmdCommand.Source -Arguments @("/d", "/c", $buildScript) -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
            $stages.Add((Invoke-PackageStage -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot -PackageToolAvailable))
        }
        else {
            $stages.Add((New-Stage -Name "build" -Result "blocked" -ExitCode 127 -Limitation "build tool or script is unavailable"))
            $stages.Add((Invoke-PackageStage -Root $resolvedSourceRoot -Evidence $resolvedEvidenceRoot))
            $limitations.Add("Build/package tooling is unavailable; both stages are BLOCKED.")
        }
    }
}

$stages.Add((Invoke-BrowserStage -Evidence $resolvedEvidenceRoot))
$blocked = @($stages | Where-Object { $_.result -eq "blocked" }).Count -gt 0
$failed = @($stages | Where-Object { $_.result -eq "fail" }).Count -gt 0
$overall = if ($blocked) { "blocked" } elseif ($failed) { "fail" } else { "pass" }
$manifest = [ordered]@{
    schema_version = "1.0"
    verification_policy_version = "1.0"
    requirement_version = "2"
    issue_id = "CLEAN-ENVIRONMENT"
    source_hash = $sourceHash
    environment_hash = $environmentHash
    generated_at = [DateTime]::UtcNow.ToString("o")
    status = $overall
    runs = @($stages)
    limitations = @($limitations)
    tracker_mutated = $false
}
$manifestPath = Join-Path $resolvedEvidenceRoot "verification_manifest.json"
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Output "verification_manifest=$manifestPath status=$overall source_hash=$sourceHash environment_hash=$environmentHash"
if ($overall -eq "blocked") { exit 2 }
if ($overall -eq "fail") { exit 1 }
exit 0
