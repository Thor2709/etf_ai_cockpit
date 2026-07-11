from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from etf_cockpit.services import CockpitSnapshot


@dataclass(frozen=True)
class InstrumentDetailViewModel:
    instrument_id: str
    display_name: str
    status: str
    identity: dict[str, Any]
    sections: dict[str, Any]


_SECTION_NAMES = ("identity", "price", "scores", "risk", "attribution", "fundamentals", "etf_disclosures", "news", "forecasts", "backtests", "history", "journal", "run_changes")


def build_instrument_detail(snapshot: CockpitSnapshot, instrument_id: str) -> InstrumentDetailViewModel:
    identity = next((item for item in snapshot.config.universe.etfs if item.id == instrument_id), None)
    if identity is None:
        return InstrumentDetailViewModel(instrument_id, instrument_id, "unavailable", {"instrument_id": instrument_id}, {name: "unavailable" for name in _SECTION_NAMES})
    signal = next((item for item in snapshot.signals if item.etf_id == instrument_id), None)
    price_rows = snapshot.prices[snapshot.prices.get("etf_id", "") == instrument_id] if not snapshot.prices.empty and "etf_id" in snapshot.prices.columns else snapshot.prices.iloc[0:0]
    return InstrumentDetailViewModel(
        instrument_id,
        identity.name,
        "ready",
        {"name": identity.name, "ticker": identity.ticker, "isin": identity.isin or "needs_verification", "asset_type": identity.asset_class, "exchange": identity.exchange},
        {
            "identity": "ready",
            "price": {"rows": len(price_rows), "as_of": str(price_rows["date"].max()) if not price_rows.empty and "date" in price_rows.columns else "unavailable"},
            "scores": "ready" if signal is not None else "unavailable",
            "risk": "ready" if signal is not None else "unavailable",
            "attribution": "available from evidence ledger where present",
            "fundamentals": "unavailable unless sourced",
            "etf_disclosures": "available from disclosure inventory",
            "news": "unavailable unless timestamp-validated",
            "forecasts": "available from valid forecast rows",
            "backtests": "available from local backtest report",
            "history": "available from local score history",
            "journal": "unavailable until a local note exists",
            "run_changes": "available from local run history",
        },
    )
