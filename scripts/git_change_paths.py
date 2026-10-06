"""Read exact Git change boundaries, including removals and both rename ends.

No network or mutation. NUL-delimited names avoid Git quoting/line splitting;
rename detection is disabled because risk belongs to the old path as well as
its replacement. Ambiguous cross-platform names fail closed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _names(root: Path, *arguments: str) -> list[str]:
    payload = subprocess.check_output(["git", *arguments], cwd=root)
    if payload and not payload.endswith(b"\0"):
        raise ValueError("Git path stream is not NUL terminated")
    names = [name.decode("utf-8") for name in payload.split(b"\0") if name]
    for name in names:
        if (name != name.strip() or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/"))):
            raise ValueError(f"Ambiguous cross-platform Git path: {name!r}")
    return names


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    """All endpoint changes; a rename is deliberately a removal plus addition."""
    return sorted(set(_names(root, "diff", "--name-only", "--no-renames", "-z", base, head, "--")))


def working_paths(root: Path) -> list[str]:
    """Union of staged, unstaged and non-ignored untracked names, without writes."""
    names = _names(root, "diff", "--name-only", "--no-renames", "-z", "--")
    names += _names(root, "diff", "--cached", "--name-only", "--no-renames", "-z", "--")
    names += _names(root, "ls-files", "--others", "--exclude-standard", "-z", "--")
    return sorted(set(names))
