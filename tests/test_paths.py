from __future__ import annotations

from pathlib import Path

from etf_cockpit.core.paths import project_root


def _make_project_root(path: Path) -> Path:
    (path / "configs").mkdir(parents=True)
    (path / "configs" / "universe.yaml").write_text("universe: test\n", encoding="utf-8")
    return path


def test_project_root_prefers_valid_env_root_over_cwd(tmp_path) -> None:
    env_root = _make_project_root(tmp_path / "visible_project")
    cwd_root = _make_project_root(tmp_path / "other_project")

    assert project_root(start=tmp_path / "bundle" / "app.py", cwd=cwd_root, env_root=str(env_root)) == env_root


def test_project_root_uses_cwd_before_bundled_internal_config(tmp_path) -> None:
    visible_root = _make_project_root(tmp_path / "visible_project")
    internal_root = _make_project_root(tmp_path / "build" / "flet_dist" / "ETF_AI_Cockpit" / "_internal")
    bundled_file = internal_root / "src" / "etf_cockpit" / "core" / "paths.py"

    assert project_root(start=bundled_file, cwd=visible_root, env_root="") == visible_root


def test_project_root_ignores_invalid_env_root_and_uses_cwd(tmp_path) -> None:
    visible_root = _make_project_root(tmp_path / "visible_project")
    invalid_env_root = tmp_path / "missing_project"

    assert project_root(start=tmp_path / "bundle" / "app.py", cwd=visible_root, env_root=str(invalid_env_root)) == visible_root
