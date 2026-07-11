from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.core.closure import evaluate_issue, load_closure_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate issue closure evidence gates.")
    parser.add_argument("--matrix", type=Path, default=Path("configs/closure_matrix.yaml"))
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence/final"))
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    records = load_closure_matrix(args.matrix)
    evaluations = [evaluate_issue(record, args.evidence_root) for record in records]
    payload = {
        "matrix": str(args.matrix),
        "evidence_root": str(args.evidence_root),
        "issue_count": len(evaluations),
        "ready_count": sum(item.ready for item in evaluations),
        "issues": [
            {
                "issue_id": item.issue_id,
                "ready": item.ready,
                "missing_gates": list(item.missing_gates),
                "evidence_paths": list(item.evidence_paths),
            }
            for item in evaluations
        ],
    }
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if all(item.ready for item in evaluations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
