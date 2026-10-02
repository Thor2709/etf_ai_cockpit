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
    assert list(payload["files"]) == ["tests/issue0014/test_routes.py", "tests/test_zebra.py"]
    assert {str(key): float(value) for key, value in payload["files"].items()} == payload["files"]
