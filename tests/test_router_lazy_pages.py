from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

from etf_cockpit.app import router


def test_importing_router_does_not_import_page_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    code = textwrap.dedent(
        """
        import sys
        import etf_cockpit.app.router
        print(sorted(name for name in sys.modules if name.startswith("etf_cockpit.app.pages.")))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo_root, env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip() == "[]"


def test_every_registered_route_resolves_to_a_callable_factory() -> None:
    assert list(router.PAGES) == [route for route, _title in router.ROUTE_TITLES]
    for route, (title, factory) in router.PAGES.items():
        assert title, route
        assert callable(factory), route
        assert callable(factory.resolve()), route


def test_page_import_failure_renders_the_route_error_path(monkeypatch) -> None:
    missing = router._LazyPage("etf_cockpit.app.pages.does_not_exist_module", "missing_page")
    monkeypatch.setitem(router.PAGES, "/lazy-missing", ("Lazy missing", missing))
    state = SimpleNamespace(last_message="")

    built = router.build_page(SimpleNamespace(), state, "/lazy-missing")  # type: ignore[arg-type]

    assert built is not None
    assert "Route failure: /lazy-missing" in state.last_message
    assert "ModuleNotFoundError" in state.last_message
    assert missing._factory is None
