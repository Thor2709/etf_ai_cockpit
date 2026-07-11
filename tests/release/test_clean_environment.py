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
