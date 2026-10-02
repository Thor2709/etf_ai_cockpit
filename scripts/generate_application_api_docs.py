"""Generate the checked-in local application API schema and short guide."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etf_cockpit.application import contracts


def _render(root: Path) -> tuple[tuple[Path, bytes], tuple[Path, bytes]]:
    destination = root / "docs" / "architecture"
    names = [
        "ApiStatus",
        "CancelWorkflowCommand",
        "CommandResult",
        "ForecastViewModel",
        "InstrumentViewModel",
        "JobViewModel",
        "OperationViewModel",
        "PageRequest",
        "PageView",
        "PaperAccountOpenRequest",
        "PaperCorporateActionRequest",
        "PaperFillRequest",
        "PaperOrderCancelRequest",
        "PaperOrderViewModel",
        "PaperPositionMarkRequest",
        "PaperPositionViewModel",
        "PaperProposalAcceptRequest",
        "PaperProposalDecisionViewModel",
        "PaperProposalRejectRequest",
        "PaperViewModel",
        "PortfolioViewModel",
        "ProposalGateEvidence",
        "ProposalGateViewModel",
        "ProposalReviewRequest",
        "ProposalViewModel",
        "QueryRequest",
        "RefreshDataCommand",
        "ScoreViewModel",
        "SubmitWorkflowCommand",
    ]
    schemas = {
        name: {"type": "string", "enum": [status.value for status in contracts.ApiStatus]}
        if name == "ApiStatus"
        else getattr(contracts, name).model_json_schema()
        for name in names
    }
    schema = {
        "schema_version": contracts.APPLICATION_API_SCHEMA_VERSION,
        "transport": "in_process",
        "execution_allowed": False,
        "models": schemas,
    }
    schema_path = destination / "application-api-schema.json"
    # Keep generated artefacts byte-stable with the repository's Windows checkout
    # convention, independent of the platform running the generator.
    schema_bytes = (json.dumps(schema, indent=2, sort_keys=True) + "\n").replace(
        "\n", "\r\n"
    ).encode("utf-8")
    lines = [
        "# Local application API",
        "",
        f"This document is generated from `etf_cockpit.application.contracts` (`{contracts.APPLICATION_API_SCHEMA_VERSION}`). The first transport is local in-process; no HTTP listener or cloud service is enabled.",
        "",
        "## Query resources",
        "",
        "`QueryRequest.resource` supports `universe`, `instruments`, `scores`, `forecasts`, `portfolios`, `jobs`, `paper`, `proposals` and `operations`. Each query returns an immutable `PageView` with `total`, `offset`, `limit` and `next_offset`. Proposal review creation uses the typed `ProposalReviewRequest` through the same local boundary and returns gate evidence with execution disabled. Paper account opening and proposal actions use typed local contracts backed by the append-only paper ledger.",
        "",
        "## Commands",
        "",
        "`RefreshDataCommand`, `SubmitWorkflowCommand` and `CancelWorkflowCommand` require an idempotency key. Commands may include an expected revision; stale revisions return `conflict` and never run. Repeating the same key and payload returns `replayed` without running the handler again.",
        "",
        "## Boundary rules",
        "",
        "- Query adapters expose serialisable view models and never return pandas frames or domain objects.",
        "- Pages use the in-process API; durable job state remains in the existing local scheduler.",
        "- No command grants broker or execution authority; `execution_allowed` remains `false`.",
        "- Paper fills use explicit execution quotes; account marks require adjusted-close evidence and remain local simulation only.",
        "- The JSON schema beside this document is the contract artefact for a second local frontend.",
        "",
    ]
    guide_path = destination / "application-api.md"
    guide_bytes = "\n".join(lines).replace("\n", "\r\n").encode("utf-8")
    return (schema_path, schema_bytes), (guide_path, guide_bytes)


def generate(root: Path) -> tuple[Path, Path]:
    rendered = _render(root)
    for path, content in rendered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"WROTE: {path}")
    return rendered[0][0], rendered[1][0]


def check(root: Path) -> bool:
    clean = True
    for path, expected in _render(root):
        try:
            actual = path.read_bytes()
        except FileNotFoundError:
            actual = b""
        if actual != expected:
            clean = False
            expected_lines = expected.splitlines()
            actual_lines = actual.splitlines()
            first_difference = next(
                (
                    index
                    for index, (expected_line, actual_line) in enumerate(
                        zip(expected_lines, actual_lines), start=1
                    )
                    if expected_line != actual_line
                ),
                min(len(expected_lines), len(actual_lines)) + 1,
            )
            expected_line = (
                expected_lines[first_difference - 1].decode("utf-8", errors="replace")
                if first_difference <= len(expected_lines)
                else "<end of generated file>"
            )
            actual_line = (
                actual_lines[first_difference - 1].decode("utf-8", errors="replace")
                if first_difference <= len(actual_lines)
                else "<end of file>"
            )
            print(f"STALE: {path}")
            print(f"first differing line {first_difference}: expected: {expected_line}")
            print(f"actual: {actual_line}")
    if clean:
        print("OK: application API documentation is up to date")
    return clean


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return 0 if check(args.root.resolve()) else 1
    generate(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
