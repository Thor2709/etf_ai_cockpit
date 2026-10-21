"""Bughunt E (#987): supply-chain and release gates must fail closed."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import check_supply_chain_intake, release_gate, supply_chain_scan
from etf_cockpit.core import secure_update
from etf_cockpit.core.secure_update import describe_release_evidence

ROOT = Path(__file__).resolve().parents[1]


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["pip-audit"], returncode=returncode, stdout=stdout, stderr="")


def _audit_rows(*rows: tuple[str, str, list[dict[str, Any]]]) -> str:
    return json.dumps({"dependencies": [{"name": n, "version": v, "vulns": vulns} for n, v, vulns in rows]})


def _two_locks(tmp_path: Path) -> dict[str, object]:
    (tmp_path / "requirements-release.txt").write_text("alpha==1.0\n", encoding="utf-8")
    (tmp_path / "requirements-release-parsers.txt").write_text("parserlib==2.0\n", encoding="utf-8")
    return {
        "dependency_lock": "requirements-release.txt",
        "parser_dependency_lock": "requirements-release-parsers.txt",
        "approved_mitigations": [],
    }


# --- E022-N001 / E120-N001: the parser lock is scanned --------------------------------------------------------

def test_shipped_supply_chain_policy_scans_the_same_locks_as_the_release_policy() -> None:
    supply = yaml.safe_load((ROOT / "configs/supply_chain_policy.yaml").read_text(encoding="utf-8"))
    release = yaml.safe_load((ROOT / "configs/release_policy.yaml").read_text(encoding="utf-8"))

    assert supply_chain_scan.policy_locks(release) == ["requirements-release.txt", "requirements-release-parsers.txt"]
    assert supply_chain_scan.policy_locks(supply) == supply_chain_scan.policy_locks(release)


def test_policy_that_omits_a_release_lock_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/supply_chain_policy.yaml").write_text("dependency_lock: requirements-release.txt\n", encoding="utf-8")
    (tmp_path / "configs/release_policy.yaml").write_text(
        "dependency_lock: requirements-release.txt\nparser_dependency_lock: requirements-release-parsers.txt\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="requirements-release-parsers.txt"):
        supply_chain_scan._policy(tmp_path)


def test_parser_only_cve_fails_the_scan(monkeypatch, tmp_path: Path) -> None:
    policy = _two_locks(tmp_path)
    calls: list[str] = []

    def fake_run(command, **_kwargs):
        lock = command[command.index("-r") + 1]
        calls.append(lock)
        if lock == "requirements-release-parsers.txt":
            return _completed(_audit_rows(("parserlib", "2.0", [{"id": "CVE-PARSER-1"}])), returncode=1)
        return _completed(_audit_rows(("alpha", "1.0", [])))

    monkeypatch.setattr(supply_chain_scan.subprocess, "run", fake_run)

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False)

    assert calls == ["requirements-release.txt", "requirements-release-parsers.txt"]
    assert result["status"] == "failed"
    assert [row["id"] for row in result["blocking_vulnerabilities"]] == ["CVE-PARSER-1"]


def test_licence_inventory_and_sbom_cover_both_locks(monkeypatch, tmp_path: Path) -> None:
    policy = _two_locks(tmp_path)
    monkeypatch.setattr(release_gate.importlib.metadata, "version", lambda name: {"alpha": "1.0", "parserlib": "2.0"}[name])
    monkeypatch.setattr(release_gate.importlib.metadata, "requires", lambda name: None)

    names = {row["name"] for row in supply_chain_scan.dependency_snapshot(tmp_path, policy)["required"]}
    source = {"manifest_sha256": "m"}
    sbom = release_gate.build_sbom(tmp_path, source, policy)

    assert names == {"alpha", "parserlib"}
    assert {c["name"] for c in sbom["components"]} >= {"alpha", "parserlib"}


# --- E022-N002: malformed / empty / non-covering pip-audit output ------------------------------------------------

@pytest.mark.parametrize(
    ("stdout", "reason"),
    [
        ("", "no output"),
        ("   \n", "no output"),
        ("this is not json", "not valid JSON"),
        ("{}", "no dependency list"),
        ('"clean"', "no dependency list"),
        ("[]", "lists no dependencies"),
        ('{"dependencies": []}', "lists no dependencies"),
        (_audit_rows(("other", "9.9", [])), "does not cover"),
        (_audit_rows(("alpha", "0.1", [])), "does not cover"),
    ],
)
def test_exit_zero_with_empty_or_invalid_audit_output_fails(monkeypatch, tmp_path: Path, stdout: str, reason: str) -> None:
    (tmp_path / "requirements-release.txt").write_text("alpha==1.0\n", encoding="utf-8")
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": []}
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *a, **k: _completed(stdout))

    result = supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False)

    assert result["status"] == "failed"
    assert any(reason in problem for problem in result["problems"])


# --- E022-N004: mitigations are scoped to package, version and expiry --------------------------------------------

_TODAY = supply_chain_scan.dt.date(2026, 10, 21)


def _scan_with(monkeypatch, tmp_path: Path, mitigations: list[object], rows: str) -> dict[str, object]:
    (tmp_path / "requirements-release.txt").write_text("alpha==1.0\nbeta==2.0\n", encoding="utf-8")
    policy = {"dependency_lock": "requirements-release.txt", "approved_mitigations": mitigations}
    monkeypatch.setattr(supply_chain_scan.subprocess, "run", lambda *a, **k: _completed(rows, returncode=1))
    return supply_chain_scan.vulnerability_scan(tmp_path, policy, allow_missing_tools=False, today=_TODAY)


_BOTH_VULNERABLE = _audit_rows(
    ("alpha", "1.0", [{"id": "CVE-X-1"}]),
    ("beta", "2.0", [{"id": "CVE-X-1"}]),
)


def test_cve_exemption_does_not_cover_another_package(monkeypatch, tmp_path: Path) -> None:
    mitigation = {"id": "CVE-X-1", "package": "alpha", "version": "1.0", "expires_on": "2026-12-31"}

    result = _scan_with(monkeypatch, tmp_path, [mitigation], _BOTH_VULNERABLE)

    assert result["status"] == "failed"
    assert [row["package"] for row in result["approved_mitigations"]] == ["alpha"]
    assert [row["package"] for row in result["blocking_vulnerabilities"]] == ["beta"]


def test_exemption_covering_every_finding_still_passes(monkeypatch, tmp_path: Path) -> None:
    mitigations = [
        {"id": "CVE-X-1", "package": "Alpha", "version": "1.0", "expires_on": "2026-12-31"},
        {"id": "CVE-X-1", "package": "beta", "version": "2.0", "expires_on": "2026-10-21"},
    ]

    result = _scan_with(monkeypatch, tmp_path, mitigations, _BOTH_VULNERABLE)

    assert result["status"] == "passed"
    assert result["blocking_vulnerabilities"] == []


@pytest.mark.parametrize(
    "mitigation",
    [
        "CVE-X-1",
        {"id": "CVE-X-1"},
        {"id": "CVE-X-1", "package": "alpha", "version": "1.0"},
        {"id": "CVE-X-1", "package": "alpha", "expires_on": "2026-12-31"},
        {"id": "CVE-X-1", "package": "alpha", "version": "0.9", "expires_on": "2026-12-31"},
        {"id": "CVE-X-1", "package": "alpha", "version": "1.0", "expires_on": "2026-10-20"},
        {"id": "CVE-X-1", "package": "alpha", "version": "1.0", "expires_on": "never"},
    ],
)
def test_unscoped_wrong_version_or_expired_exemption_never_exempts(monkeypatch, tmp_path: Path, mitigation: object) -> None:
    rows = _audit_rows(("alpha", "1.0", [{"id": "CVE-X-1"}]), ("beta", "2.0", []))

    result = _scan_with(monkeypatch, tmp_path, [mitigation], rows)

    assert result["status"] == "failed"
    assert result["approved_mitigations"] == []
    assert [row["id"] for row in result["blocking_vulnerabilities"]] == ["CVE-X-1"]


# --- E022-N003: advisory intake exceptions are explicit; everything else blocks ----------------------------------

def _stub_report(monkeypatch, tmp_path: Path, policy: dict[str, object], intake_failures: list[str]) -> int:
    monkeypatch.setattr(supply_chain_scan, "_policy", lambda _root: policy)
    monkeypatch.setattr(supply_chain_scan, "build_source_manifest", lambda *a, **k: {"manifest_sha256": "m", "files": []})
    monkeypatch.setattr(supply_chain_scan, "build_sbom", lambda *a, **k: {"bom_sha256": "s"})
    monkeypatch.setattr(supply_chain_scan, "licence_inventory", lambda *a, **k: {"components": [], "missing_license_metadata": []})
    monkeypatch.setattr(supply_chain_scan, "secret_findings", lambda *a, **k: [])
    monkeypatch.setattr(supply_chain_scan, "vulnerability_scan", lambda *a, **k: {"status": "passed", "required": True})
    monkeypatch.setattr(
        supply_chain_scan,
        "supply_chain_intake_report",
        lambda _root: {"status": "failed", "review_status": "x", "signature_status": "missing", "failures": intake_failures},
    )
    _path, code = supply_chain_scan.write_report(tmp_path, tmp_path / "out")
    return code


ADVISORY = "supply-chain registry review status is not approved"


def test_listed_advisory_intake_failure_does_not_block_but_is_recorded(monkeypatch, tmp_path: Path) -> None:
    policy = {"advisory_intake_exceptions": [ADVISORY]}

    assert _stub_report(monkeypatch, tmp_path, policy, [ADVISORY]) == 0
    report = json.loads((tmp_path / "out" / "supply-chain-report.json").read_text(encoding="utf-8"))
    assert report["advisory_intake_failures"] == [ADVISORY]
    assert report["blocking_failures"] == []


def test_unlisted_intake_failure_exits_non_zero(monkeypatch, tmp_path: Path) -> None:
    assert _stub_report(monkeypatch, tmp_path, {}, [ADVISORY]) == 1
    assert _stub_report(monkeypatch, tmp_path, {"advisory_intake_exceptions": [ADVISORY]}, [ADVISORY, "declared copied files are missing: x"]) == 1


def test_advisory_exceptions_cannot_cover_arbitrary_failures(monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be advisory"):
        _stub_report(monkeypatch, tmp_path, {"advisory_intake_exceptions": ["declared copied files are missing: x"]}, [])


def test_shipped_policy_declares_the_advisory_exceptions_explicitly() -> None:
    policy = yaml.safe_load((ROOT / "configs/supply_chain_policy.yaml").read_text(encoding="utf-8"))

    assert set(policy["advisory_intake_exceptions"]) <= supply_chain_scan.KNOWN_ADVISORY_INTAKE_FAILURES


def test_intake_checker_exits_non_zero_when_intake_cannot_be_evaluated(tmp_path: Path) -> None:
    assert check_supply_chain_intake.main(["--root", str(tmp_path), "--report-dir", str(tmp_path / "report")]) == 1


# --- E020-N001: a missing mandatory check fails the gate ---------------------------------------------------------

def _state(*checks: release_gate.CheckResult) -> release_gate.GateState:
    state = release_gate.GateState()
    for check in checks:
        state.add(check)
    return state


def test_absent_mandatory_check_fails() -> None:
    state = _state(release_gate.CheckResult("sbom", "passed", True))

    release_gate._enforce_mandatory_checks(state, {"mandatory": ["sbom", "bulk_cache"]}, frozenset())

    assert any("bulk_cache: mandatory check is absent" in failure for failure in state.failures)


def test_optional_skipped_mandatory_check_fails_unless_explicitly_waived() -> None:
    skipped = release_gate.CheckResult("bulk_cache", "skipped", False)
    policy = {"mandatory": ["bulk_cache"]}

    strict = _state(skipped)
    release_gate._enforce_mandatory_checks(strict, policy, frozenset())
    waived = _state(skipped)
    release_gate._enforce_mandatory_checks(waived, policy, frozenset({"bulk_cache"}))

    assert strict.failures and "skipped, not passed" in strict.failures[0]
    assert waived.failures == []


def test_malformed_mandatory_policy_fails_closed() -> None:
    state = _state()

    release_gate._enforce_mandatory_checks(state, {"mandatory": "sbom"}, frozenset())

    assert state.failures


def test_every_shipped_mandatory_name_is_a_check_run_gate_can_produce() -> None:
    policy = yaml.safe_load((ROOT / "configs/release_policy.yaml").read_text(encoding="utf-8"))
    source = (ROOT / "scripts/release_gate.py").read_text(encoding="utf-8")

    for name in policy["mandatory"]:
        assert f'"{name}"' in source, name


def _gate_fixture(tmp_path: Path, monkeypatch, *, mandatory: str = "", head: str = "abc") -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "schema_version: '1.0'\npython_version: '3.12.10'\ndependency_lock: requirements-release.txt\n"
        f"artifact_roots: [build]\nsigning_key_env: TEST_RELEASE_KEY\n{mandatory}",
        encoding="utf-8",
    )
    locked = {"exchange-calendars": "4.13.2", "flet": "0.85.3", "hypothesis": "6.156.6", "mypy": "1.20.2", "pytest": "9.1.1", "ruff": "0.15.20"}
    (tmp_path / "requirements-release.txt").write_text("".join(f"{n}=={v}\n" for n, v in locked.items()), encoding="utf-8")
    monkeypatch.setenv("TEST_RELEASE_KEY", "a sufficiently long test signing key")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"branch": "t", "head": head, "origin_main": head, "dirty": False})

    def installed(name: str) -> str:
        try:
            return locked[name]
        except KeyError as exc:
            raise release_gate.importlib.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(release_gate.importlib.metadata, "version", installed)
    monkeypatch.setattr(release_gate.importlib.metadata, "requires", lambda name: None)


def test_missing_mandatory_check_fails_the_run_gate(tmp_path: Path, monkeypatch) -> None:
    _gate_fixture(tmp_path, monkeypatch, mandatory="mandatory: [sbom, signature, performance_budgets, no_such_check]\n")

    result = release_gate.run_gate(tmp_path, output_dir=tmp_path / "ev", skip_tests=True, skip_package=True, skip_smoke=True)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.exit_code == 1
    failure = next(item for item in manifest["failures"] if item.startswith("mandatory_checks"))
    assert "performance_budgets: mandatory check is skipped" in failure
    assert "no_such_check: mandatory check is absent" in failure


def test_diagnostic_skip_flags_are_recorded_as_waived_mandatory_checks(tmp_path: Path, monkeypatch) -> None:
    _gate_fixture(tmp_path, monkeypatch, mandatory="mandatory: [full_tests, package_build, package_smoke, sbom, signature]\n")

    result = release_gate.run_gate(tmp_path, output_dir=tmp_path / "ev", skip_tests=True, skip_package=True, skip_smoke=True)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert manifest["waived_mandatory_checks"] == ["full_tests", "package_build", "package_smoke"]


# --- E020-N003: a missing Git identity blocks signing -----------------------------------------------------------

def test_missing_git_identity_blocks_signing(tmp_path: Path, monkeypatch) -> None:
    _gate_fixture(tmp_path, monkeypatch, head="")

    result = release_gate.run_gate(tmp_path, output_dir=tmp_path / "ev", skip_tests=True, skip_package=True, skip_smoke=True)

    signature = json.loads((result.output_dir / "release-manifest.sig.json").read_text(encoding="utf-8"))
    assert result.exit_code == 1
    assert signature["status"] == "blocked" and "signature" not in signature
    assert any(check.name == "signature" and check.status == "failed" for check in result.checks)


# --- E020-N004: the SBOM includes transitive dependencies --------------------------------------------------------

def test_sbom_includes_a_transitive_dependency(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-release.txt").write_text("app-lib==1.0\n", encoding="utf-8")
    versions = {"app-lib": "1.0", "mid_lib": "2.0", "leaf-lib": "3.0", "Marker.Only": "9.9"}
    requires = {
        "app-lib": ["mid-lib>=2", "optional-thing; extra == 'speed'", "missing-lib; python_version < '3'"],
        "mid_lib": ["Leaf_Lib (>=3)"],
        "mid-lib": ["Leaf_Lib (>=3)"],
        "Leaf_Lib": [],
    }

    def version(name: str) -> str:
        key = {"mid-lib": "mid_lib", "Leaf_Lib": "leaf-lib"}.get(name, name)
        try:
            return versions[key]
        except KeyError as exc:
            raise release_gate.importlib.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(release_gate.importlib.metadata, "version", version)
    monkeypatch.setattr(release_gate.importlib.metadata, "requires", lambda name: requires.get(name))

    sbom = release_gate.build_sbom(tmp_path, {"manifest_sha256": "m"}, {"dependency_lock": "requirements-release.txt"})

    by_ref = {component["bom-ref"]: component for component in sbom["components"]}
    assert "pkg:pypi/mid-lib@2.0" in by_ref and "pkg:pypi/leaf-lib@3.0" in by_ref
    assert by_ref["pkg:pypi/leaf-lib@3.0"]["properties"] == [{"name": "release-lock", "value": "transitive"}]
    edges = {row["ref"]: row["dependsOn"] for row in sbom["dependencies"]}
    assert edges["pkg:pypi/app-lib@1.0"] == ["pkg:pypi/mid-lib@2.0"]
    assert edges["pkg:pypi/mid-lib@2.0"] == ["pkg:pypi/leaf-lib@3.0"]


# --- E020-N002: Windows-equivalent filenames in update ZIPs are rejected ------------------------------------------

def _zip_with(tmp_path: Path, *names: str) -> Path:
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in names:
            bundle.writestr(name, b"payload")
    return archive


@pytest.mark.parametrize(
    "names",
    [
        ("Readme.txt", "README.TXT"),
        ("dir/file.txt", "DIR/File.txt"),
        ("dir/file.txt", "dir/file.txt."),
        ("dir/file.txt", "dir/file.txt "),
        ("dir/file.txt:stream",),
        ("dir:evil/file.txt",),
        ("dir/CON.txt",),
        ("dir/nul",),
        ("dir/Com1",),
        ("dir./file.txt",),
    ],
)
def test_windows_equivalent_or_reserved_update_member_names_are_rejected(tmp_path: Path, names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        secure_update.build_update_manifest(_zip_with(tmp_path, *names))


def test_ordinary_update_member_names_are_still_accepted(tmp_path: Path) -> None:
    manifest = secure_update.build_update_manifest(_zip_with(tmp_path, "app/main.py", "app/Main2.py", "console.txt", "config/nullable.yaml"))

    assert [row["path"] for row in manifest["entries"]] == ["app/Main2.py", "app/main.py", "config/nullable.yaml", "console.txt"]


# --- E120-N002: unexpected files in the package are a parity gap -------------------------------------------------

def _parity_pair(tmp_path: Path) -> tuple[Path, release_gate.PreparedPackage]:
    source = tmp_path / "src"
    (source / "src" / "etf_cockpit").mkdir(parents=True)
    (source / "src" / "etf_cockpit" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (source / "configs").mkdir()
    (source / "configs" / "c.yaml").write_text("c: 1\n", encoding="utf-8")
    package = tmp_path / "pkg"
    import shutil

    shutil.copytree(source / "src", package / "src")
    shutil.copytree(source / "configs", package / "configs")
    return source, release_gate.PreparedPackage(package, "sdist", None)


def test_unexpected_package_file_fails_parity(tmp_path: Path) -> None:
    source, prepared = _parity_pair(tmp_path)
    assert release_gate.source_package_parity(source, prepared).status == "passed"

    (prepared.root / "src" / "etf_cockpit" / "injected.py").write_text("import os\n", encoding="utf-8")
    result = release_gate.source_package_parity(source, prepared)

    assert result.status == "failed"
    assert "unexpected packaged file: src/etf_cockpit/injected.py" in result.failure


def test_generated_build_byproducts_are_not_parity_gaps(tmp_path: Path) -> None:
    source, prepared = _parity_pair(tmp_path)
    egg = prepared.root / "src" / "etf_cockpit.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_text("Name: x\n", encoding="utf-8")
    cache = prepared.root / "src" / "etf_cockpit" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_bytes(b"\x00")

    assert release_gate.source_package_parity(source, prepared).status == "passed"


# --- E120-N003: Settings must show the true release status --------------------------------------------------------

def _release_dir(root: Path, manifest: dict[str, Any], signature: dict[str, Any] | None) -> None:
    directory = root / "artifacts" / "release" / "latest"
    directory.mkdir(parents=True)
    (directory / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if signature is not None:
        (directory / "release-manifest.sig.json").write_text(json.dumps(signature), encoding="utf-8")


def test_settings_release_status_is_not_signed_when_the_manifest_has_failures(tmp_path: Path) -> None:
    _release_dir(tmp_path, {"project_version": "1.0", "failures": ["full_tests: failed"]}, {"status": "signed"})

    verification = describe_release_evidence(tmp_path)["verification"]

    assert verification.startswith("failed") and "1 gate failure" in verification
    assert verification != "signed"


def test_settings_release_status_does_not_claim_an_unverified_signature(tmp_path: Path) -> None:
    _release_dir(tmp_path, {"project_version": "1.0", "failures": []}, {"status": "signed"})

    verification = describe_release_evidence(tmp_path)["verification"]

    assert verification.startswith("signature present, not verified")


def test_settings_release_status_without_failures_list_is_unavailable_not_clean(tmp_path: Path) -> None:
    _release_dir(tmp_path, {"project_version": "1.0"}, {"status": "signed"})

    assert describe_release_evidence(tmp_path)["verification"].startswith("invalid local release evidence")


def test_settings_release_status_for_unsigned_evidence(tmp_path: Path) -> None:
    _release_dir(tmp_path, {"project_version": "1.0", "failures": []}, None)

    assert describe_release_evidence(tmp_path)["verification"] == "unsigned"


# --- E120-N004: tracked-file scanning is complete -------------------------------------------------------------

_SECRET = 'api_key = "' + "A1b2C3d4" * 3 + '"\n'


def test_secret_scan_covers_every_tracked_text_file_including_excluded_build_dirs(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for relative in ("tools/run.sh", "docs/notes.md", "Makefile", "deploy/build/settings.py", ".env.local", "conf/app.cfg"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_SECRET, encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00" + _SECRET.encode())
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    source = release_gate.build_source_manifest(tmp_path)
    flagged = {row["path"] for row in supply_chain_scan.secret_findings(tmp_path, source)}

    assert flagged == {"tools/run.sh", "docs/notes.md", "Makefile", "deploy/build/settings.py", ".env.local", "conf/app.cfg"}


# --- E122-N002 / E122-N003: build backend pins and manifest parity ------------------------------------------

def test_build_backend_requirements_are_exactly_pinned() -> None:
    requires = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["build-system"]["requires"]

    assert requires and all("==" in item and not any(op in item for op in (">", "<", "~", "*")) for item in requires), requires


def _requirement_lines(path: Path) -> set[str]:
    lines = (line.split("#", 1)[0].strip().lower().replace(" ", "") for line in path.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line}


def test_source_dependency_manifest_matches_project_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    metadata = {item.lower().replace(" ", "") for item in project["dependencies"]}
    parsers = {item.lower().replace(" ", "") for item in project["optional-dependencies"]["parsers"]}

    assert _requirement_lines(ROOT / "requirements.txt") == metadata
    assert _requirement_lines(ROOT / "requirements-parsers.txt") == parsers
