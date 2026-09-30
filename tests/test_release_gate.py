from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import release_gate


def test_full_suite_timeout_is_scoped_to_the_full_release_test_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[int] = []

    def completed(*_args, **kwargs):
        observed.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(release_gate.subprocess, "run", completed)
    output = tmp_path / "evidence"
    output.mkdir()

    release_gate.run_command(tmp_path, output, "full_tests", ("pytest",))
    release_gate.run_command(tmp_path, output, "package_build", ("build",))

    assert observed == [3600, 1800]


def test_full_tests_default_command_remains_the_serial_release_command(tmp_path: Path) -> None:
    assert release_gate._full_test_commands(tmp_path, tmp_path / "evidence", 0) == (
        (
            release_gate.sys.executable,
            "-m",
            "pytest",
            "-q",
            "--durations=100",
            "--durations-min=0.25",
            f"--junitxml={tmp_path / 'evidence' / 'junit-full.xml'}",
        ),
    )


def test_full_tests_xdist_commands_use_disjoint_phases_and_canonical_junit_names(tmp_path: Path) -> None:
    phase_a, phase_b = release_gate._full_test_commands(tmp_path, tmp_path / "evidence", 4)

    marker_index = phase_a.index("-m", phase_a.index("-m") + 1)
    assert phase_a[marker_index + 1] == "not serial"
    assert phase_a[phase_a.index("-n") + 1] == "4"
    assert phase_a[phase_a.index("--dist") + 1] == "loadfile"
    assert f"--junitxml={tmp_path / 'evidence' / 'junit-parallel.xml'}" in phase_a
    assert "--durations=100" in phase_a
    assert "--durations-min=0.25" in phase_a
    marker_index = phase_b.index("-m", phase_b.index("-m") + 1)
    assert phase_b[marker_index + 1] == "serial"
    assert f"--junitxml={tmp_path / 'evidence' / 'junit-serial.xml'}" in phase_b
    assert "--durations=100" in phase_b
    assert "--durations-min=0.25" in phase_b


def test_merge_junit_reports_sums_counts_and_keeps_anchor_style_suite_counts(tmp_path: Path) -> None:
    parallel = tmp_path / "junit-parallel.xml"
    serial = tmp_path / "junit-serial.xml"
    parallel.write_text(
        '<testsuites><testsuite name="parallel" tests="2" failures="1" errors="0" skipped="1">'
        '<testcase name="failed"><failure message="assertion" /></testcase>'
        '<testcase name="skipped"><skipped /></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    serial.write_text(
        '<testsuite name="serial" tests="3" failures="0" errors="1" skipped="0">'
        '<testcase name="error"><error message="exception" /></testcase>'
        '<testcase name="passed-one" /><testcase name="passed-two" /></testsuite>',
        encoding="utf-8",
    )

    counts = release_gate._merge_junit_reports((parallel, serial), tmp_path / "junit-full.xml")

    merged = ET.parse(tmp_path / "junit-full.xml").getroot()
    suites = merged.findall("testsuite")
    assert merged.tag == "testsuites"
    assert len(merged.findall(".//testcase")) == 5
    assert counts == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}
    assert {name: int(merged.get(name, "0")) for name in counts} == counts
    assert sum(int(suite.get("tests", "0")) for suite in suites) == 5
    assert sum(int(suite.get("failures", "0")) + int(suite.get("errors", "0")) for suite in suites) == 2


@pytest.mark.parametrize("mismatch", ["missing", "overlap"])
def test_full_tests_fails_with_readable_collection_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    def collect(_root: Path, command: tuple[str, ...]) -> tuple[set[str], float, str]:
        if command.count("-m") < 2:
            return {"tests/test_sample.py::test_a", "tests/test_sample.py::test_b"}, 2.0, ""
        marker_index = command.index("-m", command.index("-m") + 1)
        if command[marker_index + 1] == "not serial":
            phase_a = {"tests/test_sample.py::test_a"}
            if mismatch == "overlap":
                phase_a.add("tests/test_sample.py::test_b")
            return phase_a, 1.0, ""
        if mismatch == "overlap":
            return {"tests/test_sample.py::test_b"}, 1.0, ""
        return set(), 1.0, ""

    def should_not_run(*_args, **_kwargs):
        pytest.fail("test execution must not start after a collection mismatch")

    monkeypatch.setattr(release_gate, "_collect_test_nodeids", collect)
    monkeypatch.setattr(release_gate, "run_command", should_not_run)

    result = release_gate.full_tests(tmp_path, tmp_path / "evidence", 4)

    assert result.status == "failed"
    assert "collection parity failed" in result.failure
    assert "tests/test_sample.py::test_b" in result.failure
    assert f"{mismatch}=1" in result.failure


@pytest.mark.parametrize("failed_phase", ["full_tests_parallel", "full_tests_serial"])
def test_full_tests_fails_when_either_xdist_phase_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_phase: str
) -> None:
    def collect(_root: Path, command: tuple[str, ...]) -> tuple[set[str], float, str]:
        if command.count("-m") < 2:
            return {"tests/test_sample.py::test_a", "tests/test_sample.py::test_b"}, 3.0, ""
        marker_index = command.index("-m", command.index("-m") + 1)
        if command[marker_index + 1] == "not serial":
            return {"tests/test_sample.py::test_a"}, 1.0, ""
        return {"tests/test_sample.py::test_b"}, 1.5, ""

    def run_phase(_root: Path, _output: Path, name: str, command: tuple[str, ...]) -> release_gate.CheckResult:
        junit_path = Path(next(value.split("=", 1)[1] for value in command if value.startswith("--junitxml=")))
        junit_path.write_text(
            '<testsuites><testsuite name="phase" tests="1" failures="0" errors="0" skipped="0">'
            '<testcase name="sample" /></testsuite></testsuites>',
            encoding="utf-8",
        )
        failed = name == failed_phase
        return release_gate.CheckResult(
            name,
            "failed" if failed else "passed",
            True,
            command="pytest",
            exit_code=1 if failed else 0,
            duration_ms=12.5,
            output="phase output",
            failure="exit code 1" if failed else "",
        )

    monkeypatch.setattr(release_gate, "_collect_test_nodeids", collect)
    monkeypatch.setattr(release_gate, "run_command", run_phase)

    result = release_gate.full_tests(tmp_path, tmp_path / "evidence", 4)

    expected_phase = "A" if failed_phase.endswith("parallel") else "B"
    assert result.status == "failed"
    assert f"phase {expected_phase} failed" in result.failure
    evidence = json.loads(result.output.removeprefix(release_gate._FULL_TEST_EVIDENCE_PREFIX))
    assert evidence["collection_node_counts"] == {"full": 2, "phase_a": 1, "phase_b": 1}
    assert evidence["phase_duration_ms"] == {"phase_a": 12.5, "phase_b": 12.5}
    report = release_gate._report_markdown(
        {"schema_version": "1.0", "git": {}, "source_manifest_sha256": "test"},
        release_gate.GateState(checks=[result]),
        {},
    )
    assert "Full test execution evidence" in report
    assert "phase_duration_ms" in report


def test_workflow_runs_xdist_auto_on_both_platforms_and_excludes_pull_request_pilot() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    pilot_condition = jobs["parallel-pilot"]["if"]
    assert "github.event_name != 'pull_request'" in pilot_condition

    gate_step = next(step for step in jobs["release-gate"]["steps"] if step["name"] == "Run protected release gate")
    assert re.search(r"arguments=\(--root \. --output \"\$output\" --allow-unsigned --xdist-workers auto\)", gate_step["run"])
    assert '== "linux"' not in gate_step["run"]
    assert gate_step["env"]["ETF_COCKPIT_XDIST_MAX"] == "4"
    # Three file-level shards per platform run in parallel; the gate does not wait for preflight,
    # but validation-summary still requires preflight and every shard.
    gate = jobs["release-gate"]
    assert gate["strategy"]["matrix"]["shard"] == [1, 2, 3]
    assert gate["strategy"]["matrix"]["platform"] == ["windows", "linux"]
    assert gate_step["env"]["ETF_COCKPIT_TEST_SHARD"] == "${{ matrix.shard }}/3"
    assert "preflight" not in gate["needs"]
    assert {"preflight", "release-gate"} <= set(jobs["validation-summary"]["needs"])


def test_main_reads_xdist_workers_from_environment_and_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    observed: list[int] = []

    def run_gate(root: Path, **kwargs) -> release_gate.GateResult:
        observed.append(kwargs["xdist_workers"])
        return release_gate.GateResult(0, root, root / "manifest.json", root / "report.md", ())

    monkeypatch.setattr(release_gate, "run_gate", run_gate)
    monkeypatch.setenv(release_gate.XDIST_WORKERS_ENV, "3")

    assert release_gate.main(["--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert release_gate.main(["--root", str(tmp_path), "--xdist-workers", "4"]) == 0
    capsys.readouterr()

    assert observed == [3, 4]


def test_auto_xdist_workers_use_usable_cpus_capped_and_serial_on_one_cpu(monkeypatch) -> None:
    monkeypatch.setattr(release_gate, "_usable_cpu_count", lambda: 20)
    monkeypatch.setenv(release_gate.XDIST_MAX_ENV, "14")
    assert release_gate._nonnegative_int("auto") == 14
    monkeypatch.delenv(release_gate.XDIST_MAX_ENV)
    assert release_gate._nonnegative_int("AUTO") == 16
    monkeypatch.setattr(release_gate, "_usable_cpu_count", lambda: 4)
    assert release_gate._nonnegative_int("auto") == 4
    monkeypatch.setattr(release_gate, "_usable_cpu_count", lambda: 1)
    assert release_gate._nonnegative_int("auto") == 0


def _junit_report(path: Path, cases: list[tuple[str, str]]) -> Path:
    body = "".join(f'<testcase classname="{classname}" name="{name}" />' for classname, name in cases)
    path.write_text(f'<testsuites><testsuite name="pytest">{body}</testsuite></testsuites>', encoding="utf-8")
    return path


def test_junit_execution_parity_requires_every_collected_test_exactly_once(tmp_path: Path) -> None:
    collected = {
        "tests/test_a.py::test_one[x-1]",
        "tests/ui/test_b.py::TestView::test_two",
        "tests/test_c.py::test_three",
    }
    parallel = _junit_report(tmp_path / "p.xml", [("tests.test_a", "test_one[x-1]"), ("tests.ui.test_b.TestView", "test_two")])
    serial = _junit_report(tmp_path / "s.xml", [("tests.test_c", "test_three")])
    assert release_gate._junit_execution_problems((parallel, serial), collected) == []

    backslash = _junit_report(tmp_path / "b.xml", [("tests.test_c", "test_three"), ("tests.test_e", r"test_zip[C:\x.xhtml]")])
    # Collection output is normalised backslash -> "/"; JUnit keeps the raw parameter id.
    assert release_gate._junit_execution_problems((parallel, backslash), collected | {"tests/test_e.py::test_zip[C:/x.xhtml]"}) == []
    teardown = tmp_path / "t.xml"
    teardown.write_text(
        '<testsuites><testsuite name="pytest"><testcase classname="tests.test_c" name="test_three"><failure message="x" /></testcase>'
        '<testcase classname="tests.test_c" name="test_three"><error message="failed on teardown with &quot;x&quot;" /></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    # A call failure plus a teardown error is one execution reported as two JUnit entries.
    assert release_gate._junit_execution_problems((parallel, teardown), collected) == []
    nested = _junit_report(tmp_path / "n.xml", [("tests.test_c", "test_three"), ("tests.test_f", "test_lane[tests/x.py::test_y-1]")])
    assert release_gate._junit_execution_problems((parallel, nested), collected | {"tests/test_f.py::test_lane[tests/x.py::test_y-1]"}) == []

    missing = _junit_report(tmp_path / "s2.xml", [])
    duplicated = _junit_report(tmp_path / "s3.xml", [("tests.test_c", "test_three"), ("tests.test_a", "test_one[x-1]")])
    unexpected = _junit_report(tmp_path / "s4.xml", [("tests.test_c", "test_three"), ("tests.test_d", "test_new")])
    assert "1 test(s) not executed: tests.test_c::test_three" in release_gate._junit_execution_problems(
        (parallel, missing), collected
    )
    assert "1 test(s) executed more than once: tests.test_a::test_one[x-1]" in release_gate._junit_execution_problems(
        (parallel, duplicated), collected
    )
    assert "1 test(s) not collected: tests.test_d::test_new" in release_gate._junit_execution_problems(
        (parallel, unexpected), collected
    )


def _source_fixture(root: Path) -> None:
    (root / "src" / "etf_cockpit").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "scripts").mkdir()
    (root / "src" / "etf_cockpit" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "configs" / "sample.yaml").write_text("enabled: true\n", encoding="utf-8")
    (root / "scripts" / "smoke_app.py").write_text("raise SystemExit(0)\n", encoding="utf-8")


def test_source_manifest_normalises_text_line_endings_but_not_binary(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_bytes(b"one\r\ntwo\rthree\n")
    (tmp_path / "blob.bin").write_bytes(b"one\r\ntwo")

    manifest = release_gate.build_source_manifest(tmp_path)
    by_path = {str(row["path"]): row for row in manifest["files"]}

    assert by_path["notes.md"]["bytes"] == len(b"one\ntwo\nthree\n")
    assert by_path["notes.md"]["sha256"] == release_gate.sha256_bytes(b"one\ntwo\nthree\n")
    assert by_path["blob.bin"]["sha256"] == release_gate.sha256_bytes(b"one\r\ntwo")


def test_release_signature_detects_manifest_tampering() -> None:
    payload = b'{"release":"one"}\n'
    key = b"a sufficiently long test signing key"
    signature = release_gate.sign_manifest(payload, key, key_id="test")

    assert release_gate.verify_manifest_signature(payload, signature, key)
    assert not release_gate.verify_manifest_signature(payload + b"tampered", signature, key)


def test_sbom_records_source_and_packaged_artifact_evidence(tmp_path: Path) -> None:
    source = release_gate.build_source_manifest(tmp_path)
    artifacts = {"manifest_sha256": "artifact-manifest", "files": [{"path": "app.exe"}]}
    sbom = release_gate.build_sbom(tmp_path, source, {"dependency_lock": "missing.txt"}, artifact_manifest=artifacts)

    app = next(component for component in sbom["components"] if component["bom-ref"] == "etf-ai-cockpit")
    properties = app["properties"]
    values = {str(row["name"]): str(row["value"]) for row in properties}
    assert values["source-manifest-sha256"] == str(source["manifest_sha256"])
    assert values["artifact-manifest-sha256"] == "artifact-manifest"
    assert values["artifact-file-count"] == "1"


def test_run_gate_writes_machine_readable_failure_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "schema_version: '1.0'\npython_version: '3.12.10'\ndependency_lock: requirements-release.txt\nartifact_roots: [build]\nsigning_key_env: TEST_RELEASE_KEY\n",
        encoding="utf-8",
    )
    locked_versions = {
        "exchange-calendars": "4.13.2",
        "flet": "0.85.3",
        "hypothesis": "6.156.6",
        "mypy": "1.20.2",
        "pytest": "9.1.1",
        "ruff": "0.15.20",
    }
    (tmp_path / "requirements-release.txt").write_text(
        "".join(f"{name}=={version}\n" for name, version in locked_versions.items()),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_RELEASE_KEY", "a sufficiently long test signing key")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"branch": "test", "head": "abc", "origin_main": "abc", "dirty": False})

    def installed_version(name: str) -> str:
        try:
            return locked_versions[name]
        except KeyError as exc:
            raise release_gate.importlib.metadata.PackageNotFoundError(name) from exc

    monkeypatch.setattr(release_gate.importlib.metadata, "version", installed_version)

    result = release_gate.run_gate(
        tmp_path,
        output_dir=tmp_path / "evidence",
        skip_tests=True,
        skip_package=True,
        skip_smoke=True,
    )

    assert result.exit_code == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["failures"] == []
    assert len(manifest["environment"]["fingerprint_sha256"]) == 64
    assert manifest["environment"]["retry"]["automatic_test_retries"] == 0
    assert manifest["evidence_paths"]["output_dir"] == str(result.output_dir)
    assert (result.output_dir / "sbom.cdx.json").exists()
    signature = json.loads((result.output_dir / "release-manifest.sig.json").read_text(encoding="utf-8"))
    assert signature["status"] == "signed"
    assert release_gate.verify_manifest_signature(
        result.manifest_path.read_bytes(), signature, b"a sufficiently long test signing key"
    )


def test_dry_run_lists_full_release_contract(tmp_path: Path, capsys) -> None:
    assert release_gate.main(["--root", str(tmp_path), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert any("pytest" in command for command in payload["commands"])
    assert any("SBOM" in command for command in payload["commands"])
    assert any("HMAC-SHA256" in command for command in payload["commands"])


def test_package_commands_cover_windows_and_linux_outputs() -> None:
    windows = release_gate.package_command(Path("."), platform_name="nt")
    linux = release_gate.package_command(Path("."), platform_name="posix")

    assert windows == ("cmd", "/c", "scripts\\build_windows.bat")
    assert linux[-3:] == ("build", "--outdir", "build/python-dist")


def test_windows_portable_parity_matches_real_build_layout(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    package = tmp_path / "build" / "portable"
    (package / "app").mkdir(parents=True)
    import shutil
    shutil.copytree(tmp_path / "src", package / "app" / "src")
    shutil.copytree(tmp_path / "configs", package / "configs")
    shutil.copytree(tmp_path / "scripts", package / "scripts")
    (tmp_path / "build" / "portable_outdir.txt").write_text("build/portable\n", encoding="utf-8")
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="nt"
    )
    assert prepared is not None and prepared.layout == "windows-portable"
    assert release_gate.source_package_parity(tmp_path, prepared).status == "passed"
    (package / "app" / "src" / "etf_cockpit" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    failure = release_gate.source_package_parity(tmp_path, prepared)
    assert failure.status == "failed"
    assert "src/etf_cockpit/sample.py" in failure.failure


def test_sdist_is_safely_extracted_runnable_and_parity_checked(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    staging = tmp_path / "staging" / "etf_ai_cockpit-1.0"
    import shutil
    shutil.copytree(tmp_path / "src", staging / "src")
    shutil.copytree(tmp_path / "configs", staging / "configs")
    shutil.copytree(tmp_path / "scripts", staging / "scripts")
    build = tmp_path / "build"
    build.mkdir()
    archive = build / "etf_ai_cockpit-1.0.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(staging, arcname=staging.name)
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="posix"
    )
    assert prepared is not None and prepared.layout == "sdist"
    assert prepared.smoke_script is not None and prepared.smoke_script.is_file()
    assert release_gate.source_package_parity(tmp_path, prepared).status == "passed"
    (prepared.root / "configs" / "sample.yaml").unlink()
    assert release_gate.source_package_parity(tmp_path, prepared).status == "failed"


def test_wheel_without_runtime_configs_fails_truthfully(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    wheel = build / "etf_ai_cockpit-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as handle:
        handle.write(
            tmp_path / "src" / "etf_cockpit" / "sample.py",
            "etf_cockpit/sample.py",
        )
    prepared = release_gate.prepare_package_artifact(
        tmp_path, {"artifact_roots": ["build"]}, tmp_path / "extract", platform_name="posix"
    )
    assert prepared is not None and prepared.layout == "wheel"
    assert prepared.smoke_script is None
    result = release_gate.source_package_parity(tmp_path, prepared)
    assert result.status == "failed"
    assert "configs->configs missing" in result.failure


def test_archive_extraction_rejects_path_escape(tmp_path: Path) -> None:
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as handle:
        handle.writestr("../escape.py", "bad")
    with pytest.raises(ValueError, match="escapes extraction root"):
        release_gate._safe_extract_archive(wheel, tmp_path / "extract")


@pytest.mark.parametrize(
    ("member_name", "member_type", "link_name"),
    [
        ("../escape.py", tarfile.REGTYPE, ""),
        ("symbolic-link.py", tarfile.SYMTYPE, "target.py"),
        ("hard-link.py", tarfile.LNKTYPE, "target.py"),
    ],
)
def test_tar_archive_extraction_rejects_escape_and_links(
    tmp_path: Path, member_name: str, member_type: bytes, link_name: str
) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    payload = b"unsafe"
    member = tarfile.TarInfo(member_name)
    member.type = member_type
    member.linkname = link_name
    member.size = len(payload) if member_type == tarfile.REGTYPE else 0
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload) if member.size else None)

    with pytest.raises(ValueError, match="unsafe archive member"):
        release_gate._safe_extract_archive(archive_path, tmp_path / "extract")


def test_dependency_snapshot_accepts_exact_parser_lock(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    (tmp_path / "requirements-release-parsers.txt").write_text("defusedxml==0.7.1\n", encoding="utf-8")
    policy = {
        "dependency_lock": "requirements-release.txt",
        "parser_dependency_lock": "requirements-release-parsers.txt",
    }
    versions = {"pytest": "9.1.1", "defusedxml": "0.7.1"}
    monkeypatch.setattr(release_gate.importlib.metadata, "version", versions.__getitem__)

    snapshot = release_gate.dependency_snapshot(tmp_path, policy)

    assert [row["path"] for row in snapshot["lock_files"]] == [
        "requirements-release.txt",
        "requirements-release-parsers.txt",
    ]
    assert snapshot["missing"] == []
    assert snapshot["mismatched"] == []
    assert snapshot["profiles"]["release"]["packages"] == ["pytest"]
    assert snapshot["profiles"]["parsers"] == {
        "required": True,
        "status": "required",
        "lock_path": "requirements-release-parsers.txt",
        "packages": ["defusedxml"],
    }


def test_dependency_snapshot_reports_optional_parser_tier_unavailable(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setattr(release_gate.importlib.metadata, "version", lambda _name: "9.1.1")

    snapshot = release_gate.dependency_snapshot(tmp_path, {"dependency_lock": "requirements-release.txt"})

    assert snapshot["profiles"]["parsers"] == {
        "required": False,
        "status": "unavailable",
        "lock_path": None,
        "packages": [],
    }


def test_environment_check_fails_when_named_tooling_is_absent_without_parser_lock(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "requirements-release.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    monkeypatch.setattr(release_gate.platform, "python_version", lambda: "3.12.10")
    monkeypatch.setattr(release_gate.importlib.metadata, "version", lambda _name: "9.1.1")
    monkeypatch.setattr(release_gate, "git_snapshot", lambda _root: {"dirty": False})

    check = release_gate.environment_check(
        tmp_path,
        {
            "python_version": "3.12.10",
            "dependency_lock": "requirements-release.txt",
        },
        allow_dirty=False,
    )

    assert check.status == "failed"
    assert "required tooling absent from lock profile" in check.failure
    assert "flet" in check.failure


def test_environment_verification_emits_structured_failure_for_missing_lock(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "release_policy.yaml").write_text(
        "python_version: '3.12.10'\ndependency_lock: missing.txt\n",
        encoding="utf-8",
    )

    exit_code = release_gate.main(["--root", str(tmp_path), "--verify-environment"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["check"]["status"] == "failed"
    assert payload["check"]["exit_code"] == 2
    assert "dependency lock is missing" in payload["check"]["failure"]
    assert payload["environment"] is None


def test_parallel_pilot_is_report_only_when_xdist_is_unavailable(monkeypatch) -> None:
    def missing(_name: str) -> str:
        raise release_gate.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(release_gate.importlib.metadata, "version", missing)

    evidence = release_gate.parallel_pilot_evidence()

    assert evidence["status"] == "unavailable"
    assert evidence["mode"] == "report_only"
    assert evidence["authority"] == "serial"
    assert evidence["workers"] == 4
    assert evidence["collection_parity"] == {
        "required": True,
        "comparison": "ordered_nodeids",
        "status": "not_run",
    }
    assert evidence["schema_version"] == "pytest-parallel-pilot.v2"
    assert "--collect-only" in evidence["commands"]["candidate_safe_collection"]
    assert "-n 4 --dist loadfile" in evidence["commands"]["candidate_safe_execution"]
    assert evidence["serial_groups"] == [
        "concurrency",
        "environment",
        "flet",
        "package",
        "ports",
        "sqlite",
    ]


def test_git_snapshot_ignores_only_generated_release_evidence(monkeypatch) -> None:
    values = {
        ("status", "--porcelain", "--untracked-files=all"): "?? artifacts/release/latest/release-report.md\n M configs/release_policy.yaml\n",
        ("branch", "--show-current"): "feature",
        ("rev-parse", "HEAD"): "head",
        ("rev-parse", "origin/main"): "main",
    }
    monkeypatch.setattr(release_gate, "_git", lambda _root, *args: values.get(args, ""))

    snapshot = release_gate.git_snapshot(Path("."))

    assert snapshot["dirty"] is True
    assert snapshot["dirty_paths"] == [" M configs/release_policy.yaml"]


def test_release_workflow_is_matrixed_isolated_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")
    trigger = workflow.split("permissions:", maxsplit=1)[0]
    preflight = workflow[
        workflow.index("  preflight:") : workflow.index("  supply-chain:")
    ]

    assert "\n  pull_request:\n" in trigger
    assert "\n  push:" not in trigger
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes: 50" in workflow
    assert "timeout-minutes: 30" in preflight
    assert "Configure isolated user profile" in workflow
    assert "Pin reviewed canonical generation base" in workflow
    assert "PR_BASE_SHA: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || '' }}" in workflow
    assert "github.event.pull_request.base.ref || 'main'" in workflow
    assert "git update-ref refs/remotes/origin/main \"$REVIEWED_BASE_SHA\"" in workflow
    assert 'test "$(git rev-parse origin/main)" = "$REVIEWED_BASE_SHA"' in workflow
    assert "requirements-release-parsers.txt" in workflow
    assert "ETF_COCKPIT_RELEASE_BUILD: \"1\"" in workflow
    assert "secrets.RELEASE_SIGNING_KEY" not in workflow
    assert "github.event_name == 'pull_request' && needs.classifier.outputs.package_gate_required == 'true'" in workflow
    assert "arguments=(--root . --output \"$output\" --allow-unsigned --xdist-workers auto)" in workflow
    assert "repository_dispatch:" in trigger
    assert "workflow_dispatch:" not in trigger
    assert "parallel-pilot-drift" in trigger
    assert "parallel-pilot-full" in trigger
    assert "name: release-gate-${{ github.sha }}-${{ matrix.platform }}" in workflow
    assert "contents: read" in workflow
    assert "issues: write" not in workflow
    assert "releases: write" not in workflow


def test_xdist_collection_lists_node_ids_despite_quiet_addopts() -> None:
    root = Path(__file__).resolve().parents[1]
    command = release_gate._python_command(
        root, "-m", "pytest", "--collect-only", "--verbosity=-1", "tests/test_atomic_io.py"
    )
    nodeids, _elapsed, failure = release_gate._collect_test_nodeids(root, command)
    assert failure == ""
    assert nodeids and all(nodeid.startswith("tests/test_atomic_io.py::") for nodeid in nodeids)


def test_failure_digest_groups_causes_and_names_product_and_test_frames(tmp_path: Path) -> None:
    from scripts import failure_digest

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("", encoding="utf-8")
    trace = (
        "def test_a():\n>       run()\ntests/test_x.py:7: in test_a\nsrc/etf_cockpit/core/io.py:42: in run\n"
        "E   PermissionError: [WinError 5] Access is denied: 'data/x.parquet'\n"
    )
    cases = "".join(
        f'<testcase classname="tests.test_x" name="{name}" time="1.5"><failure message="PermissionError">{trace}</failure></testcase>'
        for name in ("test_a", "test_b[1]")
    )
    junit = tmp_path / "junit.xml"
    junit.write_text(
        f'<testsuites><testsuite name="pytest">{cases}<testcase classname="tests.test_x" name="test_ok" time="0.1" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    digest = failure_digest.render([junit], tmp_path)

    assert digest.splitlines()[0] == "TESTS 3 | failed 2 | errors 0 | skipped 0 | slowest test 2s"
    assert "[1] 2x PermissionError: [WinError 5] Access is denied: 'data/x.parquet'" in digest
    assert "at: product src/etf_cockpit/core/io.py:42 | test tests/test_x.py:7" in digest
    assert "- tests/test_x.py::test_b[1]" in digest


def test_failure_digest_reports_failed_gate_checks_and_passes_cleanly(tmp_path: Path) -> None:
    from scripts import failure_digest

    (tmp_path / "release-report.md").write_text(
        "- Schema: `1.0`\n\n## Failures\n- pinned_environment: missing locked packages: pdfplumber\n", encoding="utf-8"
    )
    _junit_report(tmp_path / "junit-parallel.xml", [("tests.test_c", "test_three")])
    digest = failure_digest.render([tmp_path], tmp_path)

    assert "CHECK FAILED pinned_environment: missing locked packages: pdfplumber" in digest
    assert "Schema" not in digest
    assert failure_digest.render([tmp_path / "junit-parallel.xml"], tmp_path).endswith("OK: no failing tests or checks")
