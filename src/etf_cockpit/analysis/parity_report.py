"""Read-only parity comparisons for saved analysis and workflow evidence.

Numeric tolerances are deliberately tight (absolute and relative 1e-9) and
apply only to analysis fields listed in ``analysis_parity_v1.yaml``. Identity,
version, source, action, blocker, and date fields remain exact. This module
compares supplied outputs only; it never recalculates analysis, valuation,
returns, FX, or distributions.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Mapping, Sequence
import hashlib
from io import StringIO
import json
import math
from numbers import Real
from pathlib import Path
import re
import yaml

from etf_cockpit.analysis.decision.contracts import OpportunityResult
from etf_cockpit.analysis.decision.opportunity import opportunity_result_payload
from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import project_root
from etf_cockpit.core.values import finite_real_or_none as _finite_number


_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "analysis_parity_v1.yaml"
_CORE_SURFACES = ("detail", "bulk", "holdings")
_PORTFOLIO_ARTIFACTS = ("ledger", "performance_series", "csv_export")
_SENSITIVE_FIELD = re.compile(r"(?:api[_-]?key|authorization|password|secret|bearer)", re.I)
_SECRET_VALUE = re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b|\bBearer\s+\S+", re.I)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"\b(api[_-]?key|authorization|password|secret)\s*[:=]\s*[^,\s;]+", re.I
)


def load_analysis_parity_config(path: str | Path = _CONFIG_PATH) -> dict[str, object]:
    """Load the versioned parity policy; missing or malformed policy fails closed."""

    try:
        parsed = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("analysis parity policy is unavailable or invalid") from exc
    if (
        not isinstance(parsed, Mapping)
        or parsed.get("schema_version") != 1
        or parsed.get("version") != "analysis-parity-v1"
    ):
        raise ValueError("analysis parity policy requires schema_version 1")
    tolerances = parsed.get("numeric_tolerances")
    core_surfaces = parsed.get("required_core_surfaces")
    portfolio_artifacts = parsed.get("portfolio_artifacts")
    numeric_fields = parsed.get("numeric_analysis_fields")
    if (
        not isinstance(tolerances, Mapping)
        or tuple(core_surfaces or ()) != _CORE_SURFACES
        or tuple(portfolio_artifacts or ()) != _PORTFOLIO_ARTIFACTS
        or not isinstance(numeric_fields, Sequence)
        or isinstance(numeric_fields, (str, bytes))
        or not numeric_fields
        or any(not isinstance(field, str) or not field.strip() for field in numeric_fields)
        or len(set(numeric_fields)) != len(numeric_fields)
    ):
        raise ValueError("analysis parity policy has an unsupported contract")
    absolute = _finite_number(tolerances.get("absolute"))
    relative = _finite_number(tolerances.get("relative"))
    if absolute is None or relative is None or absolute < 0 or relative < 0:
        raise ValueError("analysis parity tolerances must be finite and non-negative")
    return {
        "version": str(parsed["version"]),
        "absolute_tolerance": absolute,
        "relative_tolerance": relative,
        "numeric_analysis_fields": tuple(numeric_fields),
        "required_core_surfaces": _CORE_SURFACES,
        "portfolio_artifacts": _PORTFOLIO_ARTIFACTS,
    }


def analysis_parity_report_path(root: Path | None = None) -> Path:
    """Return the approved release report path under the discovered project root."""

    project = project_root() if root is None else project_root(start=root, cwd=root, env_root="")
    return project / "artifacts" / "release" / "latest" / "analysis-parity-report.json"


def write_parity_report(report: Mapping[str, object], path: str | Path) -> None:
    """Write a credential-sanitized parity report with the repository atomic writer."""

    sanitized = _redact_sensitive(report)
    if not isinstance(sanitized, Mapping):
        raise TypeError("parity report must be a mapping")
    if validate_parity_report(report):
        sanitized = dict(sanitized)
        sanitized["status"] = "failed"
        sanitized["release_status"] = "failed"
        sanitized["security"] = {
            "status": "failed",
            "field_paths": _redact_sensitive(validate_parity_report(report)),
        }
    atomic_write_json(Path(path), sanitized)


def canonical_snapshot_hash(payload: object) -> str:
    """Return the SHA-256 identity of one canonical OpportunityResult payload."""

    if isinstance(payload, OpportunityResult):
        canonical = opportunity_result_payload(payload)
    elif isinstance(payload, Mapping):
        canonical = dict(payload)
    else:
        raise TypeError("snapshot payload must be an OpportunityResult or mapping")
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("snapshot payload must contain finite JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def compare_source_package(
    source_runner: Callable[[], object] | None,
    packaged_runner: Callable[[], object] | None,
) -> dict[str, object]:
    """Run both entry points once and compare canonical snapshot hashes."""

    if source_runner is None:
        return {"status": "unavailable", "reason": "source entry point unavailable"}
    if packaged_runner is None:
        return {
            "status": "unavailable",
            "reason": "packaged entry point unavailable",
        }
    if not callable(source_runner) or not callable(packaged_runner):
        return {"status": "failed", "reason": "replay entry point is not callable"}
    try:
        source_hashes = _snapshot_hashes(source_runner())
        packaged_hashes = _snapshot_hashes(packaged_runner())
    except (TypeError, ValueError, KeyError) as exc:
        return {
            "status": "failed",
            "reason": f"snapshot replay invalid: {type(exc).__name__}",
        }
    mismatch = _compare_values(
        source_hashes,
        packaged_hashes,
        path="source_package.snapshot_hashes",
        absolute=0.0,
        relative=0.0,
        tolerances=[],
    )
    return {
        "status": "failed" if mismatch else "passed",
        "source_snapshot_hashes": source_hashes,
        "packaged_snapshot_hashes": packaged_hashes,
        "first_mismatch": mismatch,
        "reason": None if mismatch is None else "source and packaged snapshot hashes differ",
    }


def build_parity_report(
    evidence: Mapping[str, object] | None,
    *,
    portfolio: Mapping[str, object] | None = None,
    proposal_order: Mapping[str, object] | None = None,
    source_runner: Callable[[], object] | None = None,
    packaged_runner: Callable[[], object] | None = None,
    config_path: str | Path = _CONFIG_PATH,
) -> dict[str, object]:
    """Compare supplied workflow evidence and emit the machine-readable v2 report.

    A release report is ``passed`` only when all four lanes pass. Missing lane
    evidence is ``incomplete``; an observed mismatch or secret-bearing field is
    ``failed``. The core lane is assessed solely from detail, bulk, and holdings.
    """

    config = load_analysis_parity_config(config_path)
    absolute = float(config["absolute_tolerance"])
    relative = float(config["relative_tolerance"])
    numeric_fields = tuple(config["numeric_analysis_fields"])
    tolerance_uses: list[dict[str, object]] = []
    core = _compare_core_surfaces(
        evidence,
        absolute=absolute,
        relative=relative,
        numeric_fields=numeric_fields,
        tolerance_uses=tolerance_uses,
    )
    portfolio_lane = _compare_portfolio(portfolio)
    proposal_lane = _compare_proposal_order(
        proposal_order, core, portfolio, portfolio_lane
    )
    package_lane = compare_source_package(source_runner, packaged_runner)
    secret_paths = _sensitive_input_paths(evidence, "evidence")
    secret_paths.extend(_sensitive_input_paths(portfolio, "portfolio"))
    secret_paths.extend(_sensitive_input_paths(proposal_order, "proposal_order"))
    security = {"status": "failed" if secret_paths else "passed", "field_paths": secret_paths}

    lanes = {
        "core_analysis": core,
        "portfolio": portfolio_lane,
        "proposal_order": proposal_lane,
        "source_package": package_lane,
    }
    statuses = [str(lane.get("status", "unavailable")) for lane in lanes.values()]
    if security["status"] == "failed" or "failed" in statuses:
        overall = "failed"
    elif all(status == "passed" for status in statuses):
        overall = "passed"
    else:
        overall = "incomplete"
    first_mismatch = next(
        (
            lane["first_mismatch"]
            for lane in lanes.values()
            if isinstance(lane.get("first_mismatch"), Mapping)
        ),
        None,
    )
    if secret_paths and first_mismatch is None:
        first_mismatch = {
            "stage": "report_security",
            "path": "sensitive_input_field",
            "dependency_path": ["workflow_evidence", "machine_readable_report"],
        }
    report: dict[str, object] = {
        "schema_version": 2,
        "status": overall,
        "release_status": overall,
        "execution_allowed": False,
        "policy_version": config["version"],
        "lanes": lanes,
        "first_mismatch": first_mismatch,
        "dependency_graph": _DEPENDENCY_GRAPH,
        "tolerances": {
            "absolute": absolute,
            "relative": relative,
            "numeric_analysis_fields": list(numeric_fields),
            "uses": tolerance_uses,
        },
        "mutation_catalogue": _mutation_catalogue(core, package_lane, secret_paths),
        "security": security,
    }
    report_secrets = validate_parity_report(report)
    if report_secrets:
        report["status"] = "failed"
        report["release_status"] = "failed"
        report["security"] = {"status": "failed", "field_paths": report_secrets}
    sanitized = _redact_sensitive(report)
    assert isinstance(sanitized, dict)
    return sanitized


def validate_parity_report(report: Mapping[str, object]) -> list[str]:
    """Return paths containing credential field names or recognizable secrets."""

    return _sensitive_input_paths(report, "report")


_DEPENDENCY_GRAPH = {
    "analysis_snapshot": ["detail", "bulk", "holdings"],
    "portfolio": ["ledger", "performance_series", "csv_export"],
    "proposal_order": ["analysis_snapshot", "portfolio_snapshot", "policy_snapshot"],
    "source_package": ["source_run", "packaged_run", "snapshot_hashes"],
}


def _compare_core_surfaces(
    evidence: Mapping[str, object] | None,
    *,
    absolute: float,
    relative: float,
    numeric_fields: Sequence[str],
    tolerance_uses: list[dict[str, object]],
) -> dict[str, object]:
    if not isinstance(evidence, Mapping):
        return _unavailable_lane("frozen workflow evidence unavailable")
    surfaces: dict[str, dict[str, dict[str, object]]] = {}
    snapshot_hashes: dict[str, dict[str, str]] = {}
    for surface in _CORE_SURFACES:
        raw = evidence.get(surface)
        if raw is None:
            return _unavailable_lane(f"{surface} surface unavailable")
        try:
            surfaces[surface] = _surface_rows(raw)
            for instrument, row in sorted(surfaces[surface].items()):
                reason = _core_evidence_reason(instrument, row)
                if reason is not None:
                    return {
                        "status": "failed",
                        "reason": f"{surface} canonical evidence invalid: {reason}",
                        "first_mismatch": {
                            "stage": "canonical_evidence",
                            "path": f"analysis.{surface}.{instrument}",
                            "dependency_path": [
                                "OpportunityResult",
                                f"{surface}.identity_versions_sources_action_blockers",
                            ],
                        },
                    }
            snapshot_hashes[surface] = {
                key: canonical_snapshot_hash(_analysis_payload(row))
                for key, row in sorted(surfaces[surface].items())
            }
        except (TypeError, ValueError, KeyError) as exc:
            return {
                "status": "failed",
                "reason": f"{surface} replay invalid: {type(exc).__name__}",
                "first_mismatch": {
                    "stage": "analysis_snapshot",
                    "path": surface,
                    "dependency_path": ["analysis_snapshot", surface],
                },
            }
        for instrument, row in sorted(surfaces[surface].items()):
            supplied_identity = row.get("snapshot_id")
            expected_identity = snapshot_hashes[surface][instrument]
            if supplied_identity != expected_identity:
                return {
                    "status": "failed",
                    "snapshot_hashes": snapshot_hashes,
                    "first_mismatch": {
                        "stage": "analysis_snapshot_identity",
                        "path": f"analysis.{surface}.{instrument}.snapshot_id",
                        "dependency_path": [
                            "opportunity_result_payload.sha256",
                            f"{surface}.snapshot_id",
                        ],
                    },
                }
    reference_name = _CORE_SURFACES[0]
    # Each surface identity is first checked against its own canonical payload.
    # Cross-surface numeric analysis fields then use the declared tolerance;
    # including the payload hash again here would make that tolerance inert.
    reference = {
        instrument: {key: value for key, value in row.items() if key != "snapshot_id"}
        for instrument, row in surfaces[reference_name].items()
    }
    for surface in _CORE_SURFACES[1:]:
        candidate = {
            instrument: {key: value for key, value in row.items() if key != "snapshot_id"}
            for instrument, row in surfaces[surface].items()
        }
        mismatch = _compare_values(
            reference,
            candidate,
            path=f"analysis.{surface}",
            absolute=absolute,
            relative=relative,
            numeric_fields=numeric_fields,
            tolerances=tolerance_uses,
        )
        if mismatch is not None:
            mismatch["stage"] = "analysis_surface_parity"
            mismatch["dependency_path"] = [
                "analysis_snapshot",
                f"{reference_name}.opportunity_result_payload",
                f"{surface}.opportunity_result_payload",
            ]
            return {
                "status": "failed",
                "snapshot_hashes": snapshot_hashes,
                "first_mismatch": mismatch,
            }
    return {
        "status": "passed",
        "snapshot_hashes": snapshot_hashes,
        "first_mismatch": None,
    }


def _core_evidence_reason(instrument: str, row: Mapping[str, object]) -> str | None:
    try:
        payload = _analysis_payload(row)
    except (TypeError, ValueError, KeyError):
        return "canonical OpportunityResult payload is missing"
    required_payload = (
        "instrument",
        "schema_version",
        "formula_version",
        "source_vintage_hash",
        "status",
        "reason_code",
    )
    missing_payload = [
        name
        for name in required_payload
        if name not in payload or payload.get(name) in (None, "")
    ]
    if missing_payload:
        return f"canonical payload field is missing: {missing_payload[0]}"
    if payload.get("instrument") != instrument or row.get("instrument") != instrument:
        return "canonical instrument identity is missing or mismatched"

    versions = row.get("versions")
    if not isinstance(versions, Mapping):
        return "versions are missing"
    for name in ("schema_version", "formula_version"):
        if name not in versions:
            return f"version field is missing: {name}"
        if versions[name] != payload[name] or type(versions[name]) is not type(payload[name]):
            return f"version field is mismatched: {name}"

    for field, payload_field in (
        ("sources", "source_vintage_hash"),
        ("actions", "status"),
        ("blockers", "reason_code"),
    ):
        values = row.get(field)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return f"{field} are missing"
        expected = [payload[payload_field]]
        if list(values) != expected:
            return f"{field} do not bind to the canonical payload"
    if not isinstance(row.get("snapshot_id"), str) or not row["snapshot_id"].strip():
        return "snapshot identity is missing"
    return None


def _surface_rows(surface: object) -> dict[str, dict[str, object]]:
    raw_rows: object = surface
    if isinstance(surface, Mapping):
        if "results" in surface:
            raw_rows = surface["results"]
        elif "rows" in surface:
            raw_rows = surface["rows"]
        elif "instrument" in surface or "analysis" in surface or "opportunity" in surface:
            raw_rows = [surface]
        else:
            raw_rows = list(surface.values())
    if isinstance(raw_rows, Mapping):
        raw_rows = list(raw_rows.values())
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise TypeError("surface rows must be a sequence or mapping")
    result: dict[str, dict[str, object]] = {}
    for raw in raw_rows:
        if isinstance(raw, OpportunityResult):
            row = {"analysis": opportunity_result_payload(raw)}
        elif isinstance(raw, Mapping):
            row = dict(raw)
        else:
            raise TypeError("surface row must be an OpportunityResult or mapping")
        identity = _analysis_payload(row).get("instrument", row.get("instrument"))
        if not isinstance(identity, str) or not identity.strip() or identity in result:
            raise ValueError("surface rows require unique instrument identities")
        result[identity] = row
    if not result:
        raise ValueError("surface has no replay rows")
    return result


def _analysis_payload(row: Mapping[str, object]) -> Mapping[str, object]:
    payload = row.get("analysis", row.get("opportunity", row))
    if isinstance(payload, OpportunityResult):
        return opportunity_result_payload(payload)
    if not isinstance(payload, Mapping):
        raise TypeError("surface row has no canonical analysis payload")
    return payload


def _compare_portfolio(evidence: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(evidence, Mapping):
        return _unavailable_lane("portfolio replay evidence unavailable")
    missing = [name for name in _PORTFOLIO_ARTIFACTS if not isinstance(evidence.get(name), Mapping)]
    if missing:
        return {
            "status": "not_yet_available",
            "reason": f"portfolio evidence unavailable: {', '.join(missing)}",
            "first_mismatch": None,
        }
    ledger = evidence["ledger"]
    performance = evidence["performance_series"]
    export = evidence["csv_export"]
    assert isinstance(ledger, Mapping) and isinstance(performance, Mapping) and isinstance(export, Mapping)
    try:
        csv_rows = _parse_csv_rows(export.get("content"))
    except (TypeError, ValueError, csv.Error):
        return _failed_lane("portfolio.csv_export", "CSV export could not be parsed")
    ledger_totals = ledger.get("totals")
    performance_totals = performance.get("totals")
    ledger_dates = ledger.get("dates")
    performance_dates = performance.get("dates")
    performance_rows = performance.get("rows")
    if not isinstance(ledger_totals, Mapping) or not isinstance(performance_totals, Mapping):
        return _failed_lane("portfolio.totals", "ledger or performance totals are unavailable")
    if not isinstance(ledger_dates, Sequence) or isinstance(ledger_dates, (str, bytes)):
        return _failed_lane("portfolio.dates", "ledger dates are unavailable")
    if not isinstance(performance_dates, Sequence) or isinstance(performance_dates, (str, bytes)):
        return _failed_lane("portfolio.dates", "performance dates are unavailable")
    if not isinstance(performance_rows, Sequence) or isinstance(performance_rows, (str, bytes)):
        return _failed_lane("portfolio.performance_series", "performance rows are unavailable")
    if not csv_rows:
        return _failed_lane("portfolio.csv_export", "CSV export has no data rows")

    # The export's declared totals are not evidence. Compare each supplied
    # performance total with the corresponding value in the parsed final row.
    csv_summary: dict[str, object] = {}
    for field in performance_totals:
        if field not in csv_rows[-1]:
            return _failed_lane(
                f"portfolio.csv_export.{field}",
                "CSV export does not contain the performance summary field",
            )
        csv_summary[str(field)] = csv_rows[-1][field]
    comparison = {
        "totals": {
            "ledger": ledger_totals,
            "performance_series": performance_totals,
            "csv_export_content": csv_summary,
        },
        "dates": {
            "ledger": list(ledger_dates),
            "performance_series": list(performance_dates),
            "csv_export": [row.get("date", row.get("period_end")) for row in csv_rows],
        },
        "performance_rows": {
            "performance_series": _normalise_empty_numbers(performance_rows),
            "csv_export": csv_rows,
        },
    }
    tolerance_uses: list[dict[str, object]] = []
    for field in ("totals", "dates", "performance_rows"):
        group = comparison[field]
        assert isinstance(group, Mapping)
        reference_name = "ledger" if field != "performance_rows" else "performance_series"
        reference = group.get(reference_name)
        for name, value in group.items():
            if name == reference_name:
                continue
            mismatch = _compare_values(
                reference,
                value,
                path=f"portfolio.{field}.{name}",
                absolute=0,
                relative=0,
                numeric_fields=(),
                tolerances=tolerance_uses,
            )
            if mismatch is not None:
                mismatch["stage"] = "portfolio_reconciliation"
                mismatch["dependency_path"] = [
                    "portfolio.ledger",
                    "portfolio.performance_series",
                    "portfolio.csv_export",
                ]
                return {"status": "failed", "first_mismatch": mismatch}
    if not ledger_totals or not ledger_dates:
        return _failed_lane("portfolio.ledger", "ledger totals or dates are unavailable")
    return {"status": "passed", "first_mismatch": None}


def _parse_csv_rows(content: object) -> list[dict[str, object]]:
    if not isinstance(content, str) or not content:
        raise ValueError("CSV content is unavailable")
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames or not ({"date", "period_end"} & set(reader.fieldnames)):
        raise ValueError("CSV export requires a date or period_end column")
    rows = []
    for raw in reader:
        row: dict[str, object] = {}
        for key, value in raw.items():
            if key is None:
                raise ValueError("CSV export row has extra values")
            if key in {"date", "period_start", "period_end"}:
                row[key] = value
            else:
                row[key] = _csv_value(value)
        rows.append(row)
    return rows


def _csv_value(value: str | None) -> object:
    if value is None or value == "":
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    try:
        number = float(value)
    except ValueError:
        return value
    return number if math.isfinite(number) else value


def _normalise_empty_numbers(value: object) -> object:
    """Match pandas' exported blank cells to the equivalent CSV empty value."""

    if isinstance(value, Mapping):
        return {key: _normalise_empty_numbers(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalise_empty_numbers(item) for item in value]
    if isinstance(value, Real) and not isinstance(value, bool) and math.isnan(float(value)):
        return None
    return value


def _compare_proposal_order(
    evidence: Mapping[str, object] | None,
    core: Mapping[str, object],
    portfolio: Mapping[str, object] | None,
    portfolio_lane: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(evidence, Mapping):
        return _unavailable_lane("proposal and order lineage unavailable")
    proposals = evidence.get("proposals")
    if not isinstance(proposals, Sequence) or isinstance(proposals, (str, bytes)):
        return _failed_lane("proposal_order.proposals", "proposal lineage evidence is missing")
    if not proposals:
        return _unavailable_lane("no proposal or order lineage to replay")
    if core.get("status") != "passed":
        return _failed_lane(
            "proposal_order.analysis_snapshot_id",
            "canonical analysis snapshot identity is unavailable because core parity did not pass",
        )
    if portfolio_lane.get("status") != "passed":
        return _failed_lane(
            "proposal_order.portfolio_snapshot_id",
            "portfolio snapshot identity is unavailable because portfolio reconciliation did not pass",
        )
    hashes = core.get("snapshot_hashes")
    detail_hashes = hashes.get("detail") if isinstance(hashes, Mapping) else None
    if not isinstance(detail_hashes, Mapping):
        return _failed_lane("proposal_order.analysis_snapshot_id", "verified analysis identities are missing")
    portfolio_id = portfolio.get("portfolio_snapshot_id") if isinstance(portfolio, Mapping) else None
    policy_evidence = evidence.get("policy_evidence")
    policy_id = policy_evidence.get("snapshot_id") if isinstance(policy_evidence, Mapping) else None
    if not isinstance(portfolio_id, str) or not portfolio_id.strip():
        return _failed_lane("proposal_order.portfolio_snapshot_id", "portfolio snapshot identity is missing")
    if not isinstance(policy_id, str) or not policy_id.strip():
        return _failed_lane("proposal_order.policy_snapshot_id", "policy snapshot evidence is missing")
    required = ("analysis_snapshot_id", "portfolio_snapshot_id", "policy_snapshot_id")
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, Mapping):
            return _failed_lane(
                "proposal_order.lineage",
                f"proposal {index} has no snapshot lineage",
            )
        instrument = proposal.get("instrument", proposal.get("instrument_id"))
        analysis_id = detail_hashes.get(instrument) if isinstance(instrument, str) else None
        if not isinstance(analysis_id, str):
            return _failed_lane(
                f"proposal_order.proposals[{index}].instrument",
                f"proposal {index} does not identify a reviewed analysis snapshot",
            )
        expected = {
            "analysis_snapshot_id": analysis_id,
            "portfolio_snapshot_id": portfolio_id,
            "policy_snapshot_id": policy_id,
        }
        for identity in required:
            if not isinstance(proposal.get(identity), str) or proposal[identity] != expected[identity]:
                return {
                    "status": "failed",
                    "reason": "proposal snapshot binding is missing or mismatched",
                    "first_mismatch": {
                        "stage": "proposal_order_lineage",
                        "path": f"proposal_order.proposals[{index}].{identity}",
                        "dependency_path": [
                            "analysis_snapshot",
                            "portfolio_snapshot",
                            "policy_snapshot",
                            f"proposal_order.proposals[{index}]",
                        ],
                    },
                }
    if not proposals:
        return _unavailable_lane("no proposal or order lineage to replay")
    return {"status": "passed", "first_mismatch": None}


def _snapshot_hashes(run: object) -> dict[str, str]:
    if isinstance(run, Mapping) and "results" in run:
        values = run["results"]
    elif isinstance(run, Mapping) and "instrument" not in run:
        values = run
    else:
        values = [run]
    rows: list[tuple[str, object]] = []
    if isinstance(values, Mapping):
        rows = [(str(key), value) for key, value in values.items()]
    elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for value in values:
            if not isinstance(value, Mapping):
                raise TypeError("replay rows must be mappings")
            identity = value.get("instrument")
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("replay row has no instrument identity")
            rows.append((identity, value))
    else:
        raise TypeError("replay results must be a mapping or sequence")
    hashes: dict[str, str] = {}
    for identity, value in rows:
        if isinstance(value, Mapping) and "analysis" in value:
            value = value["analysis"]
        if isinstance(value, Mapping) and "opportunity" in value:
            value = value["opportunity"]
        if identity in hashes or not identity.strip():
            raise ValueError("replay contains duplicate or empty instrument identities")
        hashes[identity] = canonical_snapshot_hash(value)
    if not hashes:
        raise ValueError("replay has no snapshots")
    return dict(sorted(hashes.items()))


def _compare_values(
    expected: object,
    actual: object,
    *,
    path: str,
    absolute: float,
    relative: float,
    tolerances: list[dict[str, object]],
    numeric_fields: Sequence[str] = (),
) -> dict[str, object] | None:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return None if expected is actual else {"path": path}
    if isinstance(expected, Real) and isinstance(actual, Real):
        path_fields = set(re.split(r"[.\[\]]+", path))
        if not path_fields.intersection(numeric_fields):
            return (
                None
                if type(expected) is type(actual) and expected == actual
                else {"path": path}
            )
        left, right = float(expected), float(actual)
        passed = math.isfinite(left) and math.isfinite(right) and abs(left - right) <= (
            absolute + relative * max(abs(left), abs(right))
        )
        tolerances.append(
            {
                "path": path,
                "absolute": absolute,
                "relative": relative,
                "passed": passed,
            }
        )
        return None if passed else {"path": path}
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        expected_keys, actual_keys = set(expected), set(actual)
        for key in sorted(expected_keys | actual_keys, key=str):
            child = f"{path}.{key}"
            if key not in expected_keys or key not in actual_keys:
                return {"path": child}
            mismatch = _compare_values(
                expected[key],
                actual[key],
                path=child,
                absolute=absolute,
                relative=relative,
                tolerances=tolerances,
                numeric_fields=numeric_fields,
            )
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(expected, Sequence) and isinstance(actual, Sequence) and not isinstance(
        expected, (str, bytes)
    ) and not isinstance(actual, (str, bytes)):
        if len(expected) != len(actual):
            return {"path": path}
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            mismatch = _compare_values(
                left,
                right,
                path=f"{path}[{index}]",
                absolute=absolute,
                relative=relative,
                tolerances=tolerances,
                numeric_fields=numeric_fields,
            )
            if mismatch is not None:
                return mismatch
        return None
    return None if expected == actual else {"path": path}


def _mutation_catalogue(
    core: Mapping[str, object],
    package: Mapping[str, object],
    secret_paths: Sequence[str],
) -> list[dict[str, str]]:
    mismatch = core.get("first_mismatch")
    mismatch_path = str(mismatch.get("path", "")).lower() if isinstance(mismatch, Mapping) else ""
    entries = [
        ("alternative_calculation", "first divergent analysis payload field"),
        ("current_spot_future_conversion", "conversion-basis parity across surfaces"),
        ("silent_depth_downgrade", "analysis depth and depth-manifest parity"),
        ("plain_text_api_key", "sensitive-field and report validation"),
    ]
    report = [
        {
            "mutation": mutation,
            "status": (
                "detected"
                if (
                    (mutation == "alternative_calculation" and core.get("status") == "failed")
                    or (mutation == "current_spot_future_conversion" and any(k in mismatch_path for k in ("future", "conversion", "currency", "fx")))
                    or (mutation == "silent_depth_downgrade" and any(k in mismatch_path for k in ("depth", "manifest")))
                    or (mutation == "plain_text_api_key" and bool(secret_paths))
                )
                else "not_observed"
            ),
            "guard": guard,
        }
        for mutation, guard in entries
    ]
    report.extend(
        [
            {
                "mutation": "bank_versus_tech_peer_pooling",
                "status": "not_yet_available",
                "reason": "peer risk profiles are outside the available ISSUE-0174 surfaces",
            },
            {
                "mutation": "hard_coded_vwce_risk",
                "status": "not_yet_available",
                "reason": "VWCE risk-profile evidence is outside the available ISSUE-0174 surfaces",
            },
        ]
    )
    if package.get("status") == "failed":
        report.append(
            {
                "mutation": "source_package_snapshot_divergence",
                "status": "detected",
                "guard": "source and packaged snapshot hashes compared",
            }
        )
    return report


def _sensitive_input_paths(value: object, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            if (
                _SENSITIVE_FIELD.search(key_text)
                and child not in (None, "", False)
            ) or _SECRET_VALUE.search(key_text) or _CREDENTIAL_ASSIGNMENT.search(key_text):
                found.append(child_path)
            found.extend(_sensitive_input_paths(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            found.extend(_sensitive_input_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (_SECRET_VALUE.search(value) or _CREDENTIAL_ASSIGNMENT.search(value)):
        found.append(path)
    return found


def _redact_sensitive(value: object, *, field_name: str = "") -> object:
    if _SENSITIVE_FIELD.search(field_name) and value not in (None, "", False):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        redacted: dict[object, object] = {}
        for key, child in value.items():
            safe_key = _redact_text(str(key)) if isinstance(key, str) else key
            redacted[safe_key] = _redact_sensitive(child, field_name=str(key))
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_redact_sensitive(child) for child in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    value = _SECRET_VALUE.sub("[REDACTED]", value)
    return _CREDENTIAL_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def _unavailable_lane(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "reason": reason, "first_mismatch": None}


def _failed_lane(path: str, reason: str) -> dict[str, object]:
    return {
        "status": "failed",
        "reason": reason,
        "first_mismatch": {
            "stage": path.split(".", 1)[0],
            "path": path,
            "dependency_path": [path],
        },
    }


__all__ = [
    "analysis_parity_report_path",
    "build_parity_report",
    "canonical_snapshot_hash",
    "compare_source_package",
    "load_analysis_parity_config",
    "validate_parity_report",
    "write_parity_report",
]
