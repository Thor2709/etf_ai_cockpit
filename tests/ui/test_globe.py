from __future__ import annotations

import math

import flet as ft
import flet.canvas as cv
import numpy as np

from etf_cockpit.app.components import globe as g

EXPOSURE = {"USA": 62.0, "JPN": 5.5, "GBR": 3.6, "CAN": None, "CHN": float("nan"), "DEU": -1.0}


def _paths(canvas: cv.Canvas) -> list[cv.Path]:
    return [shape for shape in canvas.shapes if isinstance(shape, cv.Path)]


def test_assets_cover_36_centres_and_geojson_is_packaged() -> None:
    assert len(list(g.GLOBE_DIR.glob("globe_*.png"))) == g.CENTRE_COUNT
    assert all(g.globe_asset_path(i).is_file() for i in range(g.CENTRE_COUNT))
    assert sum(p.stat().st_size for p in g.GLOBE_DIR.glob("*.png")) < 4 * 1024 * 1024
    assert g.GEOJSON_PATH.is_file()
    codes = {c.iso3 for c in g.load_countries()}
    assert {"USA", "JPN", "GBR", "NOR", "FRA"} <= codes
    assert g.centre_longitude(g.centre_index(-35)) == -35


def test_orthographic_projection_round_trips_and_hides_far_side() -> None:
    for lon, lat in [(-35.0, 28.0), (-100.0, 40.0), (10.0, 51.0)]:
        x, y, z = g.ortho_project(np.array([lon]), np.array([lat]), -35.0)
        assert z[0] > 0
        back = g.ortho_inverse(float(x[0]), float(y[0]), -35.0)
        assert back is not None and math.isclose(back[0], lon, abs_tol=1e-6) and math.isclose(back[1], lat, abs_tol=1e-6)
    _, _, z = g.ortho_project(np.array([145.0]), np.array([-28.0]), -35.0)
    assert z[0] < 0


def test_missing_exposure_is_uncoloured_never_zero() -> None:
    assert g.clean_exposure(EXPOSURE) == {"USA": 62.0, "JPN": 5.5, "GBR": 3.6}
    globe = g.Globe(EXPOSURE, None, size=400)
    fills = {p.paint.color for p in _paths(globe.overlay) if p.paint.style == ft.PaintingStyle.FILL} - {"#4d000000"}
    assert fills <= {g.exposure_fill(62.0), g.exposure_fill(5.5), g.exposure_fill(3.6)} and len(fills) >= 2
    assert g.exposure_fill(62.0) == "#ccffc85a"  # alpha 0.30 + min(0.5, w/30)
    assert {c.iso3 for c in g.load_countries() if c.iso3 in globe.exposure} == {"USA", "JPN", "GBR"}


def test_unavailable_reason_and_empty_data_show_reason_without_fake_numbers() -> None:
    empty = g.Globe({}, None, size=300)
    assert empty.badge.visible and "No country exposure available" in empty.badge.content.value
    assert not [p for p in _paths(empty.overlay)]
    reason = g.WorldMap({"USA": 10.0}, "ETF holdings evidence missing")
    assert reason.badge.visible and "ETF holdings evidence missing" in reason.badge.content.value
    assert "unavailable" in reason.control.label.lower()


def test_rotation_swaps_base_image_and_reprojects() -> None:
    globe = g.Globe({"USA": 62.0, "JPN": 5.5}, None, size=400)
    first_src, first_shapes = globe.image.src, list(globe.overlay.shapes)
    assert first_src.endswith(f"globe_{g.centre_index(-35):02d}.png")
    globe.rotate_to(-34.0)  # same 10 degree image: nothing changes
    assert globe.image.src == first_src
    globe.rotate_to(120.0)
    assert globe.image.src != first_src and globe.overlay.shapes != first_shapes
    assert g.Globe({"USA": 1.0}, None, asset_base="globe").image.src.startswith("globe/globe_")


def test_world_map_paints_same_polygons_and_hit_tests() -> None:
    world = g.WorldMap({"USA": 62.0, "JPN": 5.5}, None, width=720, return_by_country={"USA": 8.0})
    assert len(_paths(world.canvas)) > 2 * 5
    hit = world.hit_test((-98 + 180) / 360 * 720, (world.LAT_TOP - 39) / (world.LAT_TOP - world.LAT_BOTTOM) * world.height)
    assert hit is not None and hit.iso3 == "USA"
    assert world.describe(hit) == "USA · 62% · +8.0%"
    assert world.hit_test(10, 10) is None
