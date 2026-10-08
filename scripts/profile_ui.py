"""Measure Flet shell build time per route, startup, and cProfile the slowest routes.

Read-only measurement tool (no network, ``execution_allowed`` untouched).

    python scripts/profile_ui.py --out C:/dev/queues/UI/perf-report.md [--repeat 3] [--profile-top 5]
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 1)


def _top_functions(profile: cProfile.Profile, limit: int = 12) -> str:
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(limit)
    return stream.getvalue()


def measure_cold_start() -> dict:
    """First painted shell in a fresh interpreter: imports + loading view (Flet server start-up excluded)."""

    import subprocess

    code = (
        "import sys, time, json; t0 = time.perf_counter(); sys.path.insert(0, 'src');"
        "import etf_cockpit.app.flet_app as f; t1 = time.perf_counter();"
        "view = f.build_loading_view('/'); t2 = time.perf_counter();"
        "heavy = [m for m in ('pandas', 'numpy', 'scipy', 'etf_cockpit.app.router', 'etf_cockpit.app.state') if m in sys.modules];"
        "print(json.dumps({'import_ms': round((t1 - t0) * 1000, 1), 'build_ms': round((t2 - t1) * 1000, 1), 'heavy_modules': heavy}))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {"error": (result.stderr or result.stdout)[-300:]}


class _TimedPage(SimpleNamespace):
    def update(self, *_args: object) -> None:
        self.updates = getattr(self, "updates", 0) + 1


def measure_staged_routes(state, routes: list[str]) -> dict[str, dict]:
    """Event-thread time of a navigation (render_route_change) versus the time until the final page is painted."""

    import threading

    from etf_cockpit.app import router

    rows: dict[str, dict] = {}
    for route in routes:
        page = _TimedPage(width=1920, height=1200, route=route, views=[], updates=0)
        done = threading.Event()
        t0 = time.perf_counter()
        router.render_route_change(page, state, route, background=True, on_done=done.set)
        blocked = time.perf_counter() - t0
        done.wait(600)
        rows[route] = {
            "event_thread_ms": _ms(blocked),
            "final_paint_ms": _ms(time.perf_counter() - t0),
            "skeleton_frame": page.updates > 1,
        }
    return rows


def measure_segments(state, routes: list[str]) -> dict[str, dict]:
    """Time every top-bar segment change (``on_change``) of every page: the in-place filter/segment path."""

    from etf_cockpit.app import router
    from etf_cockpit.app.components.shell.page_view import PageView

    rows: dict[str, dict] = {}
    for route in routes:
        page = _TimedPage(width=1920, height=1200, route=route, views=[], updates=0)
        built = router.build_page(page, state, route)
        if not isinstance(built, PageView):
            continue
        samples: list[float] = []
        failures = 0
        for group in built.chrome.segment_groups:
            if group.on_change is None:
                continue
            for item in group.items:
                t0 = time.perf_counter()
                try:
                    group.on_change(item)
                except Exception:
                    failures += 1
                samples.append(time.perf_counter() - t0)
        if samples or failures:
            rows[route] = {"changes": len(samples), "max_ms": _ms(max(samples, default=0.0)), "failures": failures}
    return rows


def measure(repeat: int, profile_top: int, json_path: Path | None) -> dict:
    t0 = time.perf_counter()
    import flet as ft  # noqa: F401
    from etf_cockpit.app import router  # noqa: F401
    t_import = time.perf_counter() - t0

    from etf_cockpit.app.state import AppState
    from etf_cockpit.application.snapshot_builder import build_snapshot

    t0 = time.perf_counter()
    snapshot = build_snapshot()
    t_snapshot = time.perf_counter() - t0

    profiler = cProfile.Profile()
    profiler.enable()
    t0 = time.perf_counter()
    AppState.load()
    t_state_load = time.perf_counter() - t0
    profiler.disable()
    startup_profile = _top_functions(profiler, 25)

    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = SimpleNamespace(width=1920, height=1200, route="/")
    routes = list(router.PAGES)
    rows: dict[str, dict] = {}
    for route in routes:
        samples = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            router.build_shell(page, state, route)
            samples.append(time.perf_counter() - t0)
        rows[route] = {
            "first_ms": _ms(samples[0]),
            "warm_ms": _ms(min(samples[1:]) if len(samples) > 1 else samples[0]),
            "median_ms": _ms(statistics.median(samples)),
        }

    ranked = sorted(rows, key=lambda r: rows[r]["median_ms"], reverse=True)
    cold_start = measure_cold_start()
    staged = measure_staged_routes(state, routes)
    segments = measure_segments(state, routes)
    profiles = {}
    for route in ranked[:profile_top]:
        profiler = cProfile.Profile()
        profiler.enable()
        router.build_shell(page, state, route)
        profiler.disable()
        profiles[route] = _top_functions(profiler)
    result = {
        "import_ms": _ms(t_import),
        "snapshot_ms": _ms(t_snapshot),
        "state_load_ms": _ms(t_state_load),
        "routes": rows,
        "ranked": ranked,
        "cold_start": cold_start,
        "staged": staged,
        "segments": segments,
        "startup_profile": startup_profile,
        "route_profiles": profiles,
    }
    if json_path:
        json_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def render(result: dict) -> str:
    lines = [
        "# UI performance report",
        "",
        f"- import flet + router: {result['import_ms']} ms",
        f"- build_snapshot: {result['snapshot_ms']} ms",
        f"- AppState.load (migrations + snapshot + settings): {result['state_load_ms']} ms",
        "",
        f"- cold start to painted loading shell (fresh interpreter, no Flet server): {result['cold_start']}",
        "",
        "| rank | route | first ms | median ms | best-warm ms | event-thread ms (staged) | final paint ms (staged) | skeleton frame |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, route in enumerate(result["ranked"], 1):
        row = result["routes"][route]
        staged = result["staged"].get(route, {})
        lines.append(
            f"| {index} | `{route}` | {row['first_ms']} | {row['median_ms']} | {row['warm_ms']} | "
            f"{staged.get('event_thread_ms')} | {staged.get('final_paint_ms')} | {staged.get('skeleton_frame')} |"
        )
    lines += ["", "## Segment / filter changes (page chrome on_change, max per route)", "", "| route | changes | max ms | failures |", "|---|---|---|---|"]
    for route, row in sorted(result["segments"].items(), key=lambda item: -item[1]["max_ms"]):
        lines.append(f"| `{route}` | {row['changes']} | {row['max_ms']} | {row['failures']} |")
    total = sum(result["routes"][r]["median_ms"] for r in result["ranked"])
    lines += ["", f"Sum of medians: {round(total, 1)} ms over {len(result['ranked'])} routes", ""]
    lines += ["## Startup cProfile (AppState.load)", "```", result["startup_profile"], "```"]
    for route, text in result["route_profiles"].items():
        lines += [f"## cProfile `{route}`", "```", text, "```"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--profile-top", type=int, default=5)
    args = parser.parse_args()
    result = measure(max(1, args.repeat), args.profile_top, args.json)
    text = render(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print("\n".join(text.splitlines()[:70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
