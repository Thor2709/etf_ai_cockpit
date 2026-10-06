"""Compact, agent-oriented digest of pytest JUnit results and release-gate checks.

Reads JUnit XML (and, for a release-gate output directory, its report) and prints what an agent
needs to act, in a few hundred tokens instead of the full log:

* one status line (tests, failures, errors, skips, wall time of the slowest test);
* failed gate checks with their stated reason (e.g. missing locked packages);
* failures grouped by cause: exception, the most informative evidence line, the innermost
  product frame (src/...) and the test frame, and every affected test id.

Read-only and dependency-free.  usage:
    python scripts/failure_digest.py <release-gate-output-dir | junit.xml> [...] [--root .] [--max-groups 20]
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_FRAME = re.compile(r"^((?:src|tests|scripts)[\\/][^\s:]+\.py):(\d+)(?::| )", re.M)
_EXCEPTION = re.compile(r"^E\s+((?:[\w.]+(?:Error|Exception|Expired|Exit)|Failed)\b.*)$", re.M)
_EVIDENCE = re.compile(r"^E\s+(.*(?:Error|error|failed|missing|unavailable|denied|timed out|does not match|not found).*)$", re.M)
_CHECK = re.compile(r"^- ([a-z][a-z0-9_]*): (.+)$", re.M)
_WIDTH = 200


@dataclass
class Failure:
    nodeid: str
    kind: str
    seconds: float
    cause: str
    evidence: str
    product_frame: str
    test_frame: str


@dataclass
class Group:
    cause: str
    evidence: str
    product_frame: str
    test_frame: str
    nodeids: list[str] = field(default_factory=list)


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _WIDTH else text[: _WIDTH - 3] + "..."


def _nodeid(classname: str, name: str, root: Path) -> str:
    parts = classname.split(".")
    for index in range(len(parts), 0, -1):
        candidate = Path(*parts[:index]).with_suffix(".py")
        if (root / candidate).is_file():
            return "::".join([candidate.as_posix(), *parts[index:], name])
    return f"{classname}::{name}"


def _failure(case: ET.Element, element: ET.Element, root: Path) -> Failure:
    text = element.text or ""
    message = (element.get("message") or "").strip().splitlines()
    exceptions = _EXCEPTION.findall(text)
    # The last raised exception is the proximate cause; fall back to the message's first line.
    cause = exceptions[-1] if exceptions else (message[0] if message else element.tag)
    if not exceptions and text.strip():
        cause = text.strip().splitlines()[0]
    evidence = next((line for line in reversed(_EVIDENCE.findall(text)) if _clip(line) != _clip(cause)), "")
    if not evidence and cause.rstrip().endswith(":"):
        # e.g. the checkout write guard: the offending path follows the message line.
        after = text.split(cause.strip(), 1)[-1].strip().splitlines()
        evidence = after[0] if after else ""
    frames = [(path.replace("\\", "/"), line) for path, line in _FRAME.findall(text)]
    product = next((f"{p}:{n}" for p, n in reversed(frames) if p.startswith("src/")), "")
    test = next((f"{p}:{n}" for p, n in reversed(frames) if p.startswith(("tests/", "scripts/"))), "")
    phase = "error" if element.tag == "error" else "failure"
    return Failure(
        nodeid=_nodeid(case.get("classname", ""), case.get("name", ""), root),
        kind=phase,
        seconds=float(case.get("time") or 0.0),
        cause=_clip(cause),
        evidence=_clip(evidence),
        product_frame=product,
        test_frame=test,
    )


def _cause_key(failure: Failure) -> tuple[str, str]:
    # Numbers, hex ids and temp paths vary between otherwise identical causes.
    normalised = re.sub(r"0x[0-9a-f]+|\b\d+(\.\d+)?\b|case_[0-9a-f]+|[\w-]*-[0-9a-f]{8}\b", "#", failure.cause)
    return normalised, failure.product_frame or failure.test_frame.split(":")[0]


def collect(junit_paths: list[Path], root: Path) -> tuple[dict[str, float], list[Failure]]:
    totals = {"tests": 0.0, "failures": 0.0, "errors": 0.0, "skipped": 0.0, "slowest": 0.0}
    failures: list[Failure] = []
    for path in junit_paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            totals["tests"] += 1
            totals["slowest"] = max(totals["slowest"], float(case.get("time") or 0.0))
            if case.find("skipped") is not None:
                totals["skipped"] += 1
            for tag in ("failure", "error"):
                element = case.find(tag)
                if element is not None:
                    totals["failures" if tag == "failure" else "errors"] += 1
                    failures.append(_failure(case, element, root))
    return totals, failures


def group(failures: list[Failure]) -> list[Group]:
    groups: dict[tuple[str, str], Group] = {}
    for failure in failures:
        key = _cause_key(failure)
        if key not in groups:
            groups[key] = Group(failure.cause, failure.evidence, failure.product_frame, failure.test_frame)
        groups[key].nodeids.append(failure.nodeid)
    return sorted(groups.values(), key=lambda item: -len(item.nodeids))


def failed_checks(output_dir: Path) -> list[str]:
    report = output_dir / "release-report.md"
    if not report.is_file():
        return []
    return [f"{name}: {_clip(reason)}" for name, reason in _CHECK.findall(report.read_text(encoding="utf-8"))]


def render(inputs: list[Path], root: Path, max_groups: int = 20) -> str:
    junit_paths: list[Path] = []
    checks: list[str] = []
    for item in inputs:
        if item.is_dir():
            checks.extend(failed_checks(item))
            preferred = [item / "junit-parallel.xml", item / "junit-serial.xml"]
            found = [path for path in preferred if path.is_file()] or sorted(item.glob("junit*.xml"))
            junit_paths.extend(found)
        elif item.is_file():
            junit_paths.append(item)
    totals, failures = collect(junit_paths, root)
    lines = [
        f"TESTS {int(totals['tests'])} | failed {int(totals['failures'])} | errors {int(totals['errors'])} "
        f"| skipped {int(totals['skipped'])} | slowest test {totals['slowest']:.0f}s"
    ]
    lines += [f"CHECK FAILED {check}" for check in checks]
    groups = group(failures)
    for index, entry in enumerate(groups[:max_groups], start=1):
        lines.append(f"[{index}] {len(entry.nodeids)}x {entry.cause}")
        if entry.evidence:
            lines.append(f"    evidence: {entry.evidence}")
        where = " | ".join(part for part in (f"product {entry.product_frame}" if entry.product_frame else "", f"test {entry.test_frame}" if entry.test_frame else "") if part)
        if where:
            lines.append(f"    at: {where}")
        for nodeid in entry.nodeids[:5]:
            lines.append(f"    - {nodeid}")
        if len(entry.nodeids) > 5:
            lines.append(f"    - ... {len(entry.nodeids) - 5} more with the same cause")
    if len(groups) > max_groups:
        lines.append(f"... {len(groups) - max_groups} more distinct causes")
    if not failures and not checks:
        lines.append("OK: no failing tests or checks")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--max-groups", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        print(render(args.inputs, args.root.resolve(), args.max_groups))
    except (OSError, ET.ParseError) as exc:
        print(f"digest unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
