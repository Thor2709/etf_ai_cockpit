"""Source installs must not resolve Flet 1.x (the app still uses page.go()/ft.app())."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _flet_specs(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'(?m)^\s*"?(flet(?:-web)?)\s*([<>=!~][^",\s]*(?:,[<>=!~][^",\s]*)*)', text)}


def test_requirements_and_pyproject_bound_flet_below_1_0():
    for name in ("requirements.txt", "pyproject.toml"):
        specs = _flet_specs((ROOT / name).read_text(encoding="utf-8"))
        assert set(specs) == {"flet", "flet-web"}, name
        for package, spec in specs.items():
            assert "<1.0" in spec.split(","), f"{name}: {package}{spec} lacks the <1.0 bound"
