param(
    [string]$CodexCommand = "codex",
    [string]$OutputPath = (Join-Path $PSScriptRoot "models-v1.json"),
    [string]$MetadataPath = (Join-Path $PSScriptRoot "models-v1.metadata.json")
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("codex-model-v1-" + [guid]::NewGuid().ToString("N"))
$emptyHome = Join-Path $workDir "empty-home"
$sourcePath = Join-Path $workDir "bundled-models.json"
New-Item -ItemType Directory -Path $emptyHome -Force | Out-Null

$commandInfo = Get-Command $CodexCommand -ErrorAction Stop
$cliPath = $commandInfo.Source
$cliVersion = (& $cliPath --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $cliVersion) {
    throw "Unable to determine the Codex CLI version."
}

$hadCodexHome = Test-Path Env:CODEX_HOME
$previousCodexHome = $env:CODEX_HOME
try {
    $env:CODEX_HOME = $emptyHome
    $catalogueLines = & $cliPath debug models --bundled
    if ($LASTEXITCODE -ne 0) {
        throw "codex debug models --bundled failed."
    }
    $sourceText = ($catalogueLines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($sourcePath, $sourceText, $utf8NoBom)
    $sourceObject = $sourceText | ConvertFrom-Json -Depth 100
    if (-not $sourceObject.models -or @($sourceObject.models).Count -lt 1) {
        throw "Unexpected catalogue schema: a non-empty models array is required."
    }

    $requiredSlugs = @("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
    $sourceVersions = @{}
    foreach ($slug in $requiredSlugs) {
        $matches = @($sourceObject.models | Where-Object { $_.slug -eq $slug })
        if ($matches.Count -ne 1) {
            throw "Expected exactly one $slug entry; found $($matches.Count)."
        }
        $sourceVersions[$slug] = [string]$matches[0].multi_agent_version
    }
    if ($sourceVersions["gpt-5.6-luna"] -ne "v1") {
        throw "Luna must remain V1."
    }

    $patchedObject = $sourceText | ConvertFrom-Json -Depth 100
    $changes = @()
    foreach ($slug in @("gpt-5.6-sol", "gpt-5.6-terra")) {
        $entry = @($patchedObject.models | Where-Object { $_.slug -eq $slug })[0]
        $before = [string]$entry.multi_agent_version
        $entry.multi_agent_version = "v1"
        if ($before -ne "v1") {
            $changes += [ordered]@{
                path = "models[slug=$slug].multi_agent_version"
                before = $before
                after = "v1"
            }
        }
    }

    $revertedObject = ($patchedObject | ConvertTo-Json -Depth 100 -Compress) |
        ConvertFrom-Json -Depth 100
    foreach ($slug in @("gpt-5.6-sol", "gpt-5.6-terra")) {
        $entry = @($revertedObject.models | Where-Object { $_.slug -eq $slug })[0]
        $entry.multi_agent_version = $sourceVersions[$slug]
    }
    if (($sourceObject | ConvertTo-Json -Depth 100 -Compress) -cne
        ($revertedObject | ConvertTo-Json -Depth 100 -Compress)) {
        throw "Unexpected catalogue mutation outside the two permitted fields."
    }

    $destination = [System.IO.Path]::GetFullPath($OutputPath)
    $metadataDestination = [System.IO.Path]::GetFullPath($MetadataPath)
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    New-Item -ItemType Directory -Path (Split-Path -Parent $metadataDestination) -Force | Out-Null

    $temporary = "$destination.tmp.$([guid]::NewGuid().ToString("N"))"
    [System.IO.File]::WriteAllText(
        $temporary,
        ($patchedObject | ConvertTo-Json -Depth 100) + "`n",
        $utf8NoBom
    )
    [System.IO.File]::Move($temporary, $destination, $true)

    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
    $patchedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    $metadata = [ordered]@{
        schema_version = 1
        purpose = "Sanitised provenance for regenerating the installed V1 model catalogue"
        source_codex_version = $cliVersion
        source_command = "codex debug models --bundled with an isolated empty CODEX_HOME"
        source_catalog_sha256 = $sourceHash
        patched_catalog_sha256 = $patchedHash
        required_models = $requiredSlugs
        allowed_patch = [ordered]@{
            "gpt-5.6-sol.multi_agent_version" = "v1"
            "gpt-5.6-terra.multi_agent_version" = "v1"
            "gpt-5.6-luna.multi_agent_version" = "v1"
        }
        changes = $changes
        runtime_paths_and_timestamps = "intentionally omitted"
    }
    $metadataTemporary = "$metadataDestination.tmp.$([guid]::NewGuid().ToString("N"))"
    [System.IO.File]::WriteAllText(
        $metadataTemporary,
        ($metadata | ConvertTo-Json -Depth 20) + "`n",
        $utf8NoBom
    )
    [System.IO.File]::Move($metadataTemporary, $metadataDestination, $true)

    Write-Output "Codex version: $cliVersion"
    Write-Output "Source SHA-256: $sourceHash"
    Write-Output "Output SHA-256: $patchedHash"
    Write-Output "Catalogue: $destination"
    Write-Output "Metadata: $metadataDestination"
}
finally {
    if ($hadCodexHome) {
        $env:CODEX_HOME = $previousCodexHome
    } else {
        Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force
    }
}
