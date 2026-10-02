import json

from scripts.update_test_durations import main


def test_junit_reports_refresh_sorted_file_weights(tmp_path) -> None:
    linux_report = tmp_path / "linux.xml"
    linux_report.write_text(
        """<testsuites><testsuite>
        <testcase classname="tests.test_zebra" name="first" time="0.46" />
        <testcase classname="tests.test_zebra" name="second" time="0.56" />
        <testcase classname="tests.issue0014.test_routes" name="route" time="0.35" />
        </testsuite></testsuites>""",
        encoding="utf-8",
    )
    windows_report = tmp_path / "windows.xml"
    windows_report.write_text(
        """<testsuites><testsuite>
        <testcase classname="tests.test_zebra" name="first" time="1.26" />
        <testcase classname="tests.issue0014.test_routes" name="route" time="0.86" />
        </testsuite></testsuites>""",
        encoding="utf-8",
    )
    output = tmp_path / "file_durations.json"

    assert main(
        [
            "--output",
            str(output),
            str(linux_report),
            str(windows_report),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "source": f"JUnit XML reports: {tmp_path.name}/linux.xml, {tmp_path.name}/windows.xml",
        "unit": "seconds",
        "files": {
            "tests/issue0014/test_routes.py": 0.9,
            "tests/test_zebra.py": 1.3,
        },
    }
    assert list(payload["files"]) == ["tests/issue0014/test_routes.py", "tests/test_zebra.py"]
    assert {str(key): float(value) for key, value in payload["files"].items()} == payload["files"]
