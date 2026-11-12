"""Claimant identity, PIT continuity and the idempotent MODEL_UPDATE_AVAILABLE workflow (#717).

Consumes accepted ``sparebank-intelligence-result.v1`` projections from the #716 run store, resolves
every referenced asset against the existing identity master using only knowledge available at the
run's ``known_at_cutoff``, preserves predecessor/successor claimant continuity for structural
events and emits one durable ``MODEL_UPDATE_AVAILABLE`` logical event per accepted projection
through the existing durable job scheduler.  Nothing here creates orders, proposals or authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from etf_cockpit.analysis.sparebank.events import conversion_event
from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobContext, JobSpec, WorkflowRecord
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityResolutionError
from etf_cockpit.data.sparebank_intelligence import canonical_json
from etf_cockpit.data.sparebank_run_store import SparebankRunStore

POLICY_VERSION = "sbi-claimant-resolution.v1"
EVENT_TYPE = "MODEL_UPDATE_AVAILABLE"
WORKFLOW_TYPE = "sparebank_model_update"
STAGE_PERSIST = "resolve_and_persist"
STAGE_EMIT = "emit_model_update"

LEGACY_HOLDERS = "legacy_private_ec_holders"
FOUNDATION = "foundation"
_CONTINUITY_KINDS = frozenset({"EC_FOR_EC", "CASH", "MIXED", "CONVERSION", "TICKER_CHANGE", "SUCCESSOR"})
_ISSUER_KEYS = ("lei", "national_id")
_RUN_SECTIONS = ("owner_claims", "valuations", "distributions", "advisory")


class ModelUpdateConflict(RuntimeError):
    """Raised when the same logical run is bound to a different envelope or projection."""


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


# --------------------------------------------------------------------------- identity


def resolve_asset(
    store: IdentityMasterStore,
    instrument_id: str,
    *,
    decision_time: str,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve one supplied asset; order: canonical ID, ISIN, issuer LEI/org-number, ticker/MIC as support only."""

    aliases = {str(k).lower(): str(v) for k, v in (aliases or {}).items() if str(v).strip()}
    supplied = {"instrument_id": instrument_id, **dict(sorted(aliases.items()))}
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    resolution = None

    try:
        resolution = store.resolve(instrument_id, effective_at=decision_time, decision_time=decision_time)
        candidates.append({"key": "instrument_id", "value": instrument_id, "instruments": [instrument_id], "strength": "canonical"})
    except (KeyError, IdentityResolutionError, ValueError) as exc:
        candidates.append({"key": "instrument_id", "value": instrument_id, "instruments": [], "strength": "canonical", "note": type(exc).__name__})

    def lookup(key: str, strength: str) -> set[str]:
        value = aliases.get("org_number" if key == "national_id" else key)
        if not value:
            return set()
        try:
            found = set(store.instruments_for_identifier(key, value, effective_at=decision_time, decision_time=decision_time))
            note = None
        except IdentityResolutionError:
            found, note = set(), "availability_ambiguous"
        entry = {"key": key, "value": value, "instruments": sorted(found), "strength": strength}
        if note:
            entry["note"] = note
        candidates.append(entry)
        return found

    isin = lookup("isin", "instrument")
    issuer_sets = [lookup(key, "issuer") for key in _ISSUER_KEYS if aliases.get("org_number" if key == "national_id" else key)]
    ticker = lookup("ticker", "supporting_only") if aliases.get("ticker") else set()
    exact = {instrument_id} if resolution is not None else set()

    status, selected, reason = "UNRESOLVED", None, "no_identity_evidence"
    if len(isin) > 1:
        status, reason = "CONFLICT", "isin_maps_to_multiple_instruments"
    elif exact and isin and exact != isin:
        status, reason = "CONFLICT", "canonical_id_isin_disagree"
    elif any(issuer and len(issuer) > 1 for issuer in issuer_sets) and not (exact or isin):
        status, reason = "CONFLICT", "issuer_maps_to_multiple_instruments"
    elif len({frozenset(s) for s in issuer_sets if s}) > 1:
        status, reason = "CONFLICT", "issuer_evidence_disagrees"
    else:
        chosen = exact or isin
        if chosen:
            (selected,) = chosen
            if any(issuer and selected not in issuer for issuer in issuer_sets):
                status, selected, reason = "CONFLICT", None, "issuer_evidence_excludes_instrument"
            elif resolution is not None and resolution.requires_manual_review:
                status, reason = "CONFLICT", "identity_manual_review_required"
                selected = None
            else:
                status, reason = "RESOLVED", "canonical_id" if exact else "isin"
        elif any(issuer_sets):
            reason = "issuer_evidence_without_instrument_qualifier"
        elif ticker or aliases.get("ticker"):
            reason = "ticker_not_global_key"
    if status == "RESOLVED" and aliases.get("ticker") and selected not in ticker:
        warnings.append("ticker_does_not_support_selected_instrument")

    identity: dict[str, Any] = {}
    version: dict[str, Any] = {"policy_version": POLICY_VERSION}
    if status == "RESOLVED" and resolution is None:
        resolution = store.resolve(selected, effective_at=decision_time, decision_time=decision_time)
    if status == "RESOLVED" and resolution is not None:
        ident = resolution.identity
        identity = {
            "instrument_id": ident.instrument_id, "issuer": ident.issuer, "listing": ident.listing,
            "share_class": ident.share_class, "isin": ident.isin, "ticker": ident.ticker, "mic": ident.mic,
        }
        version.update(decision_id=resolution.decision_id, decision_schema_version=resolution.decision_schema_version,
                       resolution_state=resolution.resolution_state)
        warnings.extend(resolution.warnings)
    return {
        "supplied": supplied, "candidates": candidates, "status": status, "selected_instrument_id": selected,
        "reason": reason, "identity": identity, "identity_version": version, "effective_at": decision_time,
        "decision_time": decision_time, "warnings": sorted(set(warnings)),
    }


# ------------------------------------------------------------------------ continuity


def _continuity_link(event: Mapping[str, Any], decision_time: datetime) -> dict[str, Any]:
    base = {"event_id": event.get("event_id"), "event_type": event.get("event_type")}
    spec = event.get("security_continuity")

    def fail(reason: str, status: str = "UNRESOLVED") -> dict[str, Any]:
        return {**base, "status": status, "reason": reason}

    if not isinstance(spec, Mapping):
        return fail("continuity_bridge_missing")
    kind = spec.get("kind")
    known, effective = _time(spec.get("known_at")), _time(spec.get("effective_at"))
    if kind not in _CONTINUITY_KINDS:
        return fail("continuity_kind_invalid")
    if known is None or effective is None:
        return fail("continuity_time_missing")
    if known > decision_time:
        return {**base, "status": "NOT_YET_KNOWN", "reason": "knowledge_after_decision_time", "known_at": spec["known_at"]}
    pred, succ = spec.get("predecessor_instrument_id"), spec.get("successor_instrument_id")
    if not pred:
        return fail("predecessor_missing")
    ratio, cash = spec.get("conversion_ratio"), spec.get("cash_per_predecessor_ec")
    has_ratio = isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio > 0
    has_cash = isinstance(cash, (int, float)) and not isinstance(cash, bool) and cash > 0
    if kind == "EC_FOR_EC" and not (has_ratio and succ and not has_cash):
        return fail("consideration_inconsistent", "REJECTED")
    if kind == "CASH" and not (has_cash and not has_ratio and not succ and spec.get("delisted") is True):
        return fail("consideration_inconsistent", "REJECTED")
    if kind == "MIXED" and not (has_ratio and has_cash and succ):
        return fail("consideration_inconsistent", "REJECTED")
    if kind in {"TICKER_CHANGE", "SUCCESSOR"} and not succ:
        return fail("successor_missing")
    allocations = []
    for row in spec.get("allocations") or ():
        if not isinstance(row, Mapping) or not row.get("claimant"):
            return fail("allocation_invalid", "REJECTED")
        if row["claimant"] == LEGACY_HOLDERS and row.get("source") == "FOUNDATION_ISSUED" and not row.get("legal_bridge_ref"):
            return fail("foundation_consideration_misattributed", "REJECTED")
        allocations.append(dict(row))
    conversion = None
    if kind == "CONVERSION":
        c = spec.get("conversion")
        if not isinstance(c, Mapping) or None in (c.get("pre_ec_count"), c.get("foundation_ec_count"), c.get("post_ec_count")):
            return fail("conversion_counts_missing")
        computed = conversion_event({"outstanding_ec_count": c["pre_ec_count"]}, foundation_ec_count=c["foundation_ec_count"],
                                    effective_at=spec.get("effective_at"), known_at=spec.get("known_at"), source_id=base["event_id"])
        if computed["post_state"]["outstanding_ec_count"] != c["post_ec_count"]:
            return fail("conversion_post_count_mismatch", "REJECTED")
        conversion = {"pre_ec_count": c["pre_ec_count"], "foundation_ec_count": c["foundation_ec_count"],
                      "post_ec_count": c["post_ec_count"], "recipient_ledger": list(computed["recipient_ledger"])}
    return {
        **base, "status": "RESOLVED", "reason": None, "kind": kind, "predecessor_instrument_id": pred,
        "successor_instrument_id": succ, "conversion_ratio": ratio if has_ratio else None,
        "cash_per_predecessor_ec": cash if has_cash else None, "effective_at": spec["effective_at"],
        "known_at": spec["known_at"], "allocations": allocations, "conversion": conversion,
    }


def successor_chain(links: list[Mapping[str, Any]], instrument_id: str) -> list[str]:
    """Economic-claim chain from a (possibly delisted) predecessor to its latest successor; cycle-safe."""

    chain, seen = [instrument_id], {instrument_id}
    while True:
        nxt = next((l["successor_instrument_id"] for l in links if l.get("status") == "RESOLVED"
                    and l["predecessor_instrument_id"] == chain[-1] and l.get("successor_instrument_id")), None)
        if nxt is None or nxt in seen:
            return chain
        chain.append(nxt)
        seen.add(nxt)


# ------------------------------------------------------------------------ projection


def build_resolution_projection(
    run: Mapping[str, Any],
    store: IdentityMasterStore,
    *,
    raw_sha256: str,
    aliases: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    cutoff = str(run["known_at_cutoff"])
    decision = _time(cutoff)
    aliases = aliases or {}
    links = [_continuity_link(e, decision) for e in run.get("structural_events", ())]
    resolved_links = [l for l in links if l["status"] == "RESOLVED"]

    sections: dict[str, set[str]] = {}
    for section in _RUN_SECTIONS:
        for row in run.get(section, ()):
            sections.setdefault(row["instrument_id"], set()).add(section)
    for link in resolved_links:
        for key in ("predecessor_instrument_id", "successor_instrument_id"):
            if link.get(key):
                sections.setdefault(link[key], set()).add("continuity")
    assets = {iid: {**resolve_asset(store, iid, decision_time=cutoff, aliases=aliases.get(iid)), "referenced_by": sorted(refs)}
              for iid, refs in sorted(sections.items())}

    states = []
    by_event = {l["event_id"]: l for l in links}
    superseded = {l["predecessor_instrument_id"] for l in resolved_links
                  if l["kind"] != "TICKER_CHANGE" and _time(l["effective_at"]) <= decision}
    for claim in run.get("owner_claims", ()):
        iid = claim["instrument_id"]
        state = {"instrument_id": iid, "event_id": claim.get("event_id"), "status": "RESOLVED", "reason": None,
                 "state": "CURRENT", "bindings": {
                     "ec_count_current": claim["ec_count_current"], "ec_count_fully_diluted": claim["ec_count_fully_diluted"],
                     "treasury_ec_count": claim["treasury_ec_count"], "eierbrok": claim["eierbrok"],
                     "foundation_share": claim["holdings"]["foundation_share"], "strategic_share": claim["holdings"]["strategic_share"],
                     "effective_free_float": claim["holdings"]["effective_free_float"]}}
        if assets[iid]["status"] != "RESOLVED":
            state.update(status="UNRESOLVED", reason="identity_" + assets[iid]["status"].lower())
        elif claim.get("event_id"):
            link = by_event.get(claim["event_id"])
            pre, post = claim.get("pre_event_state") or {}, claim.get("post_event_state") or {}
            if link is None or link["status"] != "RESOLVED":
                state.update(status="UNRESOLVED", reason="event_bridge_missing" if link is None else link["reason"])
            elif iid == link["predecessor_instrument_id"] and claim["ec_count_current"] != pre.get("ec_count_current"):
                state.update(status="REJECTED", reason="post_event_economics_on_pre_event_instrument")
            elif iid == link["successor_instrument_id"] and claim["ec_count_current"] != post.get("ec_count_current"):
                state.update(status="REJECTED", reason="pre_event_economics_on_post_event_instrument")
            elif iid not in (link["predecessor_instrument_id"], link["successor_instrument_id"]):
                state.update(status="UNRESOLVED", reason="instrument_not_in_event_bridge")
            else:
                state["state"] = "PRE" if iid == link["predecessor_instrument_id"] else "POST"
        elif iid in superseded:
            state.update(status="UNRESOLVED", reason="predecessor_superseded_without_event_binding")
        states.append(state)

    unresolved_ids = {iid for iid, a in assets.items() if a["status"] != "RESOLVED"} | {s["instrument_id"] for s in states if s["status"] != "RESOLVED"}
    advisory = {a["instrument_id"]: a for a in run.get("advisory", ())}
    unresolved = [{"instrument_id": iid, "opportunity_score": advisory.get(iid, {}).get("opportunity_score"),
                   "suggested_exposure_range": advisory.get(iid, {}).get("suggested_exposure_range")}
                  for iid in sorted(unresolved_ids)]
    fingerprints = {iid: _sha({"asset": {k: a[k] for k in ("status", "selected_instrument_id", "reason", "identity", "candidates")},
                               "states": [s for s in states if s["instrument_id"] == iid],
                               "links": [l for l in resolved_links if iid in (l["predecessor_instrument_id"], l.get("successor_instrument_id"))],
                               "content": {s: [r for r in run.get(s, ()) if r["instrument_id"] == iid] for s in _RUN_SECTIONS}})
                    for iid, a in assets.items()}
    body = {
        "policy_version": POLICY_VERSION, "run_id": run["run_id"], "content_hash": run["content_hash"], "raw_sha256": raw_sha256,
        "known_at_cutoff": cutoff, "generated_at": run["generated_at"], "decision_time": cutoff,
        "identity_versions": sorted({a["identity_version"].get("decision_id", "") for a in assets.values()} - {""}),
        "assets": assets, "claimant_states": states, "continuity": {"links": links, "chains": {
            l["predecessor_instrument_id"]: successor_chain(resolved_links, l["predecessor_instrument_id"]) for l in resolved_links}},
        "unresolved_exposure": {"assets": unresolved, "redistributed": False}, "asset_fingerprints": fingerprints,
        "authority": {"proposal_authority": False, "execution_allowed": False}, "execution_allowed": False,
    }
    return {**body, "projection_hash": _sha(body)}


def proposal_eligible_assets(projection: Mapping[str, Any]) -> tuple[str, ...]:
    """Assets whose identity AND claimant state resolved; unresolved/conflicted never pass (and nothing here is authority)."""

    blocked = {s["instrument_id"] for s in projection["claimant_states"] if s["status"] != "RESOLVED"}
    return tuple(i for i, a in projection["assets"].items() if a["status"] == "RESOLVED" and i not in blocked)


def invalidation_scope(prior: list[Mapping[str, Any]], projection: Mapping[str, Any]) -> dict[str, Any]:
    """Assets (and claimant states / decision contexts) whose content or resolution changed against the
    knowledge-chronological predecessor that held them; nothing else invalidates."""

    key = (projection["known_at_cutoff"], projection["run_id"])
    earlier = sorted((p for p in prior if (p["known_at_cutoff"], p["run_id"]) < key), key=lambda p: (p["known_at_cutoff"], p["run_id"]))
    affected = []
    for iid, fp in projection["asset_fingerprints"].items():
        previous = next((p["asset_fingerprints"][iid] for p in reversed(earlier) if iid in p["asset_fingerprints"]), None)
        if previous != fp:
            affected.append(iid)
    affected.sort()
    return {"affected_assets": affected,
            "affected_claimant_states": [s["instrument_id"] for s in projection["claimant_states"] if s["instrument_id"] in affected],
            "downstream_contexts": [f"decision_context:{i}" for i in affected],
            "predecessor_run_id": earlier[-1]["run_id"] if earlier else None}


# ------------------------------------------------------------------------ persistence


class ResolutionStore:
    """Immutable content-addressed projection files beside the run store (no second database)."""

    def __init__(self, run_store: SparebankRunStore) -> None:
        self.root = Path(run_store.root) / "resolutions"

    def _dir(self, run_id: str) -> Path:
        return self.root / run_id

    def _atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{uuid.uuid4().hex}.tmp"
        tmp.write_bytes(data)
        try:
            if path.exists():
                return
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def persist(self, projection: Mapping[str, Any]) -> Path:
        for existing in self.list(projection["run_id"]):
            if existing["raw_sha256"] != projection["raw_sha256"] or existing["content_hash"] != projection["content_hash"]:
                raise ModelUpdateConflict(f"run {projection['run_id']} already bound to a different envelope")
        path = self._dir(projection["run_id"]) / f"{projection['projection_hash']}.json"
        self._atomic(path, canonical_json(dict(projection)))
        return path

    def load(self, run_id: str, projection_hash: str) -> dict[str, Any] | None:
        try:
            data = json.loads((self._dir(run_id) / f"{projection_hash}.json").read_bytes())
        except (OSError, ValueError):
            return None
        body = {k: v for k, v in data.items() if k != "projection_hash"}
        return data if _sha(body) == projection_hash == data.get("projection_hash") else None

    def list(self, run_id: str) -> list[dict[str, Any]]:
        folder = self._dir(run_id)
        if not folder.is_dir():
            return []
        loaded = [self.load(run_id, p.stem) for p in sorted(folder.glob("*.json")) if not p.name.endswith(".scope.json")]
        return [p for p in loaded if p is not None]

    def all(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        return [p for d in sorted(self.root.iterdir()) if d.is_dir() for p in self.list(d.name)]

    def write_scope(self, run_id: str, projection_hash: str, scope: Mapping[str, Any]) -> dict[str, Any]:
        """First write wins so a restart reproduces the original invalidation scope."""

        path = self._dir(run_id) / f"{projection_hash}.scope.json"
        self._atomic(path, canonical_json(dict(scope)))
        return json.loads(path.read_bytes())


# ------------------------------------------------------------------------- workflow


class SparebankModelUpdateWorkflow:
    def __init__(
        self,
        run_store: SparebankRunStore,
        identity_store: IdentityMasterStore,
        scheduler: DurableJobScheduler,
        *,
        aliases: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self.run_store, self.identity_store, self.scheduler = run_store, identity_store, scheduler
        self.aliases = aliases or {}
        self.resolutions = ResolutionStore(run_store)

    def _raw_sha(self, run_id: str) -> str | None:
        try:
            return hashlib.sha256((Path(self.run_store.root) / "runs" / run_id / "envelope.json").read_bytes()).hexdigest()
        except OSError:
            return None

    def _projection(self, run_id: str) -> dict[str, Any] | None:
        run, raw_sha = self.run_store.get_run(run_id), self._raw_sha(run_id)
        if run is None or raw_sha is None:
            return None  # unavailable: unverifiable run store content
        return build_resolution_projection(run, self.identity_store, raw_sha256=raw_sha, aliases=self.aliases)

    def idempotency_material(self, run: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "event_type": EVENT_TYPE, "producer": run["producer"]["id"], "schema": run["schema"],
            "schema_major": run["schema_major"], "schema_minor": run["schema_minor"], "model_version": run["model_version"],
            "science_version": run["science_version"], "code_revision": run["code_revision"], "run_id": run["run_id"],
            "content_hash": run["content_hash"], "raw_sha256": projection["raw_sha256"],
            "attachment_hashes": sorted(a["sha256"] for a in run.get("attachments", ())),
            "run_store_identity": _sha({"run_id": run["run_id"], "raw_sha256": projection["raw_sha256"], "content_hash": run["content_hash"]}),
            "resolution_projection": projection["projection_hash"], "policy_version": POLICY_VERSION,
        }

    def submit(self, run_id: str) -> WorkflowRecord:
        """Idempotent: identical material returns the existing workflow; a conflicting binding fails closed."""

        run, projection = self.run_store.get_run(run_id), self._projection(run_id)
        if run is None or projection is None:
            raise LookupError(f"accepted run {run_id} unavailable")
        return self.submit_projection(run, projection)

    def submit_projection(self, run: Mapping[str, Any], projection: Mapping[str, Any]) -> WorkflowRecord:
        run_id = run["run_id"]
        material = self.idempotency_material(run, projection)
        for wf in self.scheduler.list_workflows(limit=100_000):
            inputs = wf.inputs if isinstance(wf.inputs, Mapping) else {}
            if wf.workflow_type == WORKFLOW_TYPE and inputs.get("run_id") == run_id and (
                    inputs.get("raw_sha256") != material["raw_sha256"] or inputs.get("content_hash") != material["content_hash"]):
                raise ModelUpdateConflict(f"run {run_id} already queued for a different envelope")
        key = _sha(material)
        payload = {"run_id": run_id, "raw_sha256": material["raw_sha256"], "content_hash": material["content_hash"],
                   "projection_hash": projection["projection_hash"], "idempotency_key": key, "material": material}
        return self.scheduler.submit(
            WORKFLOW_TYPE, f"{EVENT_TYPE} {run_id}",
            (JobSpec(STAGE_PERSIST, "Resolve claimants and persist evidence", payload),
             JobSpec(STAGE_EMIT, f"Emit {EVENT_TYPE}", payload, dependencies=(STAGE_PERSIST,))),
            input_payload=payload, dedupe_key=f"{WORKFLOW_TYPE}:{key}")

    def _stage(self, context: JobContext) -> dict[str, Any]:
        job = self.scheduler.get_job(context.job_id)
        payload = job.inputs
        run_id = payload["run_id"]
        if job.job_key == STAGE_PERSIST:
            projection = self._projection(run_id)
            if projection is None or projection["projection_hash"] != payload["projection_hash"]:
                raise ModelUpdateConflict("resolution projection changed since submission")  # fail closed, never re-bind
            self.resolutions.persist(projection)
            prior = [p for p in self.resolutions.all() if p["run_id"] != run_id]
            self.resolutions.write_scope(run_id, projection["projection_hash"], invalidation_scope(prior, projection))
            return {"projection_hash": projection["projection_hash"]}
        projection = self.resolutions.load(run_id, payload["projection_hash"])
        scope_path = self.resolutions._dir(run_id) / f"{payload['projection_hash']}.scope.json"
        if projection is None or not scope_path.exists():
            raise LookupError("persisted resolution evidence unavailable")
        scope = json.loads(scope_path.read_bytes())
        return {
            "event_type": EVENT_TYPE, "idempotency_key": payload["idempotency_key"], "run_id": run_id,
            "projection_hash": projection["projection_hash"], "known_at_cutoff": projection["known_at_cutoff"],
            "unresolved_assets": [u["instrument_id"] for u in projection["unresolved_exposure"]["assets"]],
            **scope, "authority": projection["authority"], "execution_allowed": False,
        }

    def drain(self, workflow_id: str, *, max_steps: int = 10) -> None:
        """Run queued stages of one workflow; safe to call again after a restart (stages are deterministic)."""

        self.scheduler.recover_expired_leases()
        for _ in range(max_steps):
            if self.scheduler.run_once(self._stage, workflow_id=workflow_id) is None:
                return

    def events(self) -> list[dict[str, Any]]:
        """Durable MODEL_UPDATE_AVAILABLE events in true knowledge chronology."""

        found = []
        for wf in self.scheduler.list_workflows(limit=100_000):
            if wf.workflow_type != WORKFLOW_TYPE:
                continue
            for job in self.scheduler.list_jobs(wf.workflow_id):
                if job.job_key == STAGE_EMIT and job.status.value == "succeeded" and isinstance(job.outputs, Mapping):
                    found.append(dict(job.outputs))
        return sorted(found, key=lambda e: (e["known_at_cutoff"], e["run_id"]))

    def replay_at(self, as_of: str) -> list[dict[str, Any]]:
        """Projections of runs accepted by ``as_of`` re-derived from identity knowledge at each run's own cutoff."""

        limit, out = _time(as_of), []
        for run_id in self.run_store.run_ids():
            run = self.run_store.get_run(run_id)
            if run and _time(run["known_at_cutoff"]) <= limit and _time(run["generated_at"]) <= limit:
                out.append(self._projection(run_id))
        return sorted((p for p in out if p), key=lambda p: (p["known_at_cutoff"], p["run_id"]))
