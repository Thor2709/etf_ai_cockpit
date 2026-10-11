"""Deterministic score invariants for one data root.
Usage: ETF_COCKPIT_ROOT=<root> PYTHONPATH=<wt>/src python score_invariants.py [owner_holdings.csv] [--table]"""
import csv, math, os, sys
from datetime import date
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.score_views import snapshot_scores, score_coverage
from etf_cockpit.signals import simple_scores as ss

fails, warns = [], []
snap = build_snapshot()
scores = snapshot_scores(snap, penalise_missing=False)
again = snapshot_scores(snap, penalise_missing=False)
ids = [s.display_id for s in scores]
# 1 deterministic
if [(s.display_id, s.final_score_10) for s in scores] != [(s.display_id, s.final_score_10) for s in again]:
    fails.append("non-deterministic scores between two identical calls")
# 2 no duplicates (candidate rows for configured ids count as duplicates)
base = [i.split(":", 1)[-1] for i in ids]
dups = sorted({b for b in base if base.count(b) > 1})
if dups: fails.append(f"duplicate rows: {dups}")
# 3 every enabled configured instrument listed
cfg_ids = {e.id for e in snap.config.universe.etfs if getattr(e, "enabled", True)}
missing = sorted(cfg_ids - set(base))
if missing: fails.append(f"configured but not listed: {missing}")
# 4 range / reason
today = date.today().isoformat()
for s in scores:
    v = s.final_score_10
    if v is None:
        if not (s.one_line_reason or "").strip(): fails.append(f"{s.display_id}: no score and no reason")
        else: warns.append(f"{s.display_id}: no score - {s.one_line_reason[:90]}")
    elif not (0 <= v <= 10) or math.isnan(v): fails.append(f"{s.display_id}: score {v} out of range")
    if str(s.latest_date or "")[:4].isdigit() and str(s.latest_date)[:10] > today: fails.append(f"{s.display_id}: price date {s.latest_date} after today")
# 5 F5 forecasts separate from scores
for name in ("ETF_EVIDENCE_WEIGHTS", "STOCK_EVIDENCE_WEIGHTS"):
    w = getattr(ss, name, {})
    bad = {k: w[k] for k in ("baseline", "timesfm", "toto") if w.get(k)}
    if bad: fails.append(f"F5: {name} weights forecasts {bad}")
# 6 relative strength availability
rs = [c for s in scores for c in s.components if c.key.startswith("relative_strength")]
rs_ok = sum(1 for c in rs if c.score_10 is not None)
if rs and rs_ok == 0: fails.append("relative strength unavailable for every instrument")
# 7 identity vs owner holdings
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    byisin = {s.isin: s for s in scores if s.isin}
    with open(args[0], encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            isin = (row.get("isin") or row.get("ISIN") or "").strip()
            if isin and isin not in byisin: warns.append(f"owner ISIN {isin} ({(row.get('name') or row.get('Name') or '')[:30]}) not scored")
print(f"rows {len(scores)} scored {sum(s.final_score_10 is not None for s in scores)} | RS available {rs_ok}/{len(rs)}")
if "--table" in sys.argv:
    for s in sorted(scores, key=lambda s: -(s.final_score_10 or -1)):
        cov = score_coverage(s); r = next((c.score_10 for c in s.components if c.key.startswith("relative_strength")), None)
        print(f"  {s.display_id:16s} {s.asset_type:6s} {('%.2f' % s.final_score_10) if s.final_score_10 is not None else '  -  '} cov {('%.0f%%' % (cov*100)) if cov is not None else '-':>4} RS {r} {s.yahoo_symbol} {s.latest_date}")
for w in warns: print("WARN", w)
for f in fails: print("FAIL", f)
print("RESULT", "FAIL" if fails else "PASS", len(fails), "failures")
