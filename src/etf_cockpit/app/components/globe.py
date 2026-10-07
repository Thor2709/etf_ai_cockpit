"""Globe and world-map views for the Sectors & Countries page (presentation only).

``Globe`` shows a pre-rendered Blue Marble orthographic disc (36 centre longitudes, latitude
fixed at 28 degrees, see ``scripts/build_globe_assets.py``) with country polygons projected in
Python and painted over it on ``flet.canvas``. ``WorldMap`` paints the same polygons on an
equirectangular projection. Exposure values are percent of portfolio; ``None``/non-finite means
missing and the country stays uncoloured (never drawn as zero).
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import flet as ft
import flet.canvas as cv
import numpy as np

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
GLOBE_DIR = ASSET_DIR / "globe"
GEOJSON_PATH = ASSET_DIR / "geo" / "countries.geojson"

LATITUDE_DEG = 28.0
DEFAULT_CENTRE_LON = -35.0
CENTRE_COUNT = 36
CENTRE_STEP = 10
FIRST_CENTRE = -175
DISC_FRACTION = 0.90  # disc diameter / control size; the rest is the atmosphere glow
ATMOSPHERE = "#7fb8ff"
_SHORT_NAMES = {"USA": "USA", "GBR": "UK"}


def _hex(r: int, g: int, b: int, alpha: float) -> str:
    return f"#{round(max(0.0, min(1.0, alpha)) * 255):02x}{r:02x}{g:02x}{b:02x}"


def exposure_fill(weight_pct: float) -> str:
    """Amber ramp from the spec: alpha 0.30 + min(0.5, weight / 30)."""
    return _hex(255, 200, 90, 0.30 + min(0.5, weight_pct / 30.0))


def clean_exposure(exposure: Mapping[str, float | None] | None) -> dict[str, float]:
    """Keep only finite, non-negative values; missing stays missing (never zero-filled)."""
    cleaned: dict[str, float] = {}
    for code, value in (exposure or {}).items():
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0.0:
            cleaned[str(code).upper()] = number
    return cleaned


def _format_pct(value: float) -> str:
    return f"{value:.0f}%" if value >= 10 else f"{value:.1f}%"


@dataclass(frozen=True)
class Country:
    iso3: str
    name: str
    rings: tuple[np.ndarray, ...]  # outer rings, (n, 2) lon/lat degrees
    anchor: tuple[float, float]  # (lon, lat) label point


def _ring_centroid(ring: np.ndarray) -> tuple[float, float]:
    x, y = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y2 - x2 * y
    area = cross.sum() / 2.0
    if abs(area) < 1e-9:
        return float(x.mean()), float(y.mean())
    return float(((x + x2) * cross).sum() / (6 * area)), float(((y + y2) * cross).sum() / (6 * area))


def _ring_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return abs(float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum()) / 2.0)


@lru_cache(maxsize=1)
def load_countries() -> tuple[Country, ...]:
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    countries: list[Country] = []
    for feature in data["features"]:
        props = feature["properties"]
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = tuple(np.asarray(polygon[0], dtype=np.float64)[:, :2] for polygon in polygons if polygon)
        if not rings:
            continue
        biggest = max(rings, key=_ring_area)
        countries.append(
            Country(str(props["ADM0_A3"]), str(props.get("NAME") or props["ADM0_A3"]), rings, _ring_centroid(biggest))
        )
    return tuple(countries)


def _point_in_ring(ring: np.ndarray, lon: float, lat: float) -> bool:
    x, y = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    crosses = (y > lat) != (y2 > lat)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_at = (x2 - x) * (lat - y) / (y2 - y) + x
    return bool(np.count_nonzero(crosses & (lon < x_at)) % 2)


def country_at(lon: float, lat: float, candidates: Mapping[str, float]) -> Country | None:
    for country in load_countries():
        if country.iso3 not in candidates:
            continue
        if any(_point_in_ring(ring, lon, lat) for ring in country.rings):
            return country
    return None


# ---------------------------------------------------------------- projection
def ortho_project(lon_deg: np.ndarray, lat_deg: np.ndarray, centre_lon_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Orthographic projection (unit sphere). Returns x (right), y (up), z (towards viewer)."""
    lam = np.radians(lon_deg) - math.radians(centre_lon_deg)
    phi = np.radians(lat_deg)
    phi0 = math.radians(LATITUDE_DEG)
    x = np.cos(phi) * np.sin(lam)
    y = math.cos(phi0) * np.sin(phi) - math.sin(phi0) * np.cos(phi) * np.cos(lam)
    z = math.sin(phi0) * np.sin(phi) + math.cos(phi0) * np.cos(phi) * np.cos(lam)
    return x, y, z


def ortho_inverse(x: float, y: float, centre_lon_deg: float) -> tuple[float, float] | None:
    rho2 = x * x + y * y
    if rho2 > 1.0:
        return None
    z = math.sqrt(1.0 - rho2)
    phi0 = math.radians(LATITUDE_DEG)
    lat = math.asin(max(-1.0, min(1.0, z * math.sin(phi0) + y * math.cos(phi0))))
    lon = math.radians(centre_lon_deg) + math.atan2(x, z * math.cos(phi0) - y * math.sin(phi0))
    return (math.degrees(lon) + 180.0) % 360.0 - 180.0, math.degrees(lat)


def centre_index(lon_deg: float) -> int:
    return int(round((lon_deg - FIRST_CENTRE) / CENTRE_STEP)) % CENTRE_COUNT


def centre_longitude(index: int) -> int:
    return FIRST_CENTRE + CENTRE_STEP * (index % CENTRE_COUNT)


def globe_asset_path(index: int) -> Path:
    return GLOBE_DIR / f"globe_{index % CENTRE_COUNT:02d}.png"


def _path(points: np.ndarray, paint: ft.Paint) -> cv.Path:
    elements: list = [cv.Path.MoveTo(round(float(points[0, 0]), 1), round(float(points[0, 1]), 1))]
    elements.extend(cv.Path.LineTo(round(float(px), 1), round(float(py), 1)) for px, py in points[1:])
    elements.append(cv.Path.Close())
    return cv.Path(elements, paint)


_FILL = ft.PaintingStyle.FILL
_STROKE = ft.PaintingStyle.STROKE


def _label_shapes(text: str, x: float, y: float) -> list[cv.Shape]:
    dot = cv.Circle(x, y, 2.6, ft.Paint(color="#ffffff", style=_FILL))
    shadow = cv.Text(x + 6.5, y - 6.0, text, style=ft.TextStyle(size=11.5, weight=ft.FontWeight.W_700, color="#99000000"))
    label = cv.Text(x + 6, y - 7.0, text, style=ft.TextStyle(size=11.5, weight=ft.FontWeight.W_700, color="#ffffff"))
    return [dot, shadow, label]


class _CountryView:
    """Shared state: exposure, hover tooltip and the unavailable badge."""

    def __init__(
        self,
        exposure_by_country: Mapping[str, float | None] | None,
        unavailable_reason: str | None,
        return_by_country: Mapping[str, float | None] | None,
    ) -> None:
        self.exposure = clean_exposure(exposure_by_country)
        self.returns = {str(k).upper(): v for k, v in (return_by_country or {}).items()}
        reason = (unavailable_reason or "").strip()
        if not reason and not self.exposure:
            reason = "No country exposure available"
        self.unavailable_reason = reason
        self.hovered: str | None = None
        self.tooltip_text = ft.Text("", size=12, color="#ffffff", weight=ft.FontWeight.W_600)
        self.tooltip = ft.Container(
            self.tooltip_text,
            visible=False,
            padding=ft.Padding(left=10, right=10, top=5, bottom=5),
            border_radius=10,
            bgcolor="#e6081226",
            ignore_interactions=True,
        )
        self.badge = ft.Container(
            ft.Text(f"Unavailable · {self.unavailable_reason}", size=12.5, color="#d3dcf2"),
            visible=bool(self.unavailable_reason),
            padding=ft.Padding(left=12, right=12, top=6, bottom=6),
            border_radius=12,
            bgcolor="#b30a1630",
            ignore_interactions=True,
        )

    def top_labels(self, count: int = 3) -> list[tuple[Country, float]]:
        ranked = sorted(self.exposure.items(), key=lambda item: item[1], reverse=True)[:count]
        by_code = {country.iso3: country for country in load_countries()}
        return [(by_code[code], value) for code, value in ranked if code in by_code and value > 0]

    def describe(self, country: Country) -> str:
        parts = [_SHORT_NAMES.get(country.iso3, country.name), _format_pct(self.exposure[country.iso3])]
        if self.returns:
            value = self.returns.get(country.iso3)
            parts.append("—" if value is None or not math.isfinite(float(value)) else f"{float(value):+.1f}%")
        return " · ".join(parts)

    def semantics(self) -> str:
        if self.unavailable_reason:
            return f"World exposure unavailable: {self.unavailable_reason}"
        ranked = sorted(self.exposure.items(), key=lambda item: item[1], reverse=True)[:5]
        names = {country.iso3: country.name for country in load_countries()}
        top = ", ".join(f"{names.get(code, code)} {_format_pct(value)}" for code, value in ranked)
        return f"World exposure by country. Top countries: {top}."

    def _show_tooltip(self, country: Country | None, x: float, y: float, width: float) -> bool:
        code = country.iso3 if country else None
        if code == self.hovered:
            return False
        self.hovered = code
        if country is None:
            self.tooltip.visible = False
        else:
            self.tooltip_text.value = self.describe(country)
            self.tooltip.visible = True
            self.tooltip.left = max(4.0, min(x + 14, width - 200))
            self.tooltip.top = max(4.0, y - 34)
        return True


class Globe(_CountryView):
    """Draggable orthographic globe. ``.control`` is the Flet control to place in a card.

    ``exposure_by_country`` maps ISO3 (Natural Earth ``ADM0_A3``) to percent of portfolio.
    ``asset_base`` is an optional URL prefix (relative to the Flet ``assets_dir``) used instead
    of absolute file paths, e.g. ``"globe"`` when ``assets_dir`` is ``app/assets``.
    """

    def __init__(
        self,
        exposure_by_country: Mapping[str, float | None] | None = None,
        unavailable_reason: str | None = None,
        size: float = 400,
        *,
        return_by_country: Mapping[str, float | None] | None = None,
        centre_lon: float = DEFAULT_CENTRE_LON,
        asset_base: str | None = None,
        on_rotate: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(exposure_by_country, unavailable_reason, return_by_country)
        self.size = float(size)
        self.diameter = self.size * DISC_FRACTION
        self.radius = self.diameter / 2
        self.offset = (self.size - self.diameter) / 2
        self.lon = float(centre_lon)
        self.index = centre_index(self.lon)
        self.asset_base = asset_base
        self._on_rotate = on_rotate
        self._spin_task: object | None = None

        self.atmosphere = cv.Canvas(self._atmosphere_shapes(), width=self.size, height=self.size)
        self.image = ft.Image(
            src=self._src(self.index),
            width=self.diameter,
            height=self.diameter,
            left=self.offset,
            top=self.offset,
            fit=ft.BoxFit.CONTAIN,
            filter_quality=ft.FilterQuality.HIGH,
            gapless_playback=True,
            semantics_label="Earth",
            exclude_from_semantics=True,
        )
        self.overlay = cv.Canvas(self._overlay_shapes(), width=self.size, height=self.size)
        self.badge.left = max(8.0, self.size / 2 - 130)
        self.badge.top = self.size / 2 - 16
        stack = ft.Stack(
            [self.atmosphere, self.image, self.overlay, self.badge, self.tooltip],
            width=self.size,
            height=self.size,
        )
        self.detector = ft.GestureDetector(
            content=stack,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
            on_hover=self._on_hover,
            on_exit=self._on_exit,
            hover_interval=40,
            mouse_cursor=ft.MouseCursor.GRAB,
        )
        self.control: ft.Control = ft.Semantics(label=self.semantics(), content=self.detector)

    # -- drawing
    def _src(self, index: int) -> str:
        if self.asset_base:
            return f"{self.asset_base.strip('/')}/{globe_asset_path(index).name}"
        return str(globe_asset_path(index))

    def _atmosphere_shapes(self) -> list[cv.Shape]:
        centre = self.size / 2
        glow = ft.PaintRadialGradient(
            center=ft.Offset(centre, centre),
            radius=centre,
            colors=[_hex(127, 184, 255, 0.0), _hex(127, 184, 255, 0.0), _hex(127, 184, 255, 0.42), _hex(127, 184, 255, 0.0)],
            color_stops=[0.0, DISC_FRACTION - 0.01, DISC_FRACTION + 0.006, 1.0],
        )
        return [
            cv.Circle(centre, centre, centre, ft.Paint(gradient=glow, style=_FILL)),
            cv.Circle(centre, centre, self.radius + 1, ft.Paint(color=_hex(127, 184, 255, 0.35), style=_STROKE, stroke_width=1.5)),
        ]

    def _screen(self, lon: np.ndarray, lat: np.ndarray, centre_lon: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x, y, z = ortho_project(lon, lat, centre_lon)
        return self.size / 2 + x * self.radius, self.size / 2 - y * self.radius, z

    def _ring_points(self, ring: np.ndarray, centre_lon: float) -> np.ndarray | None:
        """Project a ring; hidden points are clamped to the limb so the fill stays closed."""
        x, y, z = ortho_project(ring[:, 0], ring[:, 1], centre_lon)
        if not np.any(z >= 0):
            return None
        rho = np.hypot(x, y)
        scale = np.where(z < 0, 1.0 / np.maximum(rho, 1e-9), 1.0)
        centre = self.size / 2
        return np.column_stack([centre + x * scale * self.radius, centre - y * scale * self.radius])

    def _overlay_shapes(self) -> list[cv.Shape]:
        centre_lon = float(centre_longitude(self.index))
        fills: list[cv.Shape] = []
        strokes: list[cv.Shape] = []
        raised: list[cv.Shape] = []
        for country in load_countries():
            weight = self.exposure.get(country.iso3)
            if weight is None:
                continue
            for ring in country.rings:
                points = self._ring_points(ring, centre_lon)
                if points is None:
                    continue
                raised.append(_path(points + np.array([1.2, 2.0]), ft.Paint(color="#4d000000", style=_FILL)))
                fills.append(_path(points, ft.Paint(color=exposure_fill(weight), style=_FILL)))
                strokes.append(_path(points, ft.Paint(color="#e6ffffff", style=_STROKE, stroke_width=1.0, stroke_join=ft.StrokeJoin.ROUND)))
        labels: list[cv.Shape] = []
        for country, value in self.top_labels():
            px, py, pz = self._screen(np.array([country.anchor[0]]), np.array([country.anchor[1]]), centre_lon)
            if pz[0] > 0.12:
                short = _SHORT_NAMES.get(country.iso3, country.name)
                labels.extend(_label_shapes(f"{short} {_format_pct(value)}", float(px[0]), float(py[0])))
        return [*raised, *fills, *strokes, *labels]

    # -- interaction
    def rotate_to(self, lon: float) -> None:
        """Set the (continuous) centre longitude; re-renders only when the 10 degree image changes."""
        self.lon = (lon + 180.0) % 360.0 - 180.0
        index = centre_index(self.lon)
        if index != self.index:
            self.index = index
            self.image.src = self._src(index)
            self.overlay.shapes = self._overlay_shapes()
            self.hovered = None
            self.tooltip.visible = False
        if self._on_rotate is not None:
            self._on_rotate(self.lon)

    def _refresh(self) -> None:
        try:
            self.control.update()
        except Exception:  # not mounted yet (tests, first build)
            pass

    def _on_pan_update(self, event: ft.DragUpdateEvent) -> None:
        self._spin_task = None
        dx = event.local_delta.x if event.local_delta is not None else 0.0
        before = self.index
        self.rotate_to(self.lon - math.degrees(dx / self.radius))
        if self.index != before:
            self._refresh()

    def _on_pan_end(self, event: ft.DragEndEvent) -> None:
        velocity = float(event.velocity.x) if event.velocity is not None else 0.0
        if abs(velocity) < 80:
            return
        page = getattr(self.control, "page", None)
        if page is None or not hasattr(page, "run_task"):
            return
        token = object()
        self._spin_task = token

        async def spin() -> None:
            speed = max(-240.0, min(240.0, -math.degrees(velocity / self.radius) * 0.5))  # degrees per second
            while self._spin_task is token and abs(speed) > 6:
                await asyncio.sleep(0.04)
                before = self.index
                self.rotate_to(self.lon + speed * 0.04)
                if self.index != before:
                    self._refresh()
                speed *= 0.90

        try:
            page.run_task(spin)
        except Exception:
            self._spin_task = None

    def hit_test(self, x: float, y: float) -> Country | None:
        """Country with exposure under canvas point (x, y), or None."""
        found = ortho_inverse((x - self.size / 2) / self.radius, (self.size / 2 - y) / self.radius, float(centre_longitude(self.index)))
        return country_at(found[0], found[1], self.exposure) if found else None

    def _on_hover(self, event: ft.PointerEvent) -> None:
        position = event.local_position
        if self._show_tooltip(self.hit_test(position.x, position.y), position.x, position.y, self.size):
            self._refresh()

    def _on_exit(self, event: object) -> None:
        if self._show_tooltip(None, 0, 0, self.size):
            self._refresh()


class WorldMap(_CountryView):
    """Flat equirectangular map of the same polygons and colouring."""

    LAT_TOP = 84.0
    LAT_BOTTOM = -58.0

    def __init__(
        self,
        exposure_by_country: Mapping[str, float | None] | None = None,
        unavailable_reason: str | None = None,
        width: float = 640,
        height: float | None = None,
        *,
        return_by_country: Mapping[str, float | None] | None = None,
    ) -> None:
        super().__init__(exposure_by_country, unavailable_reason, return_by_country)
        self.width = float(width)
        span = self.LAT_TOP - self.LAT_BOTTOM
        self.height = float(height) if height else self.width * span / 360.0
        self.canvas = cv.Canvas(self._shapes(), width=self.width, height=self.height)
        self.badge.left = max(8.0, self.width / 2 - 130)
        self.badge.top = self.height / 2 - 16
        stack = ft.Stack([self.canvas, self.badge, self.tooltip], width=self.width, height=self.height)
        detector = ft.GestureDetector(content=stack, on_hover=self._on_hover, on_exit=self._on_exit, hover_interval=40)
        self.control: ft.Control = ft.Semantics(label=self.semantics(), content=detector)

    def project(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        x = (np.asarray(lon) + 180.0) / 360.0 * self.width
        y = (self.LAT_TOP - np.asarray(lat)) / (self.LAT_TOP - self.LAT_BOTTOM) * self.height
        return np.column_stack([x, y])

    def _shapes(self) -> list[cv.Shape]:
        base_fill = ft.Paint(color="#14ffffff", style=_FILL)
        base_stroke = ft.Paint(color="#33ffffff", style=_STROKE, stroke_width=0.6)
        land: list[cv.Shape] = []
        exposed: list[cv.Shape] = []
        for country in load_countries():
            weight = self.exposure.get(country.iso3)
            for ring in country.rings:
                points = self.project(ring[:, 0], ring[:, 1])
                if weight is None:
                    land.extend([_path(points, base_fill), _path(points, base_stroke)])
                else:
                    exposed.extend(
                        [
                            _path(points, ft.Paint(color=exposure_fill(weight), style=_FILL)),
                            _path(points, ft.Paint(color="#e6ffffff", style=_STROKE, stroke_width=1.0, stroke_join=ft.StrokeJoin.ROUND)),
                        ]
                    )
        labels: list[cv.Shape] = []
        for country, value in self.top_labels():
            px, py = self.project(np.array([country.anchor[0]]), np.array([country.anchor[1]]))[0]
            short = _SHORT_NAMES.get(country.iso3, country.name)
            labels.extend(_label_shapes(f"{short} {_format_pct(value)}", float(px), float(py)))
        return [*land, *exposed, *labels]

    def hit_test(self, x: float, y: float) -> Country | None:
        lon = x / self.width * 360.0 - 180.0
        lat = self.LAT_TOP - y / self.height * (self.LAT_TOP - self.LAT_BOTTOM)
        return country_at(lon, lat, self.exposure)

    def _on_hover(self, event: ft.PointerEvent) -> None:
        position = event.local_position
        if self._show_tooltip(self.hit_test(position.x, position.y), position.x, position.y, self.width):
            try:
                self.control.update()
            except Exception:
                pass

    def _on_exit(self, event: object) -> None:
        if self._show_tooltip(None, 0, 0, self.width):
            try:
                self.control.update()
            except Exception:
                pass
