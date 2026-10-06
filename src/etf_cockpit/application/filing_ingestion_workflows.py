"""SEC companyfacts/submissions, ESEF and OAM ingestion workflows run against a session port (application; ADR-0002)."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from etf_cockpit.core.paths import FILINGS_STATEMENTS_PATH, RAW_DIR, STATEMENT_FACTS_PATH
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.workflow import (
    PublicationScopeFactory,
    WorkflowTransitionError,
    publication_scope,
)
from etf_cockpit.application.sec_bulk_import import (
    BulkImportResult,
    import_sec_companyfacts_bulk as _import_sec_companyfacts_bulk,
)
from etf_cockpit.application.sec_submissions_import import (
    SubmissionsImportResult,
    import_sec_submissions as _import_sec_submissions,
)
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.data.sec_edgar_bulk import SecEdgarBulkUnavailable
from etf_cockpit.data.esef_provider import EsefProviderUnavailable, FilingsXbrlOrgProvider
from etf_cockpit.data.oam_adapters import (
    CompaniesHouseFilingAdapter,
    OAMDiscoveryRequest,
    archive_manual_official_filing,
    import_local_oam_export,
    oam_adapter_for_country,
    write_filing_coverage,
    write_oam_discovery_registry,
)
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package
from etf_cockpit.parsers.sec_facts import (
    parse_companyfacts,
    statement_facts_from_esef,
    write_statement_evidence,
)
from etf_cockpit.application.filing_ingestion import (
    _build_sec_bulk_identity,
    _bulk_result_message,
    _cached_sec_bulk_document,
    _capture_sec_raw_document,
    _esef_source_provenance,
    _load_vendor_statement_claims,
    _normalise_sec_cik,
    _persisted_sec_instruments,
    _preserve_esef_raw,
    _resolve_sec_instrument,
    _sec_bulk_identity_reason,
    _sec_failure_detail,
    _sec_failure_state,
    _sec_identity_matches,
    _validate_sec_bulk_identity,
    _validate_sec_raw_document,
)
from etf_cockpit.application.activity_results import _legacy_unavailable, ActivityUnavailableError


class FilingIngestionSession(Protocol):
    # Undeclared AppState attributes (optional seams read via getattr / set dynamically); typed Any until declared.
    _esef_filings: Any
    _esef_provider: Any
    def _finish_sec_submissions_import(self, result: SubmissionsImportResult) -> str:
        ...
    def _record_activity_output(self, step: str, path: Path | str) -> None:
        ...
    def _record_sec_bulk_outputs(self, result: BulkImportResult) -> None:
        ...
    _sec_bulk_provider: Any
    @contextmanager
    def activity_publication(self, expected_action_id: str | None = None):
        ...
    def import_sec_companyfacts(
        self,
        path: Path,
        *,
        instrument_id: str | None = None,
        document: RawDocument | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> str:
        ...
    last_message: str
    sec_companyfacts_bulk_message: Any
    sec_submissions_result: Any


def import_sec_companyfacts(
    session: FilingIngestionSession,
    path: Path,
    *,
    instrument_id: str | None = None,
    document: RawDocument | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Import an offline SEC companyfacts JSON and publish clean facts/inventory."""

    try:
        source_path = Path(path)
        source_bytes = source_path.read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if document is not None:
            _validate_sec_raw_document(document, source_path, content=source_bytes)
            parsed_path = _capture_sec_raw_document(
                source_path,
                source_bytes,
                source_sha256,
                document=document,
                publish_guard=publish_guard,
            )
        else:
            parsed_path = source_path
        payload = json.loads(source_bytes.decode("utf-8"))
        cik = str(payload.get("cik") or payload.get("cik_str") or "").strip()
        if not cik:
            raise ValueError("SEC companyfacts is missing a CIK")
        normalised_cik = str(cik).strip().upper().removeprefix("CIK").zfill(10)
        if instrument_id is not None:
            requested_instrument_id = str(instrument_id).strip()
            if not requested_instrument_id or not _sec_identity_matches(normalised_cik, requested_instrument_id):
                raise ValueError("supplied instrument ID does not match a unique persisted SEC CIK identity")
            resolved_instrument_id = requested_instrument_id
            resolved_from_identity = True
        else:
            resolved_instrument_id = _resolve_sec_instrument(normalised_cik) or f"sec_unresolved_{normalised_cik}"
            resolved_from_identity = not resolved_instrument_id.startswith("sec_unresolved_")
        identity = CanonicalIdentity(
            resolved_instrument_id,
            f"Unresolved SEC CIK {normalised_cik}" if not resolved_from_identity else "Imported SEC entity",
            None,
            "needs_verification",
            "",
            None,
            None,
            "stock",
            {},
            "manual_review",
            () if resolved_from_identity else ("cik_not_resolved_to_instrument",),
            cik,
        )
        parsed = parse_companyfacts(parsed_path, identity)
        if not parsed.success:
            warning_codes = ", ".join(warning.code for warning in parsed.warnings)
            session.last_message = f"SEC import unavailable: {warning_codes or 'validation failed'}. No data changed."
            return _legacy_unavailable(session, session.last_message)
        if document is not None:
            _validate_sec_raw_document(
                document,
                source_path,
                normalised_cik,
                parsed.source_sha256,
                content=source_bytes,
            )
            source = replace(document, path=parsed_path)
        else:
            source = RawDocument(source_path, source_path.resolve().as_uri(), datetime.now(timezone.utc), parsed.source_sha256, "sec_edgar", "sec_companyfacts", "application/json", 200)
        with publication_scope(publish_guard):
            write_statement_evidence(
                source,
                parsed.records,
                STATEMENT_FACTS_PATH,
                FILINGS_STATEMENTS_PATH,
                instrument_id=identity.instrument_id,
                vendor_records=_load_vendor_statement_claims(identity.instrument_id),
            )
        session._record_activity_output("SEC statement evidence published", STATEMENT_FACTS_PATH)
        review_note = " manual identity review required." if not resolved_from_identity else ""
        session.last_message = f"SEC import complete: {len(parsed.records)} facts, {len(parsed.warnings)} mapping warnings.{review_note}"
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"SEC import unavailable: {type(exc).__name__}. No data changed; scoring and execution were not started."
        return _legacy_unavailable(session, session.last_message, exc)


def fetch_sec_companyfacts(
    session: FilingIngestionSession,
    cik: str,
    *,
    cache_dir: Path | None = None,
    instrument_id: str | None = None,
    user_agent: str | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Use a validated local bulk archive before explicit per-CIK JSON fetch."""

    statement_import_started = False
    try:
        normalised_cik = _normalise_sec_cik(cik)
        bulk_cache = cache_dir or (RAW_DIR / "sec_edgar")
        cached_bulk: RawDocument | None = None
        bulk_reason = ""
        identity = _build_sec_bulk_identity(normalised_cik, instrument_id) if normalised_cik is not None else None
        if normalised_cik is None:
            bulk_reason = "requested CIK is malformed"
        elif identity is not None:
            cached_bulk, bulk_reason = _cached_sec_bulk_document(bulk_cache, getattr(session, "_sec_bulk_provider", None))
            if cached_bulk is not None:
                statement_import_started = True
                bulk_result = session._sec_bulk_provider.import_companyfacts_bulk(
                    (identity,),
                    import_cache_dir=bulk_cache,
                    cache_only=True,
                    facts_destination=STATEMENT_FACTS_PATH,
                    inventory_destination=FILINGS_STATEMENTS_PATH,
                    publish_guard=publish_guard,
                )
                if bulk_result.overall_status in {"complete", "partial"}:
                    session.last_message = _bulk_result_message(bulk_result, "SEC cached bulk import", context=bulk_reason)
                    session._record_sec_bulk_outputs(bulk_result)
                    return session.last_message
                detail = next((item.detail for item in bulk_result.per_cik if item.detail), "")
                bulk_reason = f"cached bulk import failed: {detail or bulk_result.overall_status}"
        else:
            bulk_reason = f"validated SEC bulk cache unavailable; {_sec_bulk_identity_reason(normalised_cik, instrument_id)}"

        # Only genuine absent binding may use the unresolved/manual JSON
        # fallback. Known-invalid evidence must not reach its legacy resolver.
        if normalised_cik is not None and identity is None and (
            instrument_id is not None or _persisted_sec_instruments(normalised_cik) != ()
        ):
            session.last_message = f"SEC import unavailable: {bulk_reason}. Local data was not changed."
            return _legacy_unavailable(session, session.last_message)
        configured_agent = str(user_agent or os.getenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT") or "").strip()
        if not configured_agent:
            session.last_message = f"SEC import unavailable: {bulk_reason}; configure ETF_COCKPIT_SEC_EDGAR_USER_AGENT with name and contact email. {_sec_failure_state(statement_import_started)}"
            return _legacy_unavailable(session, session.last_message)
        if normalised_cik is None:
            session.last_message = f"SEC import unavailable: {bulk_reason}. Local data was not changed."
            return _legacy_unavailable(session, session.last_message)
        provider = SecEdgarProvider(
            configured_agent,
            cache_dir=bulk_cache,
        )
        document = provider.fetch_companyfacts(cik, publish_guard=publish_guard)
        statement_import_started = True
        result = session.import_sec_companyfacts(
            document.path,
            instrument_id=instrument_id,
            document=document,
            publish_guard=publish_guard,
        )
        # The legacy local-import wording concerns that operation only;
        # an encompassing fetch may already have published raw documents.
        result = result.replace("No data changed", "Raw acquisition cache may have changed; inspect statement-import status")
        session.last_message = result
        if bulk_reason:
            session.last_message = f"{result} Bulk fallback: {bulk_reason}."
        return session.last_message
    except ActivityUnavailableError as exc:
        if not statement_import_started:
            raise
        session.last_message = str(exc).replace("No data changed", "Raw acquisition cache may have changed; inspect statement-import status")
        raise ActivityUnavailableError(session.last_message) from exc
    except WorkflowTransitionError:
        raise
    except Exception as exc:
        session.last_message = f"SEC import unavailable: {_sec_failure_detail(exc)}. {_sec_failure_state(statement_import_started)}"
        return _legacy_unavailable(session, session.last_message, exc)


def import_sec_companyfacts_bulk(
    session: FilingIngestionSession,
    archive: Path,
    *,
    cik: str | None = None,
    instrument_id: str | None = None,
    identity: CanonicalIdentity | None = None,
    cache_dir: Path | None = None,
    provenance: RawDocument | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Import one explicitly selected CIK from a local SEC bulk ZIP."""

    statement_import_started = False
    try:
        selected = identity
        if selected is None:
            normalised_cik = _normalise_sec_cik(cik)
            if normalised_cik is None:
                raise ValueError("SEC bulk import requires a valid selected CIK")
            selected = _build_sec_bulk_identity(normalised_cik, instrument_id, allow_manual=True)
            if selected is None:
                raise ValueError("SEC bulk import requires a unique persisted CIK-to-instrument identity")
        else:
            if not isinstance(selected, CanonicalIdentity):
                raise ValueError("SEC bulk import requires a CanonicalIdentity")
            _validate_sec_bulk_identity(selected)
            if cik is not None and _normalise_sec_cik(cik) != _normalise_sec_cik(selected.cik):
                raise ValueError("supplied CIK does not match the selected canonical identity")
            if instrument_id is not None and (not isinstance(instrument_id, str) or selected.instrument_id != instrument_id):
                raise ValueError("supplied instrument ID does not match the selected canonical identity")
        statement_import_started = True
        result = _import_sec_companyfacts_bulk(
            Path(archive),
            (selected,),
            cache_dir=cache_dir or (RAW_DIR / "sec_edgar"),
            facts_destination=STATEMENT_FACTS_PATH,
            inventory_destination=FILINGS_STATEMENTS_PATH,
            provenance=provenance,
            publish_guard=publish_guard,
        )
        session.last_message = _bulk_result_message(result, "SEC bulk import")
        if result.overall_status not in {"complete", "partial"}:
            return _legacy_unavailable(session, session.last_message)
        session._record_sec_bulk_outputs(result)
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"SEC bulk import unavailable: {_sec_failure_detail(exc)}. {_sec_failure_state(statement_import_started)}"
        return _legacy_unavailable(session, session.last_message, exc)


def fetch_sec_companyfacts_bulk(
    session: FilingIngestionSession,
    cik: str,
    *,
    instrument_id: str | None = None,
    cache_dir: Path | None = None,
    user_agent: str | None = None,
    publish_guard: PublicationScopeFactory | None = None,
    cache_only: bool = False,
) -> str:
    """Explicitly acquire the nightly bulk archive and import one CIK."""

    statement_import_started = False
    try:
        normalised_cik = _normalise_sec_cik(cik)
        selected = _build_sec_bulk_identity(normalised_cik, instrument_id) if normalised_cik is not None else None
        if selected is None:
            reason = _sec_bulk_identity_reason(normalised_cik, instrument_id) if normalised_cik is not None else "requested CIK is malformed"
            raise ValueError(f"SEC bulk refresh rejected before acquisition: {reason}")
        configured_agent = str(user_agent or os.getenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT") or "").strip()
        if not configured_agent and not cache_only:
            raise ValueError("explicit SEC bulk refresh requires a configured name and contact email")
        cache_root = cache_dir or (RAW_DIR / "sec_edgar")
        provider = getattr(session, "_sec_bulk_provider", None)
        if cache_only:
            if provider is None or Path(provider.cache_dir).resolve() != Path(cache_root).resolve():
                raise SecEdgarBulkUnavailable("SEC bulk cache unavailable: no same-session acquisition proof")
        elif provider is None or Path(provider.cache_dir).resolve() != Path(cache_root).resolve() or provider.user_agent != configured_agent:
            provider = SecEdgarProvider(configured_agent, cache_dir=cache_root)
            session._sec_bulk_provider = provider
        statement_import_started = True
        result = provider.import_companyfacts_bulk(
            (selected,), import_cache_dir=cache_root, cache_only=cache_only,
            facts_destination=STATEMENT_FACTS_PATH, inventory_destination=FILINGS_STATEMENTS_PATH,
            publish_guard=publish_guard,
        )
        session.last_message = _bulk_result_message(result, "SEC bulk import")
        if result.overall_status not in {"complete", "partial"}:
            return _legacy_unavailable(session, session.last_message)
        session._record_sec_bulk_outputs(result)
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except SecEdgarBulkUnavailable as exc:
        session.last_message = f"SEC bulk refresh unavailable: {_sec_failure_detail(exc)}. {_sec_failure_state(False)}"
        return _legacy_unavailable(session, session.last_message, exc)
    except Exception as exc:
        session.last_message = f"SEC bulk refresh unavailable: {_sec_failure_detail(exc)}. {_sec_failure_state(statement_import_started)}"
        return _legacy_unavailable(session, session.last_message, exc)


def _record_sec_bulk_outputs(session: FilingIngestionSession, result: BulkImportResult) -> None:
    message = session.last_message
    session.sec_companyfacts_bulk_message = message
    session._record_activity_output("SEC statement facts published", STATEMENT_FACTS_PATH)
    session._record_activity_output("SEC statement inventory published", FILINGS_STATEMENTS_PATH)
    if result.checkpoint_path is not None:
        members = ",".join(str(item.member_sha256 or "missing") for item in result.per_cik[:3])
        session._record_activity_output(f"SEC {result.overall_status}; archive sha256={result.archive_sha256}; member sha256={members}; {message[:512]}", result.checkpoint_path)
    session.last_message = message


def _finish_sec_submissions_import(session: FilingIngestionSession, result: SubmissionsImportResult) -> str:
    session.sec_submissions_result = result
    warnings = ",".join(str(item.get("code", "warning")) for item in result.warnings[:5])
    session.last_message = redact_text(
        f"SEC submissions import {result.status}: {len(result.records)} filing records; "
        f"warnings={warnings or 'none'}; {result.detail}. Filing bytes may be missing; "
        "execution_allowed=false."
    )[:2048]
    if result.status not in {"complete", "partial"}:
        return _legacy_unavailable(session, session.last_message)
    message = session.last_message
    if result.manifest_path is not None:
        session._record_activity_output("SEC submissions manifest retained", result.manifest_path)
    for document in result.raw_documents[:3]:
        session._record_activity_output(f"SEC submissions sha256={document.sha256}", document.path)
    session.last_message = message
    return message


def import_sec_submissions_bulk(
    session: FilingIngestionSession, archive: Path, *, cik: str | None = None, instrument_id: str | None = None,
    identity: CanonicalIdentity | None = None, cache_dir: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Import local submissions metadata with explicit manual identity."""
    try:
        normalised = _normalise_sec_cik(cik) if cik is not None else None
        selected = identity or (_build_sec_bulk_identity(normalised, instrument_id, allow_manual=True) if normalised else None)
        if selected is None:
            raise ValueError("SEC submissions import requires a selected CIK and canonical instrument identity")
        _validate_sec_bulk_identity(selected)
        if cik is not None and _normalise_sec_cik(cik) != _normalise_sec_cik(selected.cik):
            raise ValueError("supplied CIK does not match the selected canonical identity")
        if instrument_id is not None and (not isinstance(instrument_id, str) or selected.instrument_id != instrument_id):
            raise ValueError("supplied instrument ID does not match the selected canonical identity")
        result = _import_sec_submissions(Path(archive), selected, cache_dir=cache_dir or (RAW_DIR / "sec_edgar"), publish_guard=publish_guard)
        return session._finish_sec_submissions_import(result)
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"SEC submissions import unavailable: {_sec_failure_detail(exc)}; execution_allowed=false."
        return _legacy_unavailable(session, session.last_message, exc)


def fetch_sec_submissions_bulk(
    session: FilingIngestionSession, cik: str, *, instrument_id: str | None = None, cache_dir: Path | None = None,
    user_agent: str | None = None, publish_guard: PublicationScopeFactory | None = None,
    cache_only: bool = False,
) -> str:
    """Explicitly acquire or select same-session submissions evidence."""
    try:
        normalised = _normalise_sec_cik(cik)
        selected = _build_sec_bulk_identity(normalised, instrument_id) if normalised else None
        if selected is None:
            raise ValueError("SEC submissions refresh requires a unique persisted CIK-to-instrument identity")
        configured_agent = str(user_agent or os.getenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT") or "").strip()
        cache_root = cache_dir or (RAW_DIR / "sec_edgar")
        provider = getattr(session, "_sec_bulk_provider", None)
        if cache_only:
            if provider is None or Path(provider.cache_dir).resolve() != Path(cache_root).resolve():
                raise SecEdgarBulkUnavailable("SEC bulk cache unavailable: no same-session acquisition proof")
        else:
            if not configured_agent:
                raise ValueError("SEC submissions refresh requires name and contact email")
            if provider is None or Path(provider.cache_dir).resolve() != Path(cache_root).resolve() or provider.user_agent != configured_agent:
                provider = SecEdgarProvider(configured_agent, cache_dir=cache_root)
                session._sec_bulk_provider = provider
        result = provider.import_submissions_bulk(selected, import_cache_dir=cache_root, cache_only=cache_only, publish_guard=publish_guard)
        return session._finish_sec_submissions_import(result)
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"SEC submissions refresh unavailable: {_sec_failure_detail(exc)}; raw cache may have changed; execution_allowed=false."
        return _legacy_unavailable(session, session.last_message, exc)


def import_esef_package(
    session: FilingIngestionSession,
    path: Path,
    *,
    instrument_id: str | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Import a local ESEF report package into the shared facts/inventory stores."""

    try:
        package_path = Path(path)
        raw_path, source_sha256 = _preserve_esef_raw(
            package_path,
            publish_guard=publish_guard,
        )
        parsed = parse_esef_package(package_path)
        if not parsed.success or not parsed.records:
            warning_codes = ", ".join(warning.code for warning in parsed.warnings)
            session.last_message = f"ESEF import unavailable: {warning_codes or 'validation failed'}. Raw filing retained at {raw_path}; no clean data changed."
            return _legacy_unavailable(session, session.last_message)
        if parsed.source_sha256 != source_sha256:
            raise ValueError("ESEF source checksum changed during parsing")
        lei = next((record.entity_lei for record in parsed.records if record.entity_lei and record.entity_lei != "unknown"), "unknown")
        resolved_instrument_id = str(instrument_id or f"esef_unresolved_{lei}").strip()
        if not resolved_instrument_id:
            raise ValueError("ESEF import requires a non-empty instrument ID when supplied")
        provider_id, source_url = _esef_source_provenance(package_path)
        acquired_at = datetime.now(timezone.utc)
        records = statement_facts_from_esef(
            parsed.records,
            instrument_id=resolved_instrument_id,
            source_sha256=parsed.source_sha256,
            source_provider=provider_id,
            known_at=acquired_at.isoformat(),
        )
        source = RawDocument(raw_path, source_url, acquired_at, parsed.source_sha256, provider_id, "esef_report_package", "application/octet-stream", 200)
        with publication_scope(publish_guard):
            write_statement_evidence(
                source,
                records,
                STATEMENT_FACTS_PATH,
                FILINGS_STATEMENTS_PATH,
                instrument_id=resolved_instrument_id,
                vendor_records=_load_vendor_statement_claims(resolved_instrument_id),
            )
        session._record_activity_output("ESEF statement evidence published", STATEMENT_FACTS_PATH)
        warning_codes = ", ".join(sorted({f"{warning.code}:{warning.severity}" for warning in parsed.warnings})) or "none"
        mapping_counts = {
            "mapped": sum(record.mapping_status == "mapped" for record in parsed.records),
            "extensions": sum(record.mapping_status == "unmapped_extension" for record in parsed.records),
            "unmapped": sum(record.mapping_status == "unmapped" for record in parsed.records),
        }
        review_note = " manual identity review required." if instrument_id is None else ""
        authority = "official_filing" if provider_id == "filings_xbrl_org" else "manual_review"
        session.last_message = f"ESEF import complete: {len(records)} facts, warnings={warning_codes}, mapping={mapping_counts}; source_authority={authority}.{review_note}"
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"ESEF import unavailable: {type(exc).__name__}. No data changed; scoring and execution were not started."
        return _legacy_unavailable(session, session.last_message, exc)


def discover_esef_filings(
    session: FilingIngestionSession,
    country: str = "NL",
    limit: int = 10,
    *,
    cache_dir: Path | None = None,
    expected_action_id: str | None = None,
) -> str:
    """Discover official ESEF filings with an explicit unavailable state."""

    try:
        provider = FilingsXbrlOrgProvider(cache_dir=cache_dir or (RAW_DIR / "esef"))
        result = provider.list_filings(country, limit)
        if result.status != "ok":
            session.last_message = f"ESEF discovery unavailable: {redact_text(str(result.message))}"
            raise ActivityUnavailableError(session.last_message)
        filing_count = len(result.data) if result.data is not None else 0
        message = f"ESEF discovery complete: {filing_count} official filings."
        action_id = expected_action_id or getattr(getattr(session, "_activity_context", None), "action_id", None)
        if action_id is None:
            session._esef_provider = provider
            session._esef_filings = result.data
            session.last_message = message
        else:
            with session.activity_publication(action_id):
                session._esef_provider = provider
                session._esef_filings = result.data
                session.last_message = message
        return message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = f"ESEF discovery unavailable: {type(exc).__name__}. Local data was not changed."
        raise ActivityUnavailableError(session.last_message) from exc


def discover_oam(
    session: FilingIngestionSession,
    country: str,
    *,
    issuer: str = "",
    isin: str = "",
    document_type: str = "",
    date_from: str = "",
    date_to: str = "",
    endpoint: str = "",
    company_number: str = "",
    api_key: str = "",
    cache_dir: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Discover one official OAM export without changing clean evidence on failure."""

    try:
        start = datetime.fromisoformat(date_from.strip()).date() if date_from.strip() else None
        end = datetime.fromisoformat(date_to.strip()).date() if date_to.strip() else None
        if start and end and start > end:
            raise ValueError("OAM date_from must not be after date_to")
        country_code = str(country or "").strip().upper()
        adapter_type = oam_adapter_for_country(country_code)
        adapter_kwargs: dict[str, object] = {
            "cache_dir": cache_dir,
            "endpoint": endpoint or None,
            "enabled": bool(endpoint.strip()) or adapter_type is CompaniesHouseFilingAdapter,
            "publish_guard": publish_guard,
        }
        if adapter_type is CompaniesHouseFilingAdapter:
            adapter_kwargs["api_key"] = api_key
        adapter = adapter_type(**adapter_kwargs)
        request = OAMDiscoveryRequest(
            issuer=issuer,
            isin=isin,
            document_type=document_type,
            date_from=start,
            date_to=end,
            company_number=company_number,
        )
        result = adapter.discover(request)
        coverage_path = write_filing_coverage(
            result,
            country=country_code,
            request=request,
            publish_guard=publish_guard,
        )
        if result.status == "ok":
            registry_path = write_oam_discovery_registry(result, publish_guard=publish_guard)
            session._record_activity_output("Official filing registry published", registry_path)
            session.last_message = f"{redact_text(str(result.message))} Snapshot checksum={result.snapshot.sha256[:12] if result.snapshot else 'unavailable'}..."
        else:
            session._record_activity_output("Filing coverage evidence retained", coverage_path)
            session.last_message = f"{redact_text(str(result.message))} Manual fallback remains available; no clean evidence was changed."
            raise ActivityUnavailableError(session.last_message)
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = (
            f"OAM discovery unavailable: {type(exc).__name__}. Manual fallback remains available; "
            "the coverage attempt was retained when possible, but no filing evidence or score changed."
        )
        raise ActivityUnavailableError(session.last_message) from exc


def import_local_oam(
    session: FilingIngestionSession,
    path: Path,
    country: str,
    *,
    issuer: str = "",
    isin: str = "",
    document_type: str = "",
    date_from: str = "",
    date_to: str = "",
    company_number: str = "",
    cache_dir: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Import a local structured OAM export as manual-review evidence."""

    try:
        start = datetime.fromisoformat(date_from.strip()).date() if date_from.strip() else None
        end = datetime.fromisoformat(date_to.strip()).date() if date_to.strip() else None
        if start and end and start > end:
            raise ValueError("OAM date_from must not be after date_to")
        country_code = str(country or "").strip().upper()
        request = OAMDiscoveryRequest(
            issuer=issuer,
            isin=isin,
            document_type=document_type,
            date_from=start,
            date_to=end,
            company_number=company_number,
        )
        result = import_local_oam_export(
            Path(path),
            country=country_code,
            request=request,
            cache_dir=cache_dir,
            publish_guard=publish_guard,
        )
        if not result.records:
            session.last_message = (
                f"{redact_text(str(result.message))} No discovery rows or coverage were published; "
                "manual review remains required and execution_allowed=false."
            )
            raise ActivityUnavailableError(session.last_message)
        # Local imports are intentionally manual-review results, but they
        # still publish the discovered rows and their coverage observation.
        registry_path = write_oam_discovery_registry(result, publish_guard=publish_guard)
        write_filing_coverage(
            result,
            country=country_code,
            request=request,
            publish_guard=publish_guard,
        )
        session._record_activity_output("Local OAM filing registry published", registry_path)
        checksum = result.snapshot.sha256[:12] if result.snapshot else "unavailable"
        session.last_message = (
            f"{redact_text(str(result.message))} Snapshot checksum={checksum}...; "
            "source_authority=local_user_import; manual_review=true; execution_allowed=false."
        )
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = (
            f"Local OAM import unavailable: {type(exc).__name__}. "
            "Import publication did not complete; inspect retained local evidence before retrying. "
            "Manual review remains required and execution_allowed=false."
        )
        raise ActivityUnavailableError(session.last_message) from exc


def import_manual_official_filing(
    session: FilingIngestionSession,
    path: Path,
    *,
    jurisdiction: str,
    instrument_id: str,
    source_url: str,
    document_type: str = "annual_report",
    published_at: str = "",
    available_at: str = "",
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Archive one user-owned official filing for explicit manual review."""

    try:
        record = archive_manual_official_filing(
            path,
            jurisdiction=jurisdiction,
            instrument_id=instrument_id,
            source_url=source_url,
            document_type=document_type,
            published_at=published_at or None,
            available_at=available_at or None,
            publish_guard=publish_guard,
        )
        session._record_activity_output("Manual official filing archived", record.raw_path)
        session.last_message = (
            f"Official filing archived for {record.instrument_id}: {record.sha256[:12]}...; "
            f"availability={record.availability_precision}; manual review required; execution_allowed=false."
        )
        return session.last_message
    except (ActivityUnavailableError, WorkflowTransitionError):
        raise
    except Exception as exc:
        session.last_message = (
            f"Official filing import unavailable: {type(exc).__name__}. "
            "No existing evidence changed; scoring and execution were not started."
        )
        raise ActivityUnavailableError(session.last_message) from exc


def download_esef_package(
    session: FilingIngestionSession,
    filing_id: str,
    *,
    package_url: str | None = None,
    cache_dir: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> str:
    """Download one discovered official package while retaining immutable raw bytes."""

    try:
        provider = getattr(session, "_esef_provider", None) or FilingsXbrlOrgProvider(cache_dir=cache_dir or (RAW_DIR / "esef"))
        try:
            document = provider.download_report_package(
                filing_id,
                package_url,
                publish_guard=publish_guard,
            )
        except TypeError as exc:
            if "publish_guard" not in str(exc):
                raise
            document = provider.download_report_package(filing_id, package_url)
        session._record_activity_output("ESEF package downloaded", document.path)
        session.last_message = f"ESEF package downloaded: {document.path.name} ({document.sha256[:12]}...)."
        return session.last_message
    except (EsefProviderUnavailable, OSError, ValueError) as exc:
        session.last_message = f"ESEF download unavailable: {type(exc).__name__}. Local data was not changed."
        raise ActivityUnavailableError(session.last_message) from exc
