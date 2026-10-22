"""The Arelle validation child may decode only the image formats ESEF permits."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROBE = """
import io
from PIL import Image
from etf_cockpit.parsers.esef_ixbrl import _restrict_image_decoders

def encoded(fmt):
    buffer = io.BytesIO()
    Image.new("L", (2, 2)).save(buffer, format=fmt)
    return buffer.getvalue()

samples = {fmt: encoded(fmt) for fmt in ("PNG", "GIF", "JPEG", "TIFF", "PPM")}
_restrict_image_decoders()
for fmt, data in samples.items():
    try:
        Image.open(io.BytesIO(data)).load()
        print(fmt, "open")
    except Exception:
        print(fmt, "blocked")
"""


def test_validation_child_blocks_non_esef_image_decoders() -> None:
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")]))}
    result = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True, timeout=60, env=env)
    states = dict(line.split() for line in result.stdout.splitlines())
    assert states == {"PNG": "open", "GIF": "open", "JPEG": "open", "TIFF": "blocked", "PPM": "blocked"}
