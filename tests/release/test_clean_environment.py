from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_clean_environment_script_fails_closed_and_records_required_stages() -> None:
    script = (ROOT / "scripts" / "verify_clean_environment.ps1").read_text(encoding="utf-8")

    assert "BLOCKED" in script
    assert "python -m venv" in script
    assert "pip check" in script
    assert "verification_manifest" in script
    assert "issues/open.md" not in script
    assert "issues/closed.md" not in script


def test_clean_environment_script_does_not_use_global_python_without_recording_it() -> None:
    script = (ROOT / "scripts" / "verify_clean_environment.ps1").read_text(encoding="utf-8")

    assert "Get-Command python" in script
    assert "environment_hash" in script
    assert "source_hash" in script
    assert "Set-StrictMode" in script


def test_clean_environment_package_stage_is_independent_and_checks_a_real_launcher() -> None:
    script = (ROOT / "scripts" / "verify_clean_environment.ps1").read_text(encoding="utf-8")

    assert "portable_outdir.txt" in script
    assert "ETF_AI_Cockpit.bat" in script
    assert "Invoke-PackageStage" in script
    assert "New-Stage -Name \"package\" -Result $stages[$stages.Count - 1].result" not in script


def test_clean_environment_has_an_independent_chrome_stage_and_fail_closed_artifact_checks() -> None:
    script = (ROOT / "scripts" / "verify_clean_environment.ps1").read_text(encoding="utf-8")

    assert "Invoke-BrowserStage" in script
    assert "chrome.exe" in script
    assert "headless" in script.lower()
    assert "required Chrome executable is unavailable" in script
    assert '$_.result -eq "blocked"' in script


def test_clean_environment_stages_record_lowercase_status_and_per_run_hashes() -> None:
    script = (ROOT / "scripts" / "verify_clean_environment.ps1").read_text(encoding="utf-8")

    assert '$normalisedResult = $Result.ToLowerInvariant()' in script
    assert "source_hash = $SourceHash" in script
    assert "environment_hash = $EnvironmentHash" in script
