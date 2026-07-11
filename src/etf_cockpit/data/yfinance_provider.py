from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from etf_cockpit.core.config import AppConfig, ETFConfig, ProviderSection
from etf_cockpit.data.providers import DataProvider, PriceProvider, ProviderResult
from etf_cockpit.data.provenance import metadata_from_frame


YAHOO_SUFFIX_BY_EXCHANGE = {
    "XETRA": ".DE",
    "XET": ".DE",
    "DEUTSCHE BOERSE": ".DE",
    "FRANKFURT": ".F",
    "EURONEXT AMSTERDAM": ".AS",
    "AMSTERDAM": ".AS",
    "EURONEXT PARIS": ".PA",
    "PARIS": ".PA",
    "BORSA ITALIANA": ".MI",
    "MILAN": ".MI",
    "LONDON": ".L",
    "LSE": ".L",
}

YAHOO_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,31}$")


@dataclass(frozen=True)
class YahooSymbolValidation:
    instrument_id: str
    symbol: str
    status: str
    reason: str


class YFinanceProvider(DataProvider, PriceProvider):
    name = "yfinance"

    def __init__(
        self,
        section: ProviderSection | None = None,
        *,
        default_currency: str = "EUR",
        instrument_metadata: dict[str, dict[str, object]] | None = None,
    ):
        self.section = section or ProviderSection()
        self.default_currency = default_currency
        self.instrument_metadata = instrument_metadata or {}

    @classmethod
    def from_config(cls, config: AppConfig) -> "YFinanceProvider":
        section = config.data_providers.section("prices")
        section = section.model_copy(update={"symbols_map": yfinance_symbol_map_from_config(config)})
        metadata = {
            etf.id: {
                "isin": etf.isin or "",
                "ticker": etf.ticker,
                "name": etf.name,
                "currency": etf.currency,
                "exchange": etf.exchange or "",
                "asset_class": etf.asset_class,
                "region": etf.region or "",
                "sector": etf.sector or "",
                "theme": etf.theme or "",
                "role": etf.role,
                "configured_ter": etf.ter,
            }
            for etf in config.universe.etfs
        }
        return cls(section, default_currency=config.targets.base_currency, instrument_metadata=metadata)

    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._download_one(symbol=symbol, etf_id=symbol, start_date=start, end_date=end)

    def validate_symbol(self, symbol: str) -> bool:
        try:
            end = date.today()
            start = end.replace(year=end.year - 1)
            return not self.fetch_daily_prices(symbol, start, end).empty
        except Exception:
            return False

    def fetch_prices(self, symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
        symbol_map = self._symbol_map(symbols)
        if not symbol_map:
            return ProviderResult(self.name, "prices", "unavailable", "No Yahoo Finance symbols were configured.")
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        for etf_id, yahoo_symbol in symbol_map.items():
            try:
                frame = self._download_one(symbol=yahoo_symbol, etf_id=etf_id, start_date=start_date, end_date=end_date)
                if frame.empty:
                    errors.append(f"{etf_id}/{yahoo_symbol}: no rows returned")
                else:
                    frames.append(frame)
            except Exception as exc:
                errors.append(f"{etf_id}/{yahoo_symbol}: {type(exc).__name__}: {exc}")
        if not frames:
            return ProviderResult(self.name, "prices", "error", "Yahoo Finance returned no usable price rows. " + "; ".join(errors))
        data = pd.concat(frames, ignore_index=True).sort_values(["etf_id", "date"])
        latest = pd.to_datetime(data["date"]).max().date()
        metadata = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="prices",
            as_of_date=latest,
            currency=self.default_currency,
            provider_or_manual_source="Yahoo Finance via yfinance",
            staleness_status="unknown",
            notes=("; ".join(errors) if errors else "Downloaded with yfinance; Yahoo data availability can vary by listing."),
        )
        message = f"Downloaded {len(data)} Yahoo Finance price rows for {data['etf_id'].nunique()} instruments."
        if errors:
            message = "Partial refresh rejected; no incomplete Yahoo Finance price set was committed. " + "; ".join(errors)
            return ProviderResult(self.name, "prices", "error", message, data, metadata)
        return ProviderResult(self.name, "prices", "ok", message, data, metadata)

    def fetch_fx(self, pairs: list[str], start_date: date, end_date: date) -> ProviderResult:
        if not pairs:
            return ProviderResult(self.name, "fx", "unavailable", "No FX pairs were requested.")
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        for pair in pairs:
            try:
                base, quote, yahoo_symbol = _normalise_fx_pair(pair)
                frame = self._download_one(symbol=yahoo_symbol, etf_id=pair.upper().replace("/", ""), start_date=start_date, end_date=end_date)
                if frame.empty:
                    errors.append(f"{pair}: no rows returned")
                    continue
                frames.append(
                    pd.DataFrame(
                        {
                            "as_of_date": pd.to_datetime(frame["date"]).dt.date,
                            "base_currency": base,
                            "quote_currency": quote,
                            "pair": f"{base}/{quote}",
                            "rate": pd.to_numeric(frame["adjusted_close"], errors="coerce"),
                            "source": self.name,
                            "provider_symbol": yahoo_symbol,
                        }
                    ).dropna(subset=["rate"])
                )
            except Exception as exc:
                errors.append(f"{pair}: {type(exc).__name__}: {exc}")
        if not frames:
            return ProviderResult(self.name, "fx", "error", "Yahoo Finance returned no usable FX rows. " + "; ".join(errors))
        data = pd.concat(frames, ignore_index=True).sort_values(["pair", "as_of_date"])
        latest = pd.to_datetime(data["as_of_date"]).max().date()
        metadata = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="fx",
            as_of_date=latest,
            currency="mixed",
            provider_or_manual_source="Yahoo Finance FX via yfinance",
            staleness_status="unknown",
            notes=("; ".join(errors) if errors else "Downloaded FX close series with yfinance."),
        )
        message = f"Downloaded {len(data)} Yahoo Finance FX rows for {data['pair'].nunique()} pairs."
        if errors:
            message = "Partial FX refresh rejected; no incomplete Yahoo Finance FX set was committed. " + "; ".join(errors)
            return ProviderResult(self.name, "fx", "error", message, data, metadata)
        return ProviderResult(self.name, "fx", "ok", message, data, metadata)

    def fetch_etf_metadata(self, isins: list[str]) -> ProviderResult:
        symbol_map = self._symbol_map(isins)
        if not symbol_map:
            return ProviderResult(self.name, "etf_metadata", "unavailable", "No Yahoo Finance symbols were configured.")
        rows: list[dict[str, object]] = []
        errors: list[str] = []
        for etf_id, yahoo_symbol in symbol_map.items():
            try:
                rows.append(self._metadata_row(etf_id, yahoo_symbol))
            except Exception as exc:
                errors.append(f"{etf_id}/{yahoo_symbol}: {type(exc).__name__}: {exc}")
        if not rows:
            return ProviderResult(self.name, "etf_metadata", "error", "Yahoo Finance returned no usable metadata. " + "; ".join(errors))
        data = pd.DataFrame(rows)
        metadata = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="etf_metadata",
            as_of_date=date.today(),
            currency=_single_or_mixed(data.get("currency")),
            provider_or_manual_source="Yahoo Finance Ticker/funds_data via yfinance",
            staleness_status="unknown",
            notes=(
                "Yahoo does not expose issuer factsheet source dates consistently; as_of_date is retrieval date. "
                + ("Partial errors: " + "; ".join(errors) if errors else "")
            ).strip(),
        )
        message = f"Downloaded Yahoo Finance metadata for {len(data)} instruments."
        if errors:
            message = "Partial metadata refresh rejected; no incomplete Yahoo Finance metadata set was committed. " + "; ".join(errors)
            return ProviderResult(self.name, "etf_metadata", "error", message, data, metadata)
        return ProviderResult(self.name, "etf_metadata", "ok", message, data, metadata)

    def fetch_etf_holdings(self, isins: list[str]) -> ProviderResult:
        symbol_map = self._symbol_map(isins)
        if not symbol_map:
            return ProviderResult(self.name, "etf_holdings", "unavailable", "No Yahoo Finance symbols were configured.")
        rows: list[dict[str, object]] = []
        errors: list[str] = []
        for etf_id, yahoo_symbol in symbol_map.items():
            try:
                rows.extend(self._top_holding_rows(etf_id, yahoo_symbol))
            except Exception as exc:
                errors.append(f"{etf_id}/{yahoo_symbol}: {type(exc).__name__}: {exc}")
        if not rows:
            return ProviderResult(
                self.name,
                "etf_holdings",
                "unavailable",
                "Yahoo Finance exposed no top-holdings rows for the configured instruments. " + "; ".join(errors),
            )
        data = pd.DataFrame(rows)
        metadata = metadata_from_frame(
            data,
            source_name=self.name,
            source_type="etf_holdings",
            as_of_date=date.today(),
            currency=_single_or_mixed(data.get("currency")),
            provider_or_manual_source="Yahoo Finance funds_data.top_holdings via yfinance",
            staleness_status="unknown",
            notes=(
                "Yahoo top holdings are partial when Yahoo exposes only the largest positions; as_of_date is retrieval date. "
                + ("Partial errors: " + "; ".join(errors) if errors else "")
            ).strip(),
        )
        message = f"Downloaded {len(data)} Yahoo Finance top-holdings rows for {data['etf_id'].nunique()} instruments."
        if errors:
            message = "Partial holdings refresh rejected; no incomplete Yahoo Finance holdings set was committed. " + "; ".join(errors)
            return ProviderResult(self.name, "etf_holdings", "error", message, data, metadata)
        return ProviderResult(self.name, "etf_holdings", "ok", message, data, metadata)

    def _symbol_map(self, symbols: list[str]) -> dict[str, str]:
        configured = {str(k): str(v) for k, v in self.section.symbols_map.items() if str(v).strip()}
        if configured:
            requested = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
            if requested:
                return {
                    instrument_id: yahoo_symbol
                    for instrument_id, yahoo_symbol in configured.items()
                    if instrument_id in requested or yahoo_symbol in requested
                }
            return configured
        return {symbol: symbol for symbol in symbols if symbol}

    def _download_one(self, *, symbol: str, etf_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        yf = _import_yfinance()
        frame = yf.download(
            symbol,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
            group_by="column",
        )
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = _flatten_download_frame(frame)
        required = {"Open", "High", "Low", "Close"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Yahoo result missing columns: {sorted(missing)}")
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(frame.index).date,
                "etf_id": etf_id,
                "open": pd.to_numeric(frame["Open"], errors="coerce"),
                "high": pd.to_numeric(frame["High"], errors="coerce"),
                "low": pd.to_numeric(frame["Low"], errors="coerce"),
                "close": pd.to_numeric(frame["Close"], errors="coerce"),
                "adjusted_close": pd.to_numeric(frame.get("Adj Close", frame["Close"]), errors="coerce"),
                "volume": _numeric_frame_column(frame, "Volume", default=0.0),
                "currency": self.default_currency,
                "provider_symbol": symbol,
                "source": self.name,
                "is_adjusted": "Adj Close" in frame.columns,
                "dividends": _numeric_frame_column(frame, "Dividends", default=0.0),
                "stock_splits": _numeric_frame_column(frame, "Stock Splits", default=0.0),
                "capital_gains": _numeric_frame_column(frame, "Capital Gains", default=0.0),
            }
        )
        out = out.dropna(subset=["open", "high", "low", "close", "adjusted_close"])
        return out

    def _ticker(self, symbol: str) -> Any:
        return _import_yfinance().Ticker(symbol)

    def _metadata_row(self, etf_id: str, yahoo_symbol: str) -> dict[str, object]:
        ticker = self._ticker(yahoo_symbol)
        info = _safe_dict(_safe_getattr(ticker, "info", {}))
        fast_info = _safe_dict(_safe_getattr(ticker, "fast_info", {}))
        funds_data = _safe_getattr(ticker, "funds_data", None)
        fund_overview = _safe_dict(_safe_getattr(funds_data, "fund_overview", {}))
        fund_operations = _safe_dataframe(_safe_getattr(funds_data, "fund_operations", pd.DataFrame()))
        configured = self.instrument_metadata.get(etf_id, {})
        ter = _fund_operation_value(fund_operations, yahoo_symbol, "Annual Report Expense Ratio")
        return {
            "as_of_date": date.today(),
            "etf_id": etf_id,
            "isin": configured.get("isin", ""),
            "ticker": configured.get("ticker") or yahoo_symbol,
            "provider_symbol": yahoo_symbol,
            "name": info.get("longName") or info.get("shortName") or configured.get("name", ""),
            "currency": info.get("currency") or fast_info.get("currency") or configured.get("currency") or self.default_currency,
            "ter": ter if ter is not None else configured.get("configured_ter"),
            "provider": info.get("fundFamily") or fund_overview.get("family") or "Yahoo Finance",
            "factsheet_url": "",
            "quote_type": info.get("quoteType") or fast_info.get("quoteType") or fund_overview.get("legalType") or "",
            "total_assets": info.get("totalAssets"),
            "yield": info.get("yield"),
            "category": info.get("category") or fund_overview.get("categoryName") or "",
            "source": self.name,
        }

    def _top_holding_rows(self, etf_id: str, yahoo_symbol: str) -> list[dict[str, object]]:
        ticker = self._ticker(yahoo_symbol)
        funds_data = _safe_getattr(ticker, "funds_data", None)
        top_holdings = _safe_dataframe(_safe_getattr(funds_data, "top_holdings", pd.DataFrame()))
        if top_holdings.empty or "Holding Percent" not in top_holdings.columns:
            return []
        rows: list[dict[str, object]] = []
        configured = self.instrument_metadata.get(etf_id, {})
        for holding_id, row in top_holdings.iterrows():
            holding_name = str(row.get("Name", "")).strip()
            weight = _safe_float(row.get("Holding Percent"))
            if not holding_name or weight is None:
                continue
            rows.append(
                {
                    "as_of_date": date.today(),
                    "etf_id": etf_id,
                    "holding_name": holding_name,
                    "holding_id": str(holding_id),
                    "weight": weight,
                    "currency": "",
                    "region": configured.get("region", ""),
                    "sector": "",
                    "source": "yfinance_top_holdings",
                    "provider_symbol": yahoo_symbol,
                }
            )
        return rows


def _import_yfinance():
    try:
        import yfinance as yf
    except Exception as exc:
        raise RuntimeError("yfinance is not installed. Run `pip install yfinance` in the project environment.") from exc
    return yf


def yfinance_symbol_map_from_config(config: AppConfig) -> dict[str, str]:
    configured = {
        str(etf_id): str(symbol)
        for etf_id, symbol in config.data_providers.section("prices").symbols_map.items()
        if str(symbol).strip()
    }
    output: dict[str, str] = {}
    for etf in config.universe.etfs:
        if not etf.enabled:
            continue
        output[etf.id] = configured.get(etf.id) or yfinance_symbol_for_etf(etf)
    return {etf_id: symbol for etf_id, symbol in output.items() if symbol}


def yfinance_symbol_for_etf(etf: ETFConfig) -> str:
    for candidate in (etf.provider_symbol, etf.ticker):
        value = str(candidate or "").strip()
        if value and value != etf.id and looks_like_yahoo_symbol(value):
            return value
    ticker = str(etf.ticker or "").strip()
    if not ticker:
        return ""
    if "." in ticker:
        return ticker
    suffix = YAHOO_SUFFIX_BY_EXCHANGE.get(str(etf.exchange or "").strip().upper(), "")
    return f"{ticker}{suffix}" if suffix else ticker


def _flatten_download_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        if len(frame.columns.levels) > 1 and len(frame.columns.get_level_values(1).unique()) == 1:
            frame = frame.droplevel(1, axis=1)
        elif len(frame.columns.levels) > 1 and len(frame.columns.get_level_values(0).unique()) == 1:
            frame = frame.droplevel(0, axis=1)
        else:
            frame = frame.copy()
            frame.columns = [" ".join(str(part) for part in column if part) for column in frame.columns]
    return frame


def looks_like_yahoo_symbol(value: str) -> bool:
    symbol = str(value or "").strip()
    if not symbol or not YAHOO_SYMBOL_PATTERN.fullmatch(symbol):
        return False
    return True


def validate_yahoo_symbols(symbols: dict[str, str]) -> dict[str, YahooSymbolValidation]:
    """Validate configured symbol shapes without making a network request."""
    result: dict[str, YahooSymbolValidation] = {}
    for instrument_id, symbol in symbols.items():
        text = str(symbol or "").strip()
        status = "shape_valid" if looks_like_yahoo_symbol(text) else "invalid_symbol"
        reason = "Yahoo symbol shape is valid; provider availability still requires a bounded fetch." if status == "shape_valid" else "Symbol contains an invalid character or path-like value."
        result[str(instrument_id)] = YahooSymbolValidation(str(instrument_id), text, status, reason)
    return result


def _looks_like_yahoo_symbol(value: str) -> bool:
    return looks_like_yahoo_symbol(value)


def _normalise_fx_pair(pair: str) -> tuple[str, str, str]:
    compact = "".join(ch for ch in pair.upper() if ch.isalpha())
    if len(compact) != 6:
        raise ValueError(f"FX pair must contain two three-letter currencies: {pair}")
    base, quote = compact[:3], compact[3:]
    return base, quote, f"{base}{quote}=X"


def _safe_getattr(obj: object, name: str, default: object) -> object:
    if obj is None:
        return default
    try:
        value = getattr(obj, name)
        return value() if callable(value) and name == "quote_type" else value
    except Exception:
        return default


def _safe_dict(value: object) -> dict[str, object]:
    try:
        if value is None:
            return {}
        if hasattr(value, "items"):
            return dict(value.items())
        return dict(value)  # type: ignore[arg-type]
    except Exception:
        return {}


def _safe_dataframe(value: object) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _fund_operation_value(frame: pd.DataFrame, symbol: str, label: str) -> float | None:
    if frame.empty or label not in frame.index:
        return None
    for column in (symbol, *list(frame.columns)):
        if column not in frame.columns:
            continue
        value = _safe_float(frame.loc[label, column])
        if value is not None:
            return value
    return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _numeric_frame_column(frame: pd.DataFrame, column: str, *, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _single_or_mixed(series: pd.Series | None) -> str | None:
    if series is None:
        return None
    values = sorted({str(value) for value in series.dropna().unique() if str(value)})
    if not values:
        return None
    return values[0] if len(values) == 1 else "mixed"
