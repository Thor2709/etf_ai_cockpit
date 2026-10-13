"""Build-time pre-render of the Blue Marble orthographic discs (dev/build tool).

Pillow is a development dependency only; the generated PNGs are committed under
``src/etf_cockpit/app/assets/globe`` and the application never imports this module.

Usage:  python scripts/build_globe_assets.py [path/to/bluemarble_4096.jpg]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

LATITUDE_DEG = 28.0
DISC_PX = 640
BRIGHTNESS = 1.25
EMISSIVE = np.array([0.02, 0.05, 0.10], dtype=np.float32)
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "src" / "etf_cockpit" / "app" / "assets" / "globe"
DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1] / "ui_concepts_2026-10-01" / "assets" / "bluemarble_4096.jpg"
)
# Centre longitudes: -175, -165, ... 175 (10 degree steps; includes the default -35).
CENTRES = [-175 + 10 * index for index in range(36)]


def render_disc(texture: np.ndarray, centre_lon_deg: float) -> Image.Image:
    height, width, _ = texture.shape
    half = DISC_PX / 2
    ys, xs = np.mgrid[0:DISC_PX, 0:DISC_PX].astype(np.float32)
    x = (xs + 0.5 - half) / half
    y = (half - (ys + 0.5)) / half
    rho2 = x * x + y * y
    inside = rho2 <= 1.0
    z = np.sqrt(np.clip(1.0 - rho2, 0.0, 1.0))
    phi0 = np.radians(LATITUDE_DEG)
    lam0 = np.radians(centre_lon_deg)
    sin_lat = z * np.sin(phi0) + y * np.cos(phi0)
    lat = np.arcsin(np.clip(sin_lat, -1.0, 1.0))
    lon = lam0 + np.arctan2(x, z * np.cos(phi0) - y * np.sin(phi0))
    u = ((lon + np.pi) / (2 * np.pi)) % 1.0 * width - 0.5
    v = (np.pi / 2 - lat) / np.pi * (height - 1)
    x0 = np.floor(u).astype(np.int64)
    y0 = np.clip(np.floor(v).astype(np.int64), 0, height - 2)
    fx = (u - x0)[..., None]
    fy = (v - y0)[..., None]
    x0 %= width
    x1 = (x0 + 1) % width
    colour = (
        texture[y0, x0] * (1 - fx) * (1 - fy)
        + texture[y0, x1] * fx * (1 - fy)
        + texture[y0 + 1, x0] * (1 - fx) * fy
        + texture[y0 + 1, x1] * fx * fy
    )
    shade = (0.62 + 0.38 * np.power(z, 0.55))[..., None]
    colour = np.clip(colour * BRIGHTNESS * shade + EMISSIVE * 255.0, 0, 255)
    alpha = np.clip((1.0 - np.sqrt(rho2)) * half, 0.0, 1.0) * inside
    rgba = np.dstack([colour, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    image = Image.open(source).convert("RGB")
    image = image.resize((2560, 1280), Image.Resampling.LANCZOS)
    texture = np.asarray(image, dtype=np.float32)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for index, lon in enumerate(CENTRES):
        target = OUTPUT_DIR / f"globe_{index:02d}.png"
        disc = render_disc(texture, lon).quantize(
            256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG
        )
        disc.save(target, optimize=True)
        total += target.stat().st_size
    print(f"wrote {len(CENTRES)} discs to {OUTPUT_DIR} ({total / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
