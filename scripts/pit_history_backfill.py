"""Point-in-time fundamentals history backfill for the historical replay (reads only; no provider writes).

Routes (each reuses its canonical path, nothing is re-implemented here):

* ``sec``   - SEC EDGAR companyfacts via ``scripts/refresh_stock_fundamentals.py --sources sec_edgar``
              (as originally filed, known_at = filing date). Run that script; this module does not duplicate it.
* ``esef``  - every filings.xbrl.org filing per LEI, known_at = the registry ``date_added`` (never the import time):
              * Norwegian equity certificates: ``scripts/sparebank_refresh.py --history``
              * every other issuer: ``application.filing_ingestion_workflows.import_esef_package(known_at=...)``
              into ``data/clean/statement_facts.parquet`` / ``filings_statements.parquet``.

An issuer whose LEI cannot be resolved from a verified ISIN (GLEIF, exactly one record) or that has no filing is
recorded with its reason and skipped: nothing is guessed, backdated or zero-filled. A source is abandoned after
``MAX_CONSECUTIVE_ERRORS`` consecutive errors and that is recorded.

Usage: python scripts/pit_history_backfill.py --root PATH --universe-csv audit.csv [--ids A,B] [--manifest-only]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))

MAX_CONSECUTIVE_ERRORS = 5
REQUEST_PAUSE_SECONDS = 1.0
EXCLUDED_SET = "EXCLUDED"
NON_FILER_TYPES = frozenset({"etf"})  # funds do not file ESEF annual reports; their evidence is a separate snapshot class
NORWEGIAN_EC_TYPE = "equity_certificate"


def universe_targets(audit_csv: Path) -> list[dict[str, str]]:
    """Replay-universe rows that can file statements: not EXCLUDED and not a fund."""

    with Path(audit_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row for row in rows
        if str(row.get("replay_set") or "").strip() != EXCLUDED_SET and str(row.get("type") or "").strip() not in NON_FILER_TYPES
    ]


def resolve_leis(
    targets: Sequence[Mapping[str, str]],
    records: Mapping[str, Mapping[str, object]],
    lookup: Callable[[str], tuple[str, Mapping[str, object], str]],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, dict[str, str]]:
    """instrument id -> {"lei", "source"} or {"lei": "", "reason"}; the ISIN must be verified, one GLEIF record exact."""

    from etf_cockpit.data.universe_store import is_valid_isin

    out: dict[str, dict[str, str]] = {}
    consecutive = 0
    for row in targets:
        instrument_id = str(row["id"])
        record = records.get(instrument_id) or {}
        configured = str(record.get("lei") or "").strip().upper()
        isin = str(record.get("isin") or "").strip().upper()
        if configured:
            out[instrument_id] = {"lei": configured, "source": "configured universe record"}
            continue
        if not is_valid_isin(isin):
            out[instrument_id] = {"lei": "", "reason": f"lei_unresolved: universe ISIN is not verified ({isin or 'missing'})"}
            continue
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            out[instrument_id] = {"lei": "", "reason": "lei_unresolved: GLEIF abandoned after repeated errors"}
            continue
        try:
            lei, _entity, url = lookup(isin)
            consecutive = 0
            out[instrument_id] = {"lei": str(lei).upper(), "source": f"GLEIF lei-records filter[isin]={isin}", "source_url": url}
        except Exception as exc:  # recorded per issuer; the others continue
            consecutive += 1
            out[instrument_id] = {"lei": "", "reason": f"lei_unresolved: {type(exc).__name__}: {str(exc)[:120]}"}
        sleep(REQUEST_PAUSE_SECONDS)
    return out


def build_manifest(
    leis: Mapping[str, Mapping[str, str]],
    list_filings: Callable[[str], Sequence[Mapping[str, object]]],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, dict[str, object]]:
    """instrument id -> every registry filing of its LEI (no filtering by year: the caller decides)."""

    manifest: dict[str, dict[str, object]] = {}
    consecutive = 0
    for instrument_id, resolved in leis.items():
        lei = str(resolved.get("lei") or "")
        if not lei:
            manifest[instrument_id] = {"lei": "", "filings": [], "reason": resolved.get("reason", "lei_unresolved")}
            continue
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            manifest[instrument_id] = {"lei": lei, "filings": [], "reason": "registry_abandoned_after_repeated_errors"}
            continue
        try:
            filings = [dict(item) for item in list_filings(lei)]
            consecutive = 0
            manifest[instrument_id] = {
                "lei": lei,
                "filings": filings,
                "reason": "" if filings else "no_filing_in_filings_xbrl_org_registry",
            }
        except Exception as exc:
            consecutive += 1
            manifest[instrument_id] = {"lei": lei, "filings": [], "reason": f"registry_error: {type(exc).__name__}: {str(exc)[:120]}"}
        sleep(REQUEST_PAUSE_SECONDS)
    return manifest


class _Session:
    """The two attributes ``import_esef_package`` touches on its session; no UI state is needed."""

    last_message = ""

    def _record_activity_output(self, step: str, path: object) -> None:
        del step, path


def import_generic_history(
    instrument_id: str,
    lei: str,
    filings: Sequence[Mapping[str, object]],
    download: Callable[[Mapping[str, object]], object],
    log_path: Path,
    *,
    importer: Callable[..., str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, object]]:
    """Import every filing of one non-Norwegian-certificate issuer, oldest ``date_added`` first.

    known_at is the filing's ``date_added``; a filing without one, without a package or for another LEI is skipped
    with its reason. Filings already logged as imported are not parsed again.
    """

    if importer is None:
        from etf_cockpit.application.filing_ingestion_workflows import import_esef_package as importer  # type: ignore[assignment]

    done = _imported_ids(log_path)
    ordered = sorted(
        filings,
        key=lambda row: (str(row.get("date_added") or ""), str(row.get("period_end") or ""), str(row.get("id") or "")),
    )
    outcomes: list[dict[str, object]] = []
    consecutive = 0
    for filing in ordered:
        outcome: dict[str, object] = {
            "instrument_id": instrument_id,
            "lei": lei,
            "filing_id": str(filing.get("id") or ""),
            "fxo_id": str(filing.get("fxo_id") or ""),
            "period_end": str(filing.get("period_end") or ""),
            "date_added": str(filing.get("date_added") or ""),
        }
        entity = str(filing.get("entity_lei") or lei).strip().upper()
        if entity != lei:
            outcome.update(status="skipped", reason="filing belongs to another LEI")
        elif not outcome["date_added"] or not outcome["period_end"] or not str(filing.get("package_url") or ""):
            outcome.update(status="skipped", reason="registry record lacks date_added, period_end or package_url")
        elif (instrument_id, outcome["filing_id"]) in done:
            outcome.update(status="already_imported")
        elif consecutive >= MAX_CONSECUTIVE_ERRORS:
            outcome.update(status="skipped", reason="source abandoned after repeated errors")
        else:
            try:
                package = download(filing)
                message = importer(
                    _Session(),
                    Path(package.path),  # type: ignore[attr-defined]
                    instrument_id=instrument_id,
                    known_at=str(outcome["date_added"]).replace(" ", "T"),
                )
                if str(message).startswith("ESEF import complete"):
                    consecutive = 0
                    outcome.update(status="imported", sha256=package.sha256, message=str(message)[:200])  # type: ignore[attr-defined]
                else:
                    outcome.update(status="failed", reason=str(message)[:300])
            except Exception as exc:
                consecutive += 1
                outcome.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:200]}")
            sleep(REQUEST_PAUSE_SECONDS)
        _append_log(log_path, outcome)
        outcomes.append(outcome)
    return outcomes


def _imported_ids(log_path: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not log_path.is_file():
        return done
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") in {"imported", "already_imported"}:
            done.add((str(row.get("instrument_id")), str(row.get("filing_id"))))
    return done


def _append_log(log_path: Path, row: Mapping[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def apply_isin_overrides(
    records: Mapping[str, Mapping[str, object]], overrides: Mapping[str, Mapping[str, object]]
) -> dict[str, dict[str, object]]:
    """Sandbox-only ISINs (``scripts/pit_verify_isins.py``) fill a missing or unverified store ISIN; a valid store ISIN is never replaced."""

    from etf_cockpit.data.universe_store import is_valid_isin

    out = {key: dict(value) for key, value in records.items()}
    for instrument_id, override in overrides.items():
        record = out.get(instrument_id)
        if record is None or is_valid_isin(str(record.get("isin") or "").strip().upper()):
            continue
        if is_valid_isin(str(override.get("isin") or "").strip().upper()):
            record["isin"] = str(override["isin"]).strip().upper()
    return out


def check_override_leis(
    leis: dict[str, dict[str, str]], overrides: Mapping[str, Mapping[str, object]], records: Mapping[str, Mapping[str, object]]
) -> None:
    """The LEI GLEIF returns for an overridden ISIN must equal the LEI the verification recorded; otherwise nothing is imported."""

    for instrument_id, override in overrides.items():
        resolved = leis.get(instrument_id)
        if resolved is None or str(records.get(instrument_id, {}).get("isin") or "").strip().upper() == "" or not resolved.get("lei"):
            continue
        if resolved["lei"] != str(override.get("lei") or "").upper():
            leis[instrument_id] = {"lei": "", "reason": f"lei_unresolved: GLEIF LEI {resolved['lei']} differs from the verified override LEI"}
        else:
            resolved["source"] = f"{resolved.get('source', '')}; sandbox ISIN override verified {override.get('verified_at')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=os.environ.get("ETF_COCKPIT_ROOT"), required=os.environ.get("ETF_COCKPIT_ROOT") is None)
    parser.add_argument("--universe-csv", type=Path, required=True)
    parser.add_argument("--ids", default="", help="comma separated instrument ids (default: every target)")
    parser.add_argument("--manifest-only", action="store_true", help="resolve LEIs and list registry filings; import nothing")
    parser.add_argument("--isin-overrides", type=Path, help="sandbox-only verified ISINs (data/pit_history/universe_isin_overrides.json); the universe store is not edited")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    os.environ["ETF_COCKPIT_ROOT"] = str(root)

    from scripts.sparebank_refresh import OfficialFilingClient

    store = json.loads((root / "configs" / "universe_store.json").read_text(encoding="utf-8"))
    records = {str(item["instrument_id"]): item for item in store["records"]}
    wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
    targets = [row for row in universe_targets(args.universe_csv) if not wanted or row["id"] in wanted]
    history_dir = root / "data" / "pit_history"
    client = OfficialFilingClient(root / "data" / "raw" / "esef")

    overrides = json.loads(args.isin_overrides.read_text(encoding="utf-8")) if args.isin_overrides and args.isin_overrides.is_file() else {}
    records = apply_isin_overrides(records, overrides)
    leis = resolve_leis(targets, records, client.lookup_lei_by_isin)
    check_override_leis(leis, overrides, records)
    manifest = build_manifest(leis, client.filings_for_lei)
    history_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = history_dir / "esef_manifest.json"
    if wanted and manifest_path.is_file():  # a partial run refreshes its issuers only, never drops the others
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        leis = {**previous.get("leis", {}), **leis}
        manifest = {**previous.get("manifest", {}), **manifest}
    manifest_path.write_text(json.dumps({"leis": leis, "manifest": manifest}, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(f"manifest: {len(manifest)} issuers, {sum(len(v['filings']) for v in manifest.values())} registry filings")
    if args.manifest_only:
        return 0
    for row in targets:
        instrument_id = row["id"]
        entry = manifest[instrument_id]
        if row["type"] == NORWEGIAN_EC_TYPE or not entry["filings"]:
            continue  # certificates go through scripts/sparebank_refresh.py --history
        outcomes = import_generic_history(
            instrument_id, str(entry["lei"]), entry["filings"], client.download, history_dir / "esef_generic_import_log.jsonl"
        )
        print(instrument_id, {status: sum(1 for item in outcomes if item["status"] == status) for status in {i["status"] for i in outcomes}})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
