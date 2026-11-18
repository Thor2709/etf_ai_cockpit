"""GT4: the Windows-only launcher test carries a skip reason the release-gate execution parity accepts."""

from scripts import release_gate


def test_windows_only_launcher_skip_reason_is_documented() -> None:
    assert release_gate._skip_reason_allowed("requires Windows: runs the generated cmd runner")
    assert not release_gate._skip_reason_allowed("runs the generated cmd runner")


def test_optional_extra_import_skip_reasons_are_allowed_but_not_core_deps() -> None:
    assert release_gate._skip_reason_allowed("could not import 'arch.univariate.base': No module named 'arch'")
    assert not release_gate._skip_reason_allowed("could not import 'fastapi': No module named 'fastapi'")
