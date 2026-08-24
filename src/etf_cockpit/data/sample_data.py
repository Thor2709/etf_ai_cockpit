from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml  # type: ignore[import-untyped]

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR, PORTFOLIOS_DIR, RAW_DIR, ensure_project_dirs
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope


def _sample_calendar_identities() -> dict[str, dict[str, object]]:
    path = CONFIG_DIR / "sample_calendar_identities.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    identities = payload.get("identities") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "sample-calendar-identities.v1" or not isinstance(
        identities, dict
    ):
        return {}
    return {
        str(instrument_id): dict(fields)
        for instrument_id, fields in identities.items()
        if isinstance(fields, dict)
        and all(type(fields.get(key)) is str and fields.get(key).strip() for key in ("mic", "calendar_id", "timezone"))
    }


def generate_sample_prices(config: AppConfig, periods: int = 900, end_date: date | None = None) -> pd.DataFrame:
    """Generate deterministic, plausible ETF OHLCV data for immediate local use."""
    rng = np.random.default_rng(42)
    end = pd.Timestamp(end_date or date.today())
    dates = pd.bdate_range(end=end, periods=periods)
    market_shock = rng.normal(0.00025, 0.0065, size=len(dates))
    rate_shock = rng.normal(0.00005, 0.003, size=len(dates))
    risk_shock = rng.normal(0.0, 0.004, size=len(dates))
    rows: list[dict[str, object]] = []

    role_params = {
        "core": (0.00022, 0.008),
        "regional": (0.00018, 0.010),
        "sector": (0.00024, 0.014),
        "theme": (0.00030, 0.016),
        "bond": (0.00008, 0.0035),
        "hedge": (0.00010, 0.009),
        "commodity": (0.00010, 0.009),
    }
    start_prices = np.linspace(35, 125, num=max(1, len(config.universe.etfs)))
    identity_known_at = (dates[0].tz_localize("UTC") - pd.Timedelta(days=1)).isoformat()
    calendar_identities = _sample_calendar_identities()

    for index, etf in enumerate(config.universe.etfs):
        drift, vol = role_params.get(etf.role, (0.00015, 0.010))
        phase = index / max(1, len(config.universe.etfs))
        idiosyncratic = rng.normal(0.0, vol, size=len(dates))
        cyclical = 0.0008 * np.sin(np.linspace(0, 8 * np.pi, len(dates)) + phase)
        if etf.role == "bond":
            log_returns = drift + 0.15 * market_shock - 0.35 * rate_shock + idiosyncratic + cyclical
        elif etf.role in {"hedge", "commodity"}:
            log_returns = drift - 0.10 * market_shock + 0.40 * risk_shock + idiosyncratic + cyclical
        else:
            sector_beta = 1.25 if etf.role in {"sector", "theme"} else 0.95
            log_returns = drift + sector_beta * market_shock + 0.20 * risk_shock + idiosyncratic + cyclical

        # Add one controlled drawdown and recovery period to make gates/backtests meaningful.
        drawdown_start = int(len(dates) * (0.58 + 0.02 * (index % 3)))
        drawdown_end = min(len(dates), drawdown_start + 45)
        log_returns[drawdown_start:drawdown_end] -= 0.004 + 0.0005 * (index % 2)
        log_returns[drawdown_end : min(len(dates), drawdown_end + 50)] += 0.002

        close = start_prices[index] * np.exp(np.cumsum(log_returns))
        overnight = rng.normal(0, vol / 3, size=len(dates))
        open_price = close * np.exp(-0.5 * log_returns + overnight)
        high = np.maximum(open_price, close) * (1 + np.abs(rng.normal(0.0025, 0.0015, len(dates))))
        low = np.minimum(open_price, close) * (1 - np.abs(rng.normal(0.0025, 0.0015, len(dates))))
        volume_base = 100_000 + 25_000 * index
        volume = np.maximum(0, rng.normal(volume_base, volume_base * 0.18, size=len(dates))).round()
        calendar_identity = None
        calendar_fields = calendar_identities.get(etf.id)
        if calendar_fields is not None:
            calendar_identity = {
                "status": "available",
                "instrument_id": etf.id,
                "identity_decision_id": f"sample-calendar:{etf.id}",
                "identity_decision_time": identity_known_at,
                "identity_effective_at": dates[0].date().isoformat(),
                "identity_objects": [{
                    "object_type": "listing",
                    "object_id": f"sample-listing:{etf.id}:{calendar_fields['mic']}",
                    "fields": {
                        **calendar_fields,
                        "calendar_source_version": "sample-calendar-identities.v1",
                    },
                }],
                "identity_history": [{"source_id": f"sample_generator:calendar:{etf.id}"}],
                "execution_allowed": False,
            }

        for dt, opn, hi, lo, cls, volm in zip(dates, open_price, high, low, close, volume):
            rows.append(
                {
                    "date": dt.date(),
                    "etf_id": etf.id,
                    "provider_symbol": etf.provider_symbol or etf.ticker,
                    "open": float(opn),
                    "high": float(max(hi, opn, cls)),
                    "low": float(min(lo, opn, cls)),
                    "close": float(cls),
                    "adjusted_close": float(cls),
                    "volume": float(volm),
                    "currency": etf.currency,
                    "source": "sample_generator",
                    "is_adjusted": True,
                    "ingested_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    "calendar_identity": calendar_identity,
                }
            )

    return pd.DataFrame(rows)


def generate_sample_holdings(config: AppConfig, prices: pd.DataFrame, portfolio_value_eur: float = 10000) -> pd.DataFrame:
    targets = config.targets.positions
    latest = prices.sort_values("date").groupby("etf_id").tail(1).set_index("etf_id")
    drift_pattern: dict[str, float] = {}
    rows: list[dict[str, object]] = []
    weights: dict[str, float] = {}
    for etf_id, target in targets.items():
        weights[etf_id] = max(0.0, target.target_weight + drift_pattern.get(etf_id, 0.0))
    total_security_weight = min(0.98, sum(weights.values()))
    scale = total_security_weight / sum(weights.values()) if sum(weights.values()) else 1.0
    as_of = pd.to_datetime(prices["date"]).max().date()
    for etf_id, weight in weights.items():
        row = latest.loc[etf_id]
        current_weight = weight * scale
        market_value = portfolio_value_eur * current_weight
        market_price = float(row["adjusted_close"])
        units = market_value / market_price if market_price else 0.0
        average_cost = market_price * (0.88 + 0.04 * (len(etf_id) % 5))
        gain = market_value - units * average_cost
        rows.append(
            {
                "as_of_date": as_of,
                "etf_id": etf_id,
                "units": units,
                "market_price": market_price,
                "market_value_eur": market_value,
                "current_weight": current_weight,
                "average_cost_eur": average_cost,
                "unrealised_gain_eur": gain,
                "unrealised_gain_pct": (market_price / average_cost - 1) if average_cost else 0.0,
                "source": "sample_generator",
            }
        )
    return pd.DataFrame(rows)


def ensure_sample_files(
    config: AppConfig,
    force: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> tuple[Path, Path]:
    price_path = RAW_DIR / "prices" / "sample_prices.csv"
    holdings_path = PORTFOLIOS_DIR / "current_holdings.csv"
    if force or not price_path.exists() or not holdings_path.exists():
        prices = generate_sample_prices(config)
        holdings = generate_sample_holdings(config, prices)
        with publication_scope(publish_guard):
            ensure_project_dirs()
            prices.to_csv(price_path, index=False)
            holdings.to_csv(holdings_path, index=False)
    return price_path, holdings_path
