from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config
from etf_cockpit.services import FeatureService, SignalService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="latest")
    args = parser.parse_args()
    config = load_config()
    features = FeatureService(config).compute_features()
    signals = SignalService(config).generate_signals(features=features)
    for signal in signals:
        print(f"{signal.etf_id:16s} {signal.action:13s} confidence={signal.confidence:.2f} score={signal.total_score:+.2f} blocked={','.join(signal.blocked_by) or '-'}")


if __name__ == "__main__":
    main()
