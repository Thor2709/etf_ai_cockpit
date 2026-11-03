"""Live three-issuer cover probe; copy to C:/dev/queues/DATA/probe_cover.py.

Run outside the sandbox with network access and the SEC contact User-Agent set:
    python C:/dev/queues/DATA/probe_cover.py --repo C:/dev/fx-EVf1
Optional positional CIKs replace the three defaults. The source root is read only;
selected issuer caches are copied into a disposable temporary root before fetching.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    local = Path(__file__).resolve().parent
    parser.add_argument("--repo", type=Path, default=local if (local / "scripts/acquire_sp500.py").is_file()
                        else Path("C:/dev/fx-EVf1"))
    parser.add_argument("--root", type=Path, default=Path("C:/dev/queues/DATA/work2"))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sec-rate", type=float, default=8)
    parser.add_argument("--cover-cache-budget-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("ciks", nargs="*", default=["0000320193", "0001045810", "0000789019"])
    args = parser.parse_args(argv)
    if args.workers < 1 or not 0 < args.sec_rate <= 8 or args.cover_cache_budget_bytes < 1:
        parser.error("workers/budget must be positive; sec-rate must be positive and <=8")
    sys.path.insert(0, str(args.repo.resolve() / "src"))
    spec = importlib.util.spec_from_file_location("cover_probe_acquire", args.repo / "scripts/acquire_sp500.py")
    acq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acq)
    ciks = list(dict.fromkeys(acq.cik_text(cik) for cik in args.ciks))
    acq.LIMITERS["sec"] = acq.Limiter(args.sec_rate)
    source = args.root.resolve() / "data/raw/univ1_sp500"
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="sec-cover-probe-") as temporary:
        layout = acq.Layout(Path(temporary), cover_cache_budget=args.cover_cache_budget_bytes)
        try:
            cache = layout.cover_cache()
            cache.check()
            for cik in ciks:
                for path in (source / "sec/submissions").glob(f"CIK{cik}*.json"):
                    if path.stat().st_size > acq.COVER_FILE_CAP:
                        continue
                    meta = acq.recorded(path, source / "_meta/submissions")
                    if meta is not None:
                        cache.store(layout.subs / path.name, layout.subs_meta, path.read_bytes(),
                                    url=meta["url"], status=meta.get("http_status", 200))
            # Cover evidence is fetched afresh; never copy legacy full submissions.
        except acq.CoverRunAborted as exc:
            print(json.dumps({"status": "aborted", "reason": str(exc), "execution_allowed": False}), flush=True)
            return 1
        print(json.dumps({"temporary_root": temporary, "source_root": str(source),
                          "ciks": ciks, "workers": min(args.workers, len(ciks)), "execution_allowed": False}), flush=True)
        # Independent issuers run in threads; all network calls share one SEC limiter.
        with ThreadPoolExecutor(max_workers=min(args.workers, len(ciks))) as pool:
            pending = {pool.submit(acq.fetch_cover_issuer, (cik, layout)): cik for cik in ciks}
            for future in as_completed(pending):
                result = future.result()
                outcome = {"cik": result["cik"], "status": result["status"],
                           "evidence_count": len(result["evidence"]),
                           "identity_count": sum(bool(r["tickers"]) for r in result["evidence"]),
                           "bytes_downloaded": result["bytes_downloaded"],
                           "errors": result["errors"]}
                outcomes.append(outcome)
                print(json.dumps(outcome, sort_keys=True), flush=True)
    failed = [r["cik"] for r in outcomes if r["status"] == "failed"]
    print(json.dumps({"requested": len(ciks), "failed": failed}), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
