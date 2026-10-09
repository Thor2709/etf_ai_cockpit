"""Apply the owner-holdings identity fix to a canonical universe store (configs/universe_store.json).
Dry run by default; --apply backs the store up first and saves through universe_store.save_universe.
Usage: PYTHONPATH=<wt>/src python owner_identity_migration.py <root> <owner_holdings.csv> [--apply]"""
import csv, shutil, sys
from datetime import datetime
from pathlib import Path
from etf_cockpit.data import universe_store as us

V = "verified"
FIX = {
 "BA": dict(name="BAE Systems plc", isin="GB0002634946", ticker="BA.L", currency="GBP", asset_type="stock", region="United Kingdom", sector="Industrials", theme="Defence"),
 "AM": dict(name="Dassault Aviation SA", isin="FR0014004L86", ticker="AM.PA", currency="EUR", asset_type="stock", region="Europe", sector="Industrials", theme="Defence"),
 "HO": dict(name="Thales SA", isin="FR0000121329", ticker="HO.PA", currency="EUR", asset_type="stock", region="Europe", sector="Industrials", theme="Defence"),
 "KMAR": dict(name="Kongsberg Maritime ASA", isin="NO0013697029", ticker="KMAR.OL", currency="NOK", asset_type="stock", region="Europe", sector="Industrials", theme="Maritime technology"),
 "SEC0": dict(name="iShares MSCI Global Semiconductors UCITS ETF", isin="IE000I8KRLL9", ticker="SEC0.DE", currency="EUR", asset_type="etf", region="Global", sector="Technology", theme="Semiconductors"),
 "JEDI": dict(name="VanEck Space Innovators UCITS ETF", isin="IE000YU9K6K2", ticker="JEDI.DE", currency="EUR", asset_type="etf", region="Global", sector="Industrials", theme="Space", lifecycle=""),
 "SPCX": dict(name="Space Exploration Technologies Corp.", isin="US84615Q1031", ticker="SPCX", currency="USD", asset_type="stock", region="United States", sector="Industrials", theme="Space"),
 "EUDF": dict(name="WisdomTree Europe Defence UCITS ETF", isin="IE0002Y8CX98", ticker="EUDF.DE", currency="EUR", asset_type="etf", region="Europe", sector="Industrials", theme="Defence"),
 "EXUS": dict(name="Xtrackers MSCI World ex USA UCITS ETF", isin="IE0006WW1TQ4", ticker="EXUS.DE", currency="EUR", asset_type="etf", region="Global", sector="Broad", theme="World ex-USA equity"),
 "RABO": dict(name="Rabobank Certificaten", isin="XS1002121454", ticker="RABO.AS", currency="EUR", region="Europe", sector="Financials", theme="Bank capital securities"),
 "TKMS": dict(isin="DE000TKMS001"),
 "VFEM": dict(isin="IE00B3VVMM84", ticker="VFEM.AS", currency="EUR"),
 "VUSA": dict(isin="IE00B3XXRP09", ticker="VUSA.AS", currency="EUR"),
 "MORG": dict(isin="NO0012483207"),
}
root, owner_csv, apply = Path(sys.argv[1]), Path(sys.argv[2]), "--apply" in sys.argv
snap = us.load_universe(root)
records = tuple(snap.records)
by_id = {r.instrument_id: r for r in records}
owner_by_ticker = {row["ticker"].strip().upper(): row for row in csv.DictReader(open(owner_csv, encoding="utf-8")) if row.get("ticker")}
changes = {}
by_ticker = {r.ticker.upper(): r for r in records}
for iid, fix in FIX.items():
    if iid not in by_id:
        continue
    target = by_ticker.get(str(fix.get("ticker", "")).upper())
    if target is not None and target.instrument_id != iid:
        # The correct instrument already exists as its own record: the guessed legacy record is
        # disabled (history kept, nothing deleted) so the wrong company is no longer scored.
        changes[iid] = dict(enabled=False, notes=f"Disabled 2026-10-09: wrong identity guess; the owner's instrument is {target.instrument_id}.")
    else:
        changes[iid] = dict(fix, isin_status=V, **({"enabled": True} if iid in {"JEDI", "RABO"} else {}))
for r in records:  # ISINs from the owner file for exact ticker matches still unverified
    row = owner_by_ticker.get(r.ticker.upper())
    if row and r.instrument_id not in changes and r.isin != row["isin"] and r.isin_status != V:
        changes[r.instrument_id] = dict(isin=row["isin"], isin_status=V)
for iid, ch in changes.items():
    cur = by_id[iid]
    diff = {k: (getattr(cur, k), v) for k, v in ch.items() if getattr(cur, k) != v}
    if diff: print(iid, diff)
    else: changes[iid] = {}
changes = {k: v for k, v in changes.items() if v}
print(f"{len(changes)} records to change; store revision {snap.revision[:12]}")
if not apply:
    print("dry run (pass --apply to write)"); sys.exit(0)
store = root / "configs" / "universe_store.json"
backup = store.with_name(f"universe_store.backup-{datetime.now():%Y%m%dT%H%M%S}.json")
shutil.copy2(store, backup); print("backup", backup)
for iid, ch in changes.items():
    records = us.edit_record(records, iid, **ch)
result = us.save_universe(records, snap.revision, root=root)
print("saved", getattr(result, "revision", result))
