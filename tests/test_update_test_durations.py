import json

from scripts.update_test_durations import main


def test_junit_reports_refresh_sorted_file_weights(tmp_path) -> None:
    linux_first_report = tmp_path / "linux" / "linux-s1.xml"
    linux_first_report.parent.mkdir()
    linux_first_report.write_text(
        """<testsuites><testsuite>
        <testcase classname="tests.test_zebra" name="first" time="4.0" />
        <testcase classname="tests.issue0014.test_routes" name="route" time="0.35" />
        </testsuite></testsuites>""",
        encoding="utf-8",
    )
    linux_second_report = tmp_path / "linux" / "linux-s2.xml"
    linux_second_report.write_text(
        """<testsuites><testsuite>
        <testcase classname="tests.test_zebra" name="second" time="6.0" />
        </testsuite></testsuites>""",
        encoding="utf-8",
    )
    windows_report = tmp_path / "windows" / "windows-s1.xml"
    windows_report.parent.mkdir()
    windows_report.write_text(
        """<testsuites><testsuite>
        <testcase classname="tests.test_zebra" name="first" time="8.0" />
        <testcase classname="tests.issue0014.test_routes" name="route" time="0.86" />
        </testsuite></testsuites>""",
        encoding="utf-8",
    )
    output = tmp_path / "file_durations.json"

    assert main(
        [
            "--output",
            str(output),
            str(linux_first_report),
            str(linux_second_report),
            str(windows_report),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "source": "JUnit XML reports: linux/linux-s1.xml, linux/linux-s2.xml, windows/windows-s1.xml",
        "unit": "seconds",
        "files": {
            "tests/issue0014/test_routes.py": 0.9,
            "tests/test_zebra.py": 10.0,
        },
    }
    assert "serial_files" not in payload  # no serial-phase report supplied: the old shape is kept
    assert list(payload["files"]) == ["tests/issue0014/test_routes.py", "tests/test_zebra.py"]
    assert {str(key): float(value) for key, value in payload["files"].items()} == payload["files"]


def _write(path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>", encoding="utf-8")


def test_serial_phase_reports_fill_serial_files_without_double_counting_complete_reports(tmp_path) -> None:
    for platform, serial_time in (("linux", "3.0"), ("windows", "5.0")):
        directory = tmp_path / platform
        _write(
            directory / "junit-parallel.xml",
            '<testcase classname="tests.test_p" name="a" time="2.0" />',
        )
        _write(
            directory / "junit-serial.xml",
            f'<testcase classname="tests.test_s" name="a" time="{serial_time}" />'
            '<testcase classname="tests.test_p" name="s" time="1.0" />',
        )
        _write(
            directory / "junit-full.xml",
            '<testcase classname="tests.test_p" name="a" time="2.0" />'
            f'<testcase classname="tests.test_s" name="a" time="{serial_time}" />'
            '<testcase classname="tests.test_p" name="s" time="1.0" />',
        )
    output = tmp_path / "out.json"
    reports = [str(tmp_path / platform / name) for platform in ("linux", "windows") for name in ("junit-full.xml", "junit-serial.xml")]

    assert main(["--output", str(output), *reports]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["files"] == {"tests/test_p.py": 3.0, "tests/test_s.py": 5.0}  # full report only, slower platform
    assert payload["serial_files"] == {"tests/test_p.py": 1.0, "tests/test_s.py": 5.0}


def test_serial_reports_alone_with_a_parallel_phase_complete_the_file_totals(tmp_path) -> None:
    _write(tmp_path / "linux" / "junit-parallel.xml", '<testcase classname="tests.test_p" name="a" time="2.0" />')
    _write(tmp_path / "linux" / "junit-serial.xml", '<testcase classname="tests.test_p" name="s" time="4.0" />')
    output = tmp_path / "out.json"

    assert main(["--output", str(output), str(tmp_path / "linux" / "junit-parallel.xml"), str(tmp_path / "linux" / "junit-serial.xml")]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["files"] == {"tests/test_p.py": 6.0}
    assert payload["serial_files"] == {"tests/test_p.py": 4.0}


def test_an_empty_serial_phase_report_is_accepted(tmp_path) -> None:
    _write(tmp_path / "linux" / "junit-parallel.xml", '<testcase classname="tests.test_p" name="a" time="2.0" />')
    _write(tmp_path / "linux" / "junit-serial.xml", "")
    output = tmp_path / "out.json"

    assert main(["--output", str(output), str(tmp_path / "linux" / "junit-parallel.xml"), str(tmp_path / "linux" / "junit-serial.xml")]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["files"] == {"tests/test_p.py": 2.0}
    assert payload["serial_files"] == {}
