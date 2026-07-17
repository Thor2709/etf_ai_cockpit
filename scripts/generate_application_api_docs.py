"""Generate the checked-in local application API schema and short guide."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etf_cockpit.application import contracts


def generate(root: Path) -> tuple[Path, Path]:
    destination = root / "docs" / "architecture"
    destination.mkdir(parents=True, exist_ok=True)
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
        "PaperViewModel",
        "PortfolioViewModel",
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
    schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Local application API",
        "",
        f"This document is generated from `etf_cockpit.application.contracts` (`{contracts.APPLICATION_API_SCHEMA_VERSION}`). The first transport is local in-process; no HTTP listener or cloud service is enabled.",
        "",
        "## Query resources",
        "",
        "`QueryRequest.resource` supports `universe`, `instruments`, `scores`, `forecasts`, `portfolios`, `jobs`, `paper` and `operations`. Each query returns an immutable `PageView` with `total`, `offset`, `limit` and `next_offset`.",
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
        "- The JSON schema beside this document is the contract artefact for a second local frontend.",
        "",
    ]
    guide_path = destination / "application-api.md"
    guide_path.write_text("\n".join(lines), encoding="utf-8")
    return schema_path, guide_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    schema_path, guide_path = generate(args.root.resolve())
    print(f"WROTE: {schema_path}")
    print(f"WROTE: {guide_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
