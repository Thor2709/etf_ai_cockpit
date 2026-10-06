"""Daily Euronext Oslo listing capture and savings-bank membership view."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import csv
import io
from pathlib import Path
import re
import unicodedata
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd
import yaml

from etf_cockpit.core.paths import CONFIG_DIR, ROOT
from etf_cockpit.data.universe_membership import (
    CaptureStatus,
    MembershipCaptureError,
    capture_log,
    load_raw_payload,
    membership_intervals,
    record_listing_capture,
)


DEFAULT_CONFIG_PATH = CONFIG_DIR / "euronext_listing_v1.yaml"
SCOPE = "listing:euronext_oslo:all"
ENDPOINT = "https://live.euronext.com/en/pd_es/data/stocks/download?mics=XOSL%2CMERK%2CXOAS"
FORM_BODY = b"args[fe_type]=csv&args[fe_decimal_separator]=.&args[fe_date_format]=d/m/Y"
_DATE_LINE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$")
_ISIN_COUNTRY = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
Transport = Callable[[str, bytes, Mapping[str, str], float], object]
Clock = Callable[[], datetime]


class EuronextListingError(ValueError):
    """Base error for invalid listing responses or configuration."""


class EuronextListingUnavailable(EuronextListingError):
    """The public Euronext listing endpoint did not return a usable response."""


@dataclass(frozen=True)
class EuronextListingConfig:
    provider_id: str
    endpoint: str
    scope: str
    timeout_seconds: float
    minimum_rows: int
    user_agent: str
    markets: tuple[str, ...]
    savings_bank_patterns: tuple[str, ...]
    savings_bank_include_names: tuple[str, ...]
    savings_bank_exclude_names: tuple[str, ...]


@dataclass(frozen=True)
class ListingDownload:
    payload: bytes
    status_code: int
    fetched_at: datetime


@dataclass(frozen=True)
class ListingRejection:
    row_number: int
    instrument_id: str
    reason: str


@dataclass(frozen=True)
class ParsedListing:
    as_of_date: str
    rows: tuple[dict[str, str], ...]
    rejected_rows: tuple[ListingRejection, ...]


@dataclass(frozen=True)
class EuronextListingCaptureStatus:
    status: str
    reason: str | None = None
    as_of_date: str | None = None
    accepted_rows: int = 0
    rejected_rows: tuple[ListingRejection, ...] = ()
    recorder_status: CaptureStatus | None = None


class EuronextListingProvider:
    """Download the public Oslo listing CSV with an injectable transport."""

    def __init__(
        self,
        config: EuronextListingConfig,
        *,
        transport: Transport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self) -> ListingDownload:
        headers = {
            "Accept": "text/csv,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": self.config.user_agent,
        }
        try:
            if self.transport is not None:
                response = _normalise_response(
                    self.transport(self.config.endpoint, FORM_BODY, headers, self.config.timeout_seconds)
                )
            else:
                request = Request(self.config.endpoint, data=FORM_BODY, headers=dict(headers), method="POST")
                with urlopen(request, timeout=self.config.timeout_seconds) as response_handle:
                    response = _normalise_response(response_handle)
        except HTTPError as exc:
            raise EuronextListingUnavailable(
                f"Euronext Oslo listing endpoint returned HTTP {exc.code}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise EuronextListingUnavailable("Euronext Oslo listing download failed") from exc
        if response.status_code != 200:
            raise EuronextListingUnavailable(f"Euronext Oslo listing endpoint returned HTTP {response.status_code}")
        return ListingDownload(response.payload, response.status_code, _utc_datetime(self.clock()))


def load_euronext_listing_config(path: Path | None = None) -> EuronextListingConfig:
    """Load and validate the versioned listing and savings-bank configuration."""

    source = Path(path or DEFAULT_CONFIG_PATH)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EuronextListingError(f"Euronext listing configuration is unavailable: {source}") from exc
    required = {
        "schema_version",
        "provider_id",
        "endpoint",
        "scope",
        "timeout_seconds",
        "minimum_rows",
        "user_agent",
        "markets",
        "savings_bank_patterns",
        "savings_bank_include_names",
        "savings_bank_exclude_names",
    }
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise EuronextListingError("Euronext listing configuration has an unsupported shape")
    if (
        payload.get("schema_version") != "euronext-listing.v1"
        or payload.get("provider_id") != "euronext_oslo_listing"
        or payload.get("endpoint") != ENDPOINT
        or payload.get("scope") != SCOPE
    ):
        raise EuronextListingError("Euronext listing configuration identity is unsupported")
    timeout_seconds = payload.get("timeout_seconds")
    minimum_rows = payload.get("minimum_rows")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or isinstance(minimum_rows, bool)
        or not isinstance(minimum_rows, int)
        or minimum_rows <= 0
    ):
        raise EuronextListingError("Euronext listing timeout and minimum row count must be positive")
    user_agent = _config_text(payload.get("user_agent"), "user_agent")
    markets = _config_text_list(payload.get("markets"), "markets")
    if set(markets) != {"Oslo Børs", "Euronext Growth Oslo", "Euronext Expand Oslo"}:
        raise EuronextListingError("Euronext listing market declarations are unsupported")
    return EuronextListingConfig(
        provider_id="euronext_oslo_listing",
        endpoint=ENDPOINT,
        scope=SCOPE,
        timeout_seconds=float(timeout_seconds),
        minimum_rows=minimum_rows,
        user_agent=user_agent,
        markets=markets,
        savings_bank_patterns=_config_text_list(payload.get("savings_bank_patterns"), "savings_bank_patterns"),
        savings_bank_include_names=_config_text_list(
            payload.get("savings_bank_include_names"), "savings_bank_include_names", allow_empty=True
        ),
        savings_bank_exclude_names=_config_text_list(
            payload.get("savings_bank_exclude_names"), "savings_bank_exclude_names", allow_empty=True
        ),
    )


def parse_euronext_listing(payload: bytes, config: EuronextListingConfig | None = None) -> ParsedListing:
    """Parse a downloaded Euronext semicolon CSV, retaining row rejection reasons."""

    active_config = config or load_euronext_listing_config()
    if not isinstance(payload, bytes) or not payload:
        raise EuronextListingError("Euronext listing response is empty")
    try:
        text = payload.decode("utf-8-sig")
        records = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise EuronextListingError("Euronext listing response is not valid UTF-8 semicolon CSV") from exc
    if not records:
        raise EuronextListingError("Euronext listing response is empty")
    header_index: int | None = None
    header: list[str] = []
    for index, candidate in enumerate(records):
        folded = [item.strip().casefold() for item in candidate]
        if {"name", "isin", "symbol", "market", "currency"}.issubset(folded):
            header_index = index
            header = folded
            break
    if header_index is None:
        raise EuronextListingError("Euronext listing CSV is missing the instrument header")
    as_of_date = _preamble_date(records[header_index + 1 : header_index + 4])
    positions = {name: header.index(name) for name in ("name", "isin", "symbol", "market", "currency")}
    accepted: list[dict[str, str]] = []
    rejected: list[ListingRejection] = []
    seen_isins: dict[str, dict[str, str]] = {}
    allowed_markets = set(active_config.markets)
    for row_number, record in enumerate(records[header_index + 4 :], start=header_index + 5):
        if not record or not any(value.strip() for value in record):
            continue
        raw_isin = record[positions["isin"]].strip() if len(record) > positions["isin"] else ""
        if not _valid_isin(raw_isin):
            rejected.append(ListingRejection(row_number, raw_isin, "invalid ISIN"))
            continue
        if len(record) <= max(positions.values()):
            rejected.append(ListingRejection(row_number, raw_isin, "row is missing required listing fields"))
            continue
        name = record[positions["name"]].strip()
        symbol = record[positions["symbol"]].strip()
        market = record[positions["market"]].strip()
        currency = record[positions["currency"]].strip()
        if not all((name, symbol, market, currency)):
            rejected.append(ListingRejection(row_number, raw_isin, "row is missing required listing fields"))
            continue
        if market not in allowed_markets:
            rejected.append(ListingRejection(row_number, raw_isin, f"unknown market: {market}"))
            continue
        row = {
            "instrument_id": raw_isin,
            "symbol": symbol,
            "name": name,
            "market": market,
            "currency": currency,
            "yfinance_ticker": f"{symbol}.OL",
        }
        isin_key = raw_isin.casefold()
        if isin_key in seen_isins:
            reason = "duplicate ISIN" if seen_isins[isin_key] == row else "conflicting duplicate ISIN"
            rejected.append(ListingRejection(row_number, raw_isin, reason))
            continue
        seen_isins[isin_key] = row
        accepted.append(row)
    return ParsedListing(as_of_date, tuple(accepted), tuple(rejected))


def capture_euronext_oslo_listing(
    *,
    root: Path | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    clock: Clock | None = None,
) -> EuronextListingCaptureStatus:
    """Fetch, validate and record one complete Euronext Oslo listing snapshot."""

    try:
        config = load_euronext_listing_config(config_path)
        downloaded = EuronextListingProvider(config, transport=transport, clock=clock).fetch()
        parsed = parse_euronext_listing(downloaded.payload, config)
        completeness_rejections = tuple(
            rejection for rejection in parsed.rejected_rows if rejection.reason != "duplicate ISIN"
        )
        if completeness_rejections:
            raise EuronextListingError("Euronext listing contains rejected instrument rows")
        if len(parsed.rows) < config.minimum_rows:
            raise EuronextListingError(
                f"Euronext listing has {len(parsed.rows)} accepted rows; minimum is {config.minimum_rows}"
            )
        status = record_listing_capture(
            parsed.rows,
            source=config.provider_id,
            scope=config.scope,
            known_at=downloaded.fetched_at,
            root=Path(root or ROOT),
            raw_payload=downloaded.payload,
            snapshot_date=parsed.as_of_date,
        )
        return EuronextListingCaptureStatus(
            status=status.status,
            as_of_date=parsed.as_of_date,
            accepted_rows=len(parsed.rows),
            rejected_rows=parsed.rejected_rows,
            recorder_status=status,
        )
    except (EuronextListingError, MembershipCaptureError, OSError, TimeoutError, ValueError) as exc:
        return EuronextListingCaptureStatus("error", reason=f"{type(exc).__name__}: {exc}")


def savings_bank_view(
    *,
    root: Path | None = None,
    config_path: Path | None = None,
) -> pd.DataFrame:
    """Return savings-bank members in the latest complete Oslo listing capture."""

    active_root = Path(root or ROOT)
    config = load_euronext_listing_config(config_path)
    columns = ("isin", "symbol", "yfinance_ticker", "market")
    captures = capture_log(config.scope, root=active_root)
    if captures.empty:
        return pd.DataFrame(columns=columns)
    latest = captures.sort_values(["snapshot_date", "known_at", "capture_id"]).iloc[-1]
    intervals = membership_intervals(config.scope, str(latest["known_at"]), root=active_root)
    current_ids = {
        str(row["instrument_id"])
        for row in intervals.to_dict(orient="records")
        if row["valid_to"] is None
    }
    listing = parse_euronext_listing(load_raw_payload(str(latest["checksum"]), root=active_root), config)
    patterns = tuple(_normalise_name(item) for item in config.savings_bank_patterns)
    include_names = {_normalise_name(item) for item in config.savings_bank_include_names}
    exclude_names = tuple(_normalise_name(item) for item in config.savings_bank_exclude_names)
    results: list[dict[str, str]] = []
    for row in listing.rows:
        name = _normalise_name(row["name"])
        if row["instrument_id"] not in current_ids or _is_excluded_name(name, exclude_names):
            continue
        if name not in include_names and not any(pattern in name for pattern in patterns):
            continue
        results.append(
            {
                "isin": row["instrument_id"],
                "symbol": row["symbol"],
                "yfinance_ticker": row["yfinance_ticker"],
                "market": row["market"],
            }
        )
    return pd.DataFrame.from_records(results, columns=columns)


def _normalise_response(value: object) -> ListingDownload:
    if isinstance(value, (bytes, bytearray)):
        payload, status = bytes(value), 200
    elif isinstance(value, tuple) and len(value) in {2, 3}:
        payload, status = value[0], int(value[1])
        payload = bytes(payload or b"")
    elif hasattr(value, "read"):
        payload = bytes(value.read())  # type: ignore[union-attr]
        status = int(getattr(value, "status", 200))
    else:
        raise EuronextListingUnavailable("Euronext transport returned an unsupported response")
    return ListingDownload(payload, status, datetime.now(timezone.utc))


def _preamble_date(records: list[list[str]]) -> str:
    for row in records:
        if len(row) != 1:
            continue
        match = _DATE_LINE.fullmatch(row[0].strip())
        if match is None:
            continue
        day, month, year = match.groups()
        try:
            parsed = date(int(year), _MONTHS[month.casefold()], int(day))
        except (KeyError, ValueError) as exc:
            raise EuronextListingError("Euronext listing preamble date is invalid") from exc
        return parsed.isoformat()
    raise EuronextListingError("Euronext listing CSV is missing its preamble date")


def _valid_isin(value: str) -> bool:
    if not _ISIN_COUNTRY.fullmatch(value):
        return False
    expanded = "".join(str(ord(character) - 55) if character.isalpha() else character for character in value)
    total = 0
    double = False
    for character in reversed(expanded):
        digit = int(character)
        if double:
            digit *= 2
            digit = digit // 10 + digit % 10
        total += digit
        double = not double
    return total % 10 == 0


def _config_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EuronextListingError(f"Euronext listing {field_name} must be a non-empty string")
    return value.strip()


def _config_text_list(value: object, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EuronextListingError(f"Euronext listing {field_name} must be a list of non-empty strings")
    result = tuple(item.strip() for item in value)
    if (not allow_empty and not result) or len(set(result)) != len(result):
        raise EuronextListingError(f"Euronext listing {field_name} must be non-empty and unique")
    return result


def _is_excluded_name(name: str, exclusions: tuple[str, ...]) -> bool:
    return any(name == excluded or name.startswith(f"{excluded} ") for excluded in exclusions)


def _normalise_name(value: str) -> str:
    normalised = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalised.split())


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EuronextListingError("fetch clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


__all__ = [
    "EuronextListingCaptureStatus",
    "EuronextListingConfig",
    "EuronextListingError",
    "EuronextListingProvider",
    "ListingRejection",
    "ParsedListing",
    "capture_euronext_oslo_listing",
    "load_euronext_listing_config",
    "parse_euronext_listing",
    "savings_bank_view",
]
