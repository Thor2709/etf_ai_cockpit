"""V8 research items routed to #987 (supply chain / release gate), reproduced natively."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from etf_cockpit.core import secure_update
from etf_cockpit.governance import release_certification, supply_chain_intake
from etf_cockpit.governance.static_checks import run_static_execution_boundary_check
from scripts import check_focused_junit, release_gate, select_focused_tests

ROOT = Path(__file__).resolve().parents[1]
KEY = b"a sufficiently long test signing key"


# --- E.C4.S21.N001: focused tests verify collection parity and JUnit execution -------------------------------

def _junit(path: Path, cases: list[tuple[str, str, str]]) -> Path:
    body = "".join(
        f'<testcase classname="{classname}" name="{name}">' + ("<failure message='x'/>" if outcome == "failed" else "<skipped message='no'/>" if outcome == "skipped" else "") + "</testcase>"
        for classname, name, outcome in cases
    )
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>', encoding="utf-8")
    return path


def _collected(path: Path, *nodeids: str) -> Path:
    path.write_text("\n".join(nodeids) + "\n\n2 tests collected\n", encoding="utf-8")
    return path


def test_focused_junit_must_cover_every_collected_test(tmp_path: Path) -> None:
    collected = _collected(tmp_path / "collected.txt", "tests/test_a.py::test_one", "tests/test_a.py::test_two")
    junit = _junit(tmp_path / "junit.xml", [("tests.test_a", "test_one", "passed")])

    problems = check_focused_junit.problems([junit], collected)

    assert any("not executed" in problem for problem in problems)


def test_focused_junit_accepts_full_execution_and_rejects_foreign_or_missing_reports(tmp_path: Path) -> None:
    collected = _collected(tmp_path / "collected.txt", "tests/test_a.py::test_one")
    good = _junit(tmp_path / "good.xml", [("tests.test_a", "test_one", "passed")])
    foreign = _junit(tmp_path / "foreign.xml", [("tests.test_a", "test_one", "passed"), ("tests.test_b", "test_x", "passed")])

    assert check_focused_junit.problems([good], collected) == []
    assert any("not collected" in problem for problem in check_focused_junit.problems([foreign], collected))
    assert check_focused_junit.problems([tmp_path / "absent.xml"], collected)
    assert check_focused_junit.problems([], collected)
    assert check_focused_junit.problems([good], _collected(tmp_path / "empty.txt"))


def test_focused_junit_cli_exit_codes(tmp_path: Path) -> None:
    collected = _collected(tmp_path / "collected.txt", "tests/test_a.py::test_one")
    junit = _junit(tmp_path / "junit.xml", [("tests.test_a", "test_one", "skipped")])

    assert check_focused_junit.main(["--collected", str(collected), "--junit", str(junit)]) == 1
    junit = _junit(tmp_path / "junit.xml", [("tests.test_a", "test_one", "passed")])
    assert check_focused_junit.main(["--collected", str(collected), "--junit", str(junit)]) == 0


def test_focused_workflow_step_runs_the_junit_parity_check() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/release-gate.yml").read_text(encoding="utf-8"))["jobs"]
    run = next(step for step in jobs["focused-tests"]["steps"] if step["name"] == "Select and run focused tests")["run"]

    assert "--collect-only" in run
    assert "scripts/check_focused_junit.py" in run


# --- E.C4.S21.N002: transitive import impact -----------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def test_selector_picks_tests_that_import_a_changed_module_only_transitively(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    files = {
        "src/etf_cockpit/__init__.py": "",
        "src/etf_cockpit/core/__init__.py": "",
        "src/etf_cockpit/core/leaf.py": "X = 1\n",
        "src/etf_cockpit/core/mid.py": "from etf_cockpit.core.leaf import X\n",
        "src/etf_cockpit/core/rel.py": "from . import mid\n",
        "src/etf_cockpit/top.py": "from etf_cockpit.core import rel\n",
        "src/etf_cockpit/other.py": "Y = 1\n",
        "tests/test_top.py": "import etf_cockpit.top\n",
        "tests/test_unrelated.py": "import etf_cockpit.other\n",
    }
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src/etf_cockpit/core/leaf.py").write_text("X = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "change")

    selected = select_focused_tests.select_tests(tmp_path, select_focused_tests.changed_paths(tmp_path, base, _git(tmp_path, "rev-parse", "HEAD")))

    assert selected == ["tests/test_top.py"]


# --- E.C2.S20.N001 / E.C3.S20.N003: the signed registry digest binds status, key selector and copied bytes -------

def _registry_root(tmp_path: Path, *, review_status: str = "hardening_required", copied: bytes = b"copied\n") -> Path:
    source = yaml.safe_load((ROOT / "configs/supply_chain_intake.yaml").read_text(encoding="utf-8"))
    source["review_status"] = review_status
    source["components"] = [dict(source["components"][0], copied_files=["vendor_copy/lib.txt"])]
    source["policy"]["copied_code_requires_approved_record"] = False
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "configs/supply_chain_intake.yaml").write_text(yaml.safe_dump(source, sort_keys=True), encoding="utf-8")
    (tmp_path / "vendor_copy").mkdir(exist_ok=True)
    (tmp_path / "vendor_copy/lib.txt").write_bytes(copied)
    (tmp_path / "packaging").mkdir(exist_ok=True)
    (tmp_path / "packaging/THIRD_PARTY_NOTICES.md").write_text("notices\n", encoding="utf-8")
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    return tmp_path


def _digest(root: Path) -> str:
    return str(supply_chain_intake.supply_chain_intake_report(root)["registry_sha256"])


def test_registry_digest_changes_with_top_level_review_status(tmp_path: Path) -> None:
    pending = _digest(_registry_root(tmp_path))
    approved = _digest(_registry_root(tmp_path, review_status="approved"))

    assert pending != approved


def test_registry_digest_changes_with_signature_key_selector(tmp_path: Path) -> None:
    root = _registry_root(tmp_path)
    before = _digest(root)
    path = root / "configs/supply_chain_intake.yaml"
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry["signature"]["key_env"] = "ATTACKER_CHOSEN_KEY"
    path.write_text(yaml.safe_dump(registry, sort_keys=True), encoding="utf-8")

    assert _digest(root) != before


def test_registry_digest_binds_the_bytes_of_copied_files(tmp_path: Path) -> None:
    original = _digest(_registry_root(tmp_path, copied=b"copied\n"))
    tampered = _digest(_registry_root(tmp_path, copied=b"tampered\n"))

    assert original != tampered


def test_a_signature_made_before_review_status_was_flipped_no_longer_verifies(tmp_path: Path, monkeypatch) -> None:
    root = _registry_root(tmp_path)
    monkeypatch.setenv("ETF_COCKPIT_RELEASE_SIGNING_KEY", KEY.decode())
    signature = supply_chain_intake.sign_supply_chain_registry(_digest(root), KEY, key_id="k")
    destination = root / "artifacts/supply_chain_intake/latest/supply-chain-intake.sig.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(signature), encoding="utf-8")
    assert supply_chain_intake.supply_chain_intake_report(root)["signature_status"] == "signed"

    _registry_root(tmp_path, review_status="approved")

    assert supply_chain_intake.supply_chain_intake_report(root)["signature_status"] == "invalid"


# --- E.C2.S20.N002: staging never deletes a pre-existing path ---------------------------------------------------

def _signed_update(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("app/main.py", b"print('ok')\n")
    manifest = secure_update.build_update_manifest(archive)
    return archive, manifest, secure_update.sign_update_manifest(manifest, KEY, key_id="k")


def test_extraction_does_not_delete_a_pre_existing_fixed_name_directory(tmp_path: Path) -> None:
    archive, manifest, signature = _signed_update(tmp_path)
    target = tmp_path / "install"
    precious = tmp_path / ".install.staging"
    precious.mkdir()
    (precious / "keep.txt").write_text("user data", encoding="utf-8")

    staged = secure_update.extract_verified_update(archive, manifest, signature, KEY, target)

    assert (precious / "keep.txt").read_text(encoding="utf-8") == "user data"
    assert staged != precious and (staged / "app/main.py").is_file()


# --- E.C2.S24.N001: script files are inspected ------------------------------------------------------------------

@pytest.mark.parametrize("name", ["tools/run.sh", "tools/run.ps1", "tools/run.bat", "tools/run.cmd"])
def test_static_scan_inspects_script_contents(tmp_path: Path, name: str) -> None:
    script = tmp_path / name
    script.parent.mkdir(parents=True)
    script.write_text("echo start\nplace_order --symbol SPY\n", encoding="utf-8")

    report = run_static_execution_boundary_check(tmp_path)

    assert report.result == "fail"
    assert any(violation.path == name for violation in report.violations)


def test_static_scan_accepts_a_benign_script(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo hello\n", encoding="utf-8")

    assert run_static_execution_boundary_check(tmp_path).result == "pass"


# --- E.C4.S20.N001: the signed-manifest subcheck looks at the manifest's own checks ------------------------------

def _release_evidence(root: Path, manifest: dict[str, Any]) -> None:
    directory = root / "artifacts/release/issue-0152"
    directory.mkdir(parents=True)
    payload = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (directory / "release-manifest.json").write_bytes(payload)
    signature = release_gate.sign_manifest(payload, KEY, key_id="k")
    signature["status"] = "signed"
    (directory / "release-manifest.sig.json").write_text(json.dumps(signature), encoding="utf-8")


@pytest.mark.parametrize(
    "extra",
    [
        {"failures": ["full_tests: failed"]},
        {"checks": [{"name": "full_tests", "status": "failed", "required": True}]},
        {"checks": [{"name": "sbom", "status": "skipped", "required": True}]},
        {},
    ],
)
def test_signed_manifest_with_failed_or_unrecorded_checks_blocks(tmp_path: Path, monkeypatch, extra: dict[str, Any]) -> None:
    monkeypatch.setenv("ETF_COCKPIT_RELEASE_SIGNING_KEY", KEY.decode())
    _release_evidence(tmp_path, {"git": {"head": "abc"}, **extra})

    status, evidence = release_certification._signed_manifest_status(tmp_path, "abc")

    assert status == "blocked", evidence


def test_signed_manifest_with_all_checks_passed_is_accepted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETF_COCKPIT_RELEASE_SIGNING_KEY", KEY.decode())
    _release_evidence(
        tmp_path,
        {"git": {"head": "abc"}, "failures": [], "checks": [{"name": "sbom", "status": "passed", "required": True}]},
    )

    assert release_certification._signed_manifest_status(tmp_path, "abc")[0] == "passed"


# --- E.C5.S20.N001: the package artifact is chosen by build identity, not by sort order ---------------------------

def _tar(path: Path) -> None:
    import tarfile

    with tarfile.open(path, "w:gz"):
        pass


def test_artifact_selection_uses_build_identity_and_rejects_ambiguity(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "etf-ai-cockpit"\nversion = "1.1.0b1"\n', encoding="utf-8")
    build = tmp_path / "build"
    build.mkdir()
    for name in ("etf_ai_cockpit-1.1.0b1.tar.gz", "etf_ai_cockpit-9.9.9.tar.gz", "zzz-other-1.1.0b1.tar.gz"):
        _tar(build / name)

    chosen = release_gate._select_archive(tmp_path, release_gate._artifact_paths(tmp_path, {"artifact_roots": ["build"]}))
    assert chosen is not None and chosen.name == "etf_ai_cockpit-1.1.0b1.tar.gz"

    _tar(build / "sub_dir_copy.tar.gz")
    (build / "again").mkdir()
    _tar(build / "again" / "etf_ai_cockpit-1.1.0b1.tar.gz")
    with pytest.raises(ValueError, match="ambiguous"):
        release_gate._select_archive(tmp_path, release_gate._artifact_paths(tmp_path, {"artifact_roots": ["build"]}))


def test_artifact_selection_fails_when_no_artifact_matches_the_build(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "etf-ai-cockpit"\nversion = "1.1.0b1"\n', encoding="utf-8")
    (tmp_path / "build").mkdir()
    _tar(tmp_path / "build" / "etf_ai_cockpit-0.0.1.tar.gz")

    with pytest.raises(ValueError, match="build identity"):
        release_gate._select_archive(tmp_path, release_gate._artifact_paths(tmp_path, {"artifact_roots": ["build"]}))


# --- E.C5.S20.N002 / E.C5.S20.N003: manifest policy fields and signature metadata -------------------------------

def test_update_with_wrong_schema_or_online_policy_is_rejected(tmp_path: Path) -> None:
    archive, manifest, _signature = _signed_update(tmp_path)
    for field, value in (("offline_only", False), ("schema_version", "9.9"), ("offline_only", None)):
        altered = dict(manifest, **{field: value})
        altered["manifest_sha256"] = secure_update._manifest_digest(altered)
        resigned = secure_update.sign_update_manifest(altered, KEY, key_id="k")

        verification = secure_update.verify_update_bundle(archive, altered, resigned, KEY)

        assert not verification.ok, (field, value)
        assert any(field in error for error in verification.errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [("algorithm", "HMAC-SHA1"), ("algorithm", None), ("key_id", ""), ("key_id", None), ("schema_version", "0.1")],
)
def test_detached_signature_metadata_is_validated(field: str, value: object) -> None:
    payload = b'{"a":1}\n'
    signature = secure_update.sign_update_manifest({"a": 1}, KEY, key_id="k")
    assert secure_update.detached_signature_errors(payload, signature, KEY) == []
    signature[field] = value

    assert secure_update.detached_signature_errors(payload, signature, KEY)


def test_release_gate_signature_still_satisfies_the_detached_signature_check() -> None:
    payload = b"manifest"
    signature = release_gate.sign_manifest(payload, KEY, key_id="local-release-key")
    signature["status"] = "signed"

    assert secure_update.detached_signature_errors(payload, signature, KEY) == []
    assert hmac.compare_digest(str(signature["payload_sha256"]), hashlib.sha256(payload).hexdigest())


# --- E.C5.S22.N001: the sdist carries every file the Windows builder copies ---------------------------------------

def test_manifest_in_includes_every_file_build_windows_requires() -> None:
    builder = (ROOT / "scripts/build_windows.bat").read_text(encoding="utf-8")
    loop = re.search(r"for %%f in \(([^)]*)\) do", builder)
    assert loop is not None
    required = {item for item in loop.group(1).split() if not item.startswith("%")}
    required |= {
        match.group(1)
        for match in re.finditer(r'set "LAUNCHER_REQ(?:_PARSERS)?=([^"]+)"', builder)
    }
    manifest_in = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    included = {line.split(maxsplit=1)[1].strip() for line in manifest_in.splitlines() if line.startswith("include ")}

    assert required <= included, sorted(required - included)
