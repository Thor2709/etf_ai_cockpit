"""Immutable file-backed store for validated ``sparebank-intelligence-result.v1`` runs.

Layout under ``root``::

    runs/<run_id>/envelope.json      original accepted bytes (never rewritten)
    runs/<run_id>/projection.json    validated projection
    runs/<run_id>/meta.json          hashes, import metadata, schema/model/code versions
    attachments/<sha256>             content-addressed, immutable
    quarantine/<raw_sha256>-<n>/     rejected bytes + machine-readable reasons

A run directory is built in ``staging/`` and published with one ``os.rename``,
so a reader never sees a partial run and a concurrent identical import loses the
rename race harmlessly.  A different payload for an existing run ID is a fatal
conflict: both histories are kept (the loser in quarantine), nothing is overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from etf_cockpit.data.sparebank_intelligence import (
    IntelligenceIssue,
    canonical_json,
    parse_envelope_bytes,
    validate_attachment_bytes,
)

ATTACHMENT_DIR = "attachments"


@dataclass(frozen=True)
class RunImportOutcome:
    status: str  # IMPORTED | IDEMPOTENT | QUARANTINED | CONFLICT
    run_id: str | None
    raw_sha256: str
    reasons: tuple[str, ...] = ()
    quarantine_path: Path | None = None


@dataclass(frozen=True)
class DirectoryImportReport:
    outcomes: tuple[RunImportOutcome, ...]

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


class SparebankRunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ import

    def import_bytes(
        self,
        raw: bytes,
        *,
        source: str,
        attachments: dict[str, bytes] | None = None,
        now: datetime | None = None,
    ) -> RunImportOutcome:
        """Validate then publish ``raw``; nothing becomes readable unless every check passes."""

        parsed = parse_envelope_bytes(raw, now=now)
        issues: tuple[IntelligenceIssue, ...] = parsed.issues
        if parsed.ok and parsed.projection is not None:
            by_id = {row["attachment_id"]: row for row in parsed.projection["attachments"]}
            supplied = {key: value for key, value in (attachments or {}).items() if key in by_id}
            issues = validate_attachment_bytes(parsed.projection, supplied)
        if issues or not parsed.ok or parsed.projection is None:
            return self._quarantine(raw, parsed.raw_sha256, parsed.run_id, issues, source)

        run_id = parsed.projection["run_id"]
        target = self._run_dir(run_id)
        existing = self._existing_sha(target)
        if existing is not None:
            return self._resolve_duplicate(raw, parsed.raw_sha256, run_id, existing, source)

        self._store_attachments(parsed.projection, attachments or {})
        staging = self.root / "staging" / uuid.uuid4().hex
        staging.mkdir(parents=True)
        try:
            (staging / "envelope.json").write_bytes(raw)
            (staging / "projection.json").write_bytes(canonical_json(parsed.projection))
            meta = {
                "run_id": run_id,
                "raw_sha256": parsed.raw_sha256,
                "content_hash": parsed.content_hash,
                "source": source,
                "imported_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                "schema": parsed.projection["schema"],
                "model_version": parsed.projection["model_version"],
                "science_version": parsed.projection["science_version"],
                "code_revision": parsed.projection["code_revision"],
                "as_of": parsed.projection["as_of"],
                "known_at_cutoff": parsed.projection["known_at_cutoff"],
                "status": parsed.projection["status"],
                "quarantine_reason": None,
                "execution_allowed": False,
            }
            (staging / "meta.json").write_bytes(canonical_json(meta))
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(staging, target)
            except OSError:
                # Lost a publication race (or the target appeared): re-read what won.
                winner = self._existing_sha(target)
                if winner is None:
                    raise
                return self._resolve_duplicate(raw, parsed.raw_sha256, run_id, winner, source)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return RunImportOutcome("IMPORTED", run_id, parsed.raw_sha256)

    def import_directory(self, import_dir: Path, *, now: datetime | None = None) -> DirectoryImportReport:
        """Import every complete ``*.json`` envelope; temp/partial names are ignored."""

        directory = Path(import_dir)
        if not directory.is_dir():
            return DirectoryImportReport(())
        outcomes = []
        for path in sorted(directory.glob("*.json")):
            if path.name.startswith(".") or not path.is_file():
                continue
            raw = path.read_bytes()
            outcomes.append(
                self.import_bytes(raw, source=f"file:{path.name}", attachments=_sidecar_attachments(directory, raw), now=now)
            )
        return DirectoryImportReport(tuple(outcomes))

    # -------------------------------------------------------------------- read

    def run_ids(self) -> tuple[str, ...]:
        runs = self.root / "runs"
        if not runs.is_dir():
            return ()
        return tuple(sorted(item.name for item in runs.iterdir() if item.is_dir()))

    def get_run(self, run_id: str) -> dict | None:
        """Stored projection, or ``None`` (unavailable) when absent or the stored bytes fail verification."""

        directory = self._run_dir(run_id)
        try:
            raw = (directory / "envelope.json").read_bytes()
            meta = json.loads((directory / "meta.json").read_bytes())
            if hashlib.sha256(raw).hexdigest() != meta["raw_sha256"]:
                return None
            return json.loads((directory / "projection.json").read_bytes())
        except (OSError, ValueError, KeyError):
            return None

    def latest_run(self) -> dict | None:
        """Newest valid run by (known_at_cutoff, run_id); ``None`` when nothing verifiable exists."""

        candidates = [run for run in (self.get_run(run_id) for run_id in self.run_ids()) if run is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda run: (run["known_at_cutoff"], run["run_id"]))

    def quarantine_reasons(self) -> tuple[dict, ...]:
        folder = self.root / "quarantine"
        if not folder.is_dir():
            return ()
        rows = []
        for item in sorted(folder.iterdir()):
            try:
                rows.append(json.loads((item / "reason.json").read_bytes()))
            except (OSError, ValueError):
                continue
        return tuple(rows)

    def attachment_bytes(self, sha256: str) -> bytes | None:
        try:
            blob = (self.root / ATTACHMENT_DIR / sha256).read_bytes()
        except OSError:
            return None
        return blob if hashlib.sha256(blob).hexdigest() == sha256 else None

    # ---------------------------------------------------------------- internals

    def _run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def _existing_sha(self, directory: Path) -> str | None:
        if not directory.is_dir():
            return None
        try:
            return hashlib.sha256((directory / "envelope.json").read_bytes()).hexdigest()
        except OSError:
            return "unreadable"

    def _resolve_duplicate(self, raw: bytes, raw_sha: str, run_id: str, existing_sha: str, source: str) -> RunImportOutcome:
        if existing_sha == raw_sha:
            return RunImportOutcome("IDEMPOTENT", run_id, raw_sha)
        issue = IntelligenceIssue("run_id_conflict", "$.run_id")
        outcome = self._quarantine(raw, raw_sha, run_id, (issue,), source)
        return RunImportOutcome("CONFLICT", run_id, raw_sha, ("run_id_conflict",), outcome.quarantine_path)

    def _store_attachments(self, projection: dict, supplied: dict[str, bytes]) -> None:
        folder = self.root / ATTACHMENT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        for row in projection["attachments"]:
            blob = supplied.get(row["attachment_id"])
            if blob is None:
                continue
            destination = folder / row["sha256"]
            if destination.exists():
                continue
            temp = folder / f".{row['sha256']}.{uuid.uuid4().hex}.tmp"
            temp.write_bytes(blob)
            try:
                os.replace(temp, destination)
            except OSError:
                # A concurrent importer published the same content-addressed file first.
                deadline = time.monotonic() + 5.0
                while self.attachment_bytes(row["sha256"]) is None:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.02)
            finally:
                temp.unlink(missing_ok=True)

    def _quarantine(
        self, raw: bytes, raw_sha: str, run_id: str | None, issues: tuple[IntelligenceIssue, ...], source: str
    ) -> RunImportOutcome:
        folder = self.root / "quarantine"
        folder.mkdir(parents=True, exist_ok=True)
        index = 0
        while True:
            target = folder / f"{raw_sha[:16]}-{index}"
            try:
                target.mkdir()
                break
            except FileExistsError:
                index += 1
        (target / "raw.bin").write_bytes(raw)
        reasons = [issue.as_dict() for issue in issues]
        (target / "reason.json").write_bytes(
            canonical_json({"run_id": run_id, "raw_sha256": raw_sha, "source": source, "reasons": reasons, "execution_allowed": False})
        )
        codes = tuple(sorted({issue.code for issue in issues}))
        return RunImportOutcome("QUARANTINED", run_id, raw_sha, codes, target)


def _sidecar_attachments(directory: Path, raw: bytes) -> dict[str, bytes]:
    """Attachments sit in ``<import_dir>/attachments/<attachment_id>``; ids are validated by name."""

    try:
        manifest = json.loads(raw).get("attachments", [])
    except (ValueError, AttributeError):
        return {}
    found: dict[str, bytes] = {}
    if not isinstance(manifest, list):
        return found
    for row in manifest:
        attachment_id = row.get("attachment_id") if isinstance(row, dict) else None
        if not isinstance(attachment_id, str) or not attachment_id or Path(attachment_id).name != attachment_id:
            continue
        candidate = directory / "attachments" / attachment_id
        if candidate.is_file():
            found[attachment_id] = candidate.read_bytes()
    return found


__all__ = ["DirectoryImportReport", "RunImportOutcome", "SparebankRunStore"]
