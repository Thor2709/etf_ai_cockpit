from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_ui_pages as renderer
from etf_cockpit.app.router import PAGES


def test_route_slugs_are_unique_and_filesystem_safe_for_every_page() -> None:
    slugs = [renderer.route_to_slug(route) for route in PAGES]

    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in slugs)
    assert renderer.route_to_slug("/") == "home"


def test_cli_defaults() -> None:
    args = renderer.build_parser().parse_args([])

    assert args.routes is None
    assert args.out == Path("artifacts/ui-render")
    assert args.width == 1920
    assert args.height == 1200
    assert args.settle_ms == 15000
    assert args.browser is None
    assert args.timeout_s == 60


def test_missing_browser_path_exits_two_with_clear_message(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    missing_browser = tmp_path / "missing-chromium"

    result = renderer.main(["--browser", str(missing_browser)])

    assert result == 2
    assert f"Chromium-family browser not found: {missing_browser}" in capsys.readouterr().err


def test_missing_websockets_exits_two_with_clear_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(renderer, "resolve_browser", lambda _explicit: Path("browser"))
    monkeypatch.setattr(renderer.importlib.util, "find_spec", lambda _name: None)

    result = renderer.main(["--browser", "browser"])

    assert result == 2
    assert "The 'websockets' package is required" in capsys.readouterr().err


class FakeDriver:
    def __init__(self) -> None:
        self.console_errors: list[str] = []

    async def capture(
        self,
        url: str,
        png_path: Path,
        *,
        width: int,
        height: int,
        timeout_s: float,
        settle_ms: int,
    ) -> list[str]:
        assert url.startswith("http://127.0.0.1:8550")
        assert (width, height, timeout_s, settle_ms) == (800, 600, 5, 0)
        if url.endswith("/portfolio"):
            self.console_errors = ["console failure"]
            raise TimeoutError("route did not render")
        png_path.write_bytes(b"fake png")
        self.console_errors = []
        return []


def test_fake_render_writes_index_schema_for_success_and_failure(tmp_path: Path) -> None:
    output = tmp_path / "output"
    rows = asyncio.run(
        renderer.render_routes(
            ["/", "/portfolio"],
            output,
            FakeDriver(),
            base_url="http://127.0.0.1:8550",
            width=800,
            height=600,
            timeout_s=5,
            settle_ms=0,
        )
    )

    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert index == rows
    assert len(index) == 2
    assert all(set(row) == {"route", "png", "ok", "error", "console_errors"} for row in index)
    assert index[0] == {
        "route": "/",
        "png": "home.png",
        "ok": True,
        "error": None,
        "console_errors": [],
    }
    assert index[1] == {
        "route": "/portfolio",
        "png": "portfolio.png",
        "ok": False,
        "error": "TimeoutError: route did not render",
        "console_errors": ["console failure"],
    }
    assert (output / "home.png").read_bytes() == b"fake png"
