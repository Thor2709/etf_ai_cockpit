"""Research report export with a grounding check (INT-26).

Every number is rendered by ``format_metric`` from a ``Metric``; every claim carries a ``chunk_id`` citation.
Claim, commentary and title text is untrusted (document or model text): it is escaped and never carries
numeric authority. ``check_grounding`` re-renders each number and resolves each citation; any failure closes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import html
from pathlib import Path
import re

from etf_cockpit.analysis.stock_metrics import Metric
from etf_cockpit.application.stock_views import format_metric
from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.data import document_chunks


@dataclass(frozen=True)
class Claim:
    text: str
    chunk_id: str
    document_sha256: str


@dataclass(frozen=True)
class ResearchReport:
    title: str
    as_of: str  # UTC, the same text form as ``DocumentChunk.known_at``
    metrics: tuple[Metric, ...]
    claims: tuple[Claim, ...]
    commentary: str = ""
    currency: str | None = None


def build_research_report(
    title: str,
    as_of: str,
    metrics: Sequence[Metric],
    claims: Sequence[Claim] = (),
    *,
    commentary: str = "",
    currency: str | None = None,
) -> ResearchReport:
    parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("as_of must carry a time zone")
    keys = [metric.key for metric in metrics]
    if len(set(keys)) != len(keys):
        raise ValueError("metric keys must be unique")
    if not all(claim.chunk_id and claim.document_sha256 for claim in claims):
        raise ValueError("every claim needs a chunk_id and document_sha256")
    return ResearchReport(title, parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), tuple(metrics),
                          tuple(claims), commentary, currency)


def render_markdown(report: ResearchReport) -> str:
    lines = [f"# {_md(report.title)}", "", f"As of {report.as_of}", "", "## Numbers", ""]
    for metric in report.metrics:
        lines.append(f"- {_md(metric.label)}: {_metric_token(report, metric, False)} {_md(_detail(metric))}".rstrip())
    lines += ["", "## Claims", ""]
    lines += [f"- {_md(claim.text)} {_claim_token(claim, False)}" for claim in report.claims]
    if report.commentary:
        lines += ["", "## Commentary (model text, not numeric evidence)", "", f"> {_md(report.commentary)}"]
    return "\n".join(lines) + "\n"


def render_html(report: ResearchReport) -> str:
    esc = html.escape
    numbers = "".join(
        f"<li>{esc(metric.label)}: {_metric_token(report, metric, True)} <small>{esc(_detail(metric))}</small></li>"
        for metric in report.metrics
    )
    claims = "".join(f"<li>{esc(claim.text)} {_claim_token(claim, True)}</li>" for claim in report.claims)
    commentary = (
        f"<section class=\"commentary\"><h2>Commentary (model text, not numeric evidence)</h2><p>{esc(report.commentary)}</p></section>"
        if report.commentary else ""
    )
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{esc(report.title)}</title></head><body>"
        f"<h1>{esc(report.title)}</h1><p>As of {esc(report.as_of)}</p>"
        f"<h2>Numbers</h2><ul>{numbers}</ul><h2>Claims</h2><ul>{claims}</ul>{commentary}</body></html>\n"
    )


def check_grounding(report: ResearchReport, rendered: str, chunk_store: Path, *, html: bool = False) -> dict[str, object]:
    """Every number must be the metric's own rendering and every citation must resolve; any failure fails closed."""

    reasons = []
    tokens = [_metric_token(report, metric, html) for metric in report.metrics] + [_claim_token(claim, html) for claim in report.claims]
    for token, expected in Counter(tokens).items():
        if rendered.count(token) != expected:
            reasons.append(f"rendered text does not contain {token!r} exactly {expected} time(s)")
    for claim in report.claims:
        chunk = document_chunks.resolve(chunk_store, claim.chunk_id, claim.document_sha256)
        if chunk is None:
            reasons.append(f"citation {claim.chunk_id} does not resolve")
        elif chunk.known_at > report.as_of:
            reasons.append(f"citation {claim.chunk_id} was known after the report date")
    return {"status": "failed" if reasons else "ok", "reasons": reasons}


def write_report(report: ResearchReport, destination: Path, chunk_store: Path) -> dict[str, object]:
    """Write Markdown, or HTML for a ``.html`` destination, only when the grounding check passes."""

    as_html = destination.suffix.lower() == ".html"
    rendered = render_html(report) if as_html else render_markdown(report)
    grounding = check_grounding(report, rendered, chunk_store, html=as_html)
    if grounding["status"] != "ok":
        return {"status": "unavailable", "reasons": grounding["reasons"]}
    result = atomic_write_bytes(destination, rendered.encode("utf-8"), lambda path: path.read_bytes().decode("utf-8"))
    return {"status": "written", "path": str(result.destination), "sha256": result.sha256}


def _metric_token(report: ResearchReport, metric: Metric, as_html: bool) -> str:
    value = format_metric(metric, report.currency)
    if as_html:
        return f"<span data-metric=\"{html.escape(metric.key)}\">{html.escape(value)}</span>"
    return f"**{value}** `metric:{metric.key}`"


def _claim_token(claim: Claim, as_html: bool) -> str:
    if as_html:
        return f"<cite data-chunk=\"{html.escape(claim.chunk_id)}\">{html.escape(claim.chunk_id)}</cite>"
    return f"[cite:{claim.chunk_id}]"


def _detail(metric: Metric) -> str:
    parts = [metric.basis, metric.as_of, metric.source, None if metric.available else (metric.reason or metric.status)]
    return "(" + ", ".join(part for part in parts if part) + ")" if any(parts) else ""


def _md(text: str) -> str:
    """One line with Markdown and marker characters escaped, so untrusted text cannot forge a number or citation."""

    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", " ".join(str(text).split()))
