"""Read-only ETF display acquisition, published through the reference importer.

Source observations remain display context, never trusted tracking or score
inputs. Document addresses are registry bindings or links discovered on the
ISIN-bound public profile; no issuer product IDs are inferred.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request

import pandas as pd

from etf_cockpit.data.fund_adapters import fetch_etf_economics_sources
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.providers import ProviderResult


# Verified issuer document, not a constructed product address.
_ISSUER_DOCUMENTS = {
    "IE00BK5BQT80": "https://fund-docs.vanguard.com/FTSE_All-World_UCITS_ETF_USD_Accumulating_9679_EU_INT_EN.pdf",
}
_ISSUER_HOSTS = ("vanguard.com", "ishares.com", "blackrock.com", "etf.dws.com", "xtrackers.com", "ssga.com", "amundietf.com", "amundi.com", "api.fundinfo.com")
_MAX_BYTES = 8 * 1024 * 1024
_CONTEXT_FIELD = "etf_e1_context_v1"


def _public_url(isin: str) -> str:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        raise ValueError("isin_missing_or_invalid")
    return "https://www.justetf.com/en/etf-profile.html?" + urlencode({"isin": isin})


def _get(url: str, *, timeout: float = 10) -> bytes:
    """Bounded GET only; reject redirects outside the free source hosts."""
    def allowed(address):
        parsed = urlsplit(address)
        return parsed.scheme == "https" and not parsed.username and not parsed.password and any(
            parsed.hostname == host or (parsed.hostname or "").endswith("." + host)
            for host in (*_ISSUER_HOSTS, "justetf.com")
        )
    if not allowed(url):
        raise ValueError("source_url_not_supported")
    # Disable automatic redirects so an unapproved target is never contacted.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    from urllib.error import HTTPError
    opener = build_opener(NoRedirect())
    for _ in range(4):
        try:
            with opener.open(Request(url, headers={"User-Agent": "ETF-AI-Cockpit/1.1 (read-only research)"}), timeout=timeout) as response:
                payload = response.read(_MAX_BYTES + 1)
            if len(payload) > _MAX_BYTES:
                raise ValueError("source_response_too_large")
            return payload
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            url = urljoin(url, exc.headers.get("Location", ""))
            if not allowed(url):
                raise ValueError("source_redirect_not_supported") from exc
    raise ValueError("source_redirect_limit")


class _Profile(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.tokens, self.links, self.rows = [], [], []
        self._hidden = 0
        self._href, self._label = None, []
        self._row, self._cell = None, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._hidden += 1
        if tag == "a":
            self._href, self._label = dict(attrs).get("href"), []
        if tag == "tr":
            self._row = []
        if tag in {"td", "th"}:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._hidden = max(0, self._hidden - 1)
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._label)))
            self._href = None
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join(self._cell))
            self._cell = None
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        value = " ".join(data.split())
        if self._hidden or not value:
            return
        self.tokens.append(value)
        if self._href:
            self._label.append(value)
        if self._cell is not None:
            self._cell.append(value)


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _parse_fields(text: str, row: dict) -> dict:
    fee = re.search(r"(?:Total expense ratio|TER|Ongoing Charges Figure|Ongoing charges)\s*[†‡:]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if fee:
        row.update(ter=float(fee[1]) / 100, fee_unit="decimal_fraction")
    size = re.search(r"Fund size\s+(EUR|USD|GBP)\s+([\d,.]+)\s*m\b", text, re.I)
    issuer_size = re.search(r"Total assets\s*\(million\)\s*(US\$|\$|EUR|USD|GBP)\s*([\d,.]+)", text, re.I)
    if size or issuer_size:
        match = size or issuer_size
        row.update(aum=_number(match[2]) * 1_000_000, aum_unit="currency_units", aum_currency="USD" if match[1] == "US$" else None if match[1] == "$" else match[1].upper())
    policy = re.search(r"Distribution policy\s+(Accumulating|Distributing)", text, re.I)
    if policy:
        row["distribution_policy"] = policy[1].casefold()
    return row


def _public_records(html: bytes, instrument, known_at: str, url: str) -> list[dict]:
    profile = _Profile(html.decode("utf-8"))
    text = " ".join(profile.tokens)
    if not re.search(r"ISIN\s*:?\s*" + re.escape(instrument.isin) + r"\b", text):
        raise ValueError("public_identity_mismatch")
    row = _parse_fields(text, dict(instrument_id=instrument.id, as_of=known_at, known_at=known_at, source_id=url, source_authority="public_page", date_basis="acquisition_snapshot"))
    # The composition date is separate from the undated current profile facts.
    date_match = re.search(r"As of\s+(\d{2}/\d{2}/\d{4})", text, re.I)
    if date_match:
        effective = datetime.strptime(date_match[1], "%d/%m/%Y").date().isoformat()
        if pd.Timestamp(effective, tz="UTC") > pd.Timestamp(known_at):
            row["holdings_unavailable_reason"] = "public_composition_future_date"
            return [row]
        start = text.find("Top 10 Holdings")
        end = text.find("Countries", start)
        section = text[start:end] if start >= 0 and end > start else ""
        # Table rows and adjacent linked holding-name/percentage text are both
        # used by public profile templates. No country/sector is guessed.
        holdings = []
        for name, weight in re.findall(r"([A-Za-z][^%]*?)\s+(\d+(?:\.\d+)?)%", section):
            name = name.strip()
            if name.casefold().startswith(("top 10 holdings", "weight of top 10 holdings")):
                continue
            holdings.append(dict(holding_name=name, weight=float(weight) / 100, country="", sector="", as_of_date=effective, known_at=known_at, source=url, authority="vendor"))
        if holdings and 0 < sum(item["weight"] for item in holdings) <= 1.01:
            row["holdings"] = holdings
        elif holdings:
            row["holdings_unavailable_reason"] = "public_holdings_weights_not_usable"
        splits = dict(instrument_id=instrument.id, as_of=effective, known_at=known_at, source_id=url, source_authority="public_page")
        for dimension, start_label, end_label in (("country", "Countries", "Sectors"), ("sector", "Sectors", "As of")):
            start = text.find(start_label)
            finish = text.find(end_label, start + len(start_label))
            if start >= 0 and finish > start:
                pairs = re.findall(r"([A-Za-z][^%]*?)\s+(\d+(?:\.\d+)?)%", text[start + len(start_label):finish])
                values = {"Other/unclassified" if name.strip() == "Other" else name.strip(): float(weight) / 100 for name, weight in pairs}
                if values and sum(values.values()) <= 1.01:
                    splits[dimension + "_split"] = values
        return [row, splits]
    return [row]


def _issuer_records(payload: bytes, instrument, known_at: str, url: str, kind: str) -> list[dict]:
    if kind == "holdings":
        frame = pd.read_csv(BytesIO(payload))
        # Only explicitly labelled, identity-bound CSV formats are accepted.
        if "isin" not in frame or not frame["isin"].astype(str).eq(instrument.isin).any():
            raise ValueError("issuer_csv_fund_identity_missing")
        frame = frame.loc[frame["isin"].astype(str).eq(instrument.isin)]
        if not {"as_of_date", "holding_name", "weight"} <= set(frame):
            raise ValueError("issuer_csv_template_unsupported")
        dates = pd.to_datetime(frame["as_of_date"], utc=True, errors="coerce")
        weights = pd.to_numeric(frame["weight"], errors="coerce")
        if dates.isna().any() or dates.nunique() != 1 or dates.max() > pd.Timestamp(known_at):
            raise ValueError("issuer_csv_date_not_usable")
        if weights.isna().any() or weights.lt(0).any() or not 0 < weights.sum() <= 1.01:
            raise ValueError("issuer_csv_weights_not_usable")
        frame["as_of_date"] = dates.dt.date.map(str)
        frame["weight"] = weights
        holdings = frame.to_dict("records")
        for holding in holdings:
            holding.update(known_at=known_at, source=url, authority="issuer")
        return [dict(instrument_id=instrument.id, as_of=frame["as_of_date"].max(), known_at=known_at, source_id=url, source_authority="issuer_document", holdings=holdings)]
    if not payload.startswith(b"%PDF"):
        raise ValueError("issuer_document_not_pdf")
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("issuer_pdf_parser_unavailable") from exc
    with pdfplumber.open(BytesIO(payload)) as document:
        if len(document.pages) > 12:
            raise ValueError("issuer_document_page_limit")
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    if set(re.findall(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b", text)) != {instrument.isin}:
        raise ValueError("issuer_identity_mismatch")
    date_match = re.search(r"(?:Factsheet\s*\||Data as at|As at|as of)\s*(\d{1,2}\s+[A-Za-z]+\s+20\d{2})", text, re.I)
    if date_match is None:
        raise ValueError("issuer_document_date_missing")
    effective = _document_date(date_match[1])
    if pd.Timestamp(effective, tz="UTC") > pd.Timestamp(known_at):
        raise ValueError("issuer_document_future_date")
    row = _parse_fields(" ".join(text.split()), dict(instrument_id=instrument.id, as_of=effective, known_at=known_at, source_id=url, source_authority="issuer_document"))
    # A single-share-class factsheet must bind the explicit ISIN and policy;
    # do not infer policy from the configured instrument name.
    if re.search(r"\b" + re.escape(instrument.isin) + r"\s+Accumulated\b", text):
        row["distribution_policy"] = "accumulating"
    # Accept only unambiguous labelled percentage rows. Unsupported multi-column
    # layouts stay unavailable instead of being guessed from nearby numbers.
    for dimension, start_label, end_label in (("sector", "Weighted exposure", "Market allocation"), ("country", "Market allocation", "Glossary")):
        start, end = text.find(start_label), text.find(end_label)
        if start >= 0 and end > start:
            pairs = re.findall(r"^\s*([A-Za-z][A-Za-z .&/-]+?)\s+(\d+(?:\.\d+)?)%?\s*$", text[start + len(start_label):end], re.M)
            values = {"Other/unclassified" if name.strip() == "Other" else name.strip(): float(weight) / 100 for name, weight in pairs}
            if values and sum(values.values()) <= 1.01:
                row[dimension + "_split"] = values
    return [row]


def _envelope(row: dict, instrument_id: str) -> dict:
    """Reuse the importer's existing field_name/value provenance columns."""
    return dict(row, etf_id=instrument_id, as_of_date=pd.Timestamp(row["as_of"]).date(), provider=row.get("source_authority", "yfinance"), field_name=_CONTEXT_FIELD, value=json.dumps(row, sort_keys=True, default=str))


def decode_e1_reference_context(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in frame.to_dict("records"):
        if row.get("field_name") == _CONTEXT_FIELD:
            try:
                context = json.loads(row["value"])
                if not isinstance(context, dict) or context.get("instrument_id") != row.get("instrument_id", row.get("etf_id")):
                    continue
                row.update(context)
            except (TypeError, ValueError):
                continue
        rows.append(row)
    result = pd.DataFrame(rows)
    result.attrs.update(frame.attrs)
    return result


def fetch_etf_e1_reference_data(config, provider, *, http_get=None, now=None, registry=None, checkpoint=None):
    """Issuer -> public -> yfinance readers; a failed source never aborts refresh.

    ``checkpoint`` is called before each instrument so a user cancellation stops the network
    acquisition promptly (it raises the workflow's cancellation error)."""
    get = http_get or _get
    acquired = (now or datetime.now(timezone.utc)).isoformat()
    def observed_time():
        return (now or datetime.now(timezone.utc)).isoformat()
    messages = []
    if registry is None:
        try:
            registry = read_document_registry()
        except Exception as exc:
            registry = pd.DataFrame()
            messages.append(f"ETF issuer registry: {type(exc).__name__}")
    metadata_rows, holding_rows = [], []
    vendor_results = {}

    def vendor_result(dataset):
        if dataset not in vendor_results:
            try:
                vendor_results[dataset] = getattr(provider, "fetch_" + dataset)([])
            except Exception as exc:
                vendor_results[dataset] = ProviderResult("yfinance", dataset, "unavailable", type(exc).__name__)
        return vendor_results[dataset]

    for instrument in config.universe.etfs:
        if str(instrument.instrument_type).casefold() != "etf" or not instrument.enabled:
            continue
        if checkpoint is not None:
            checkpoint()
        cache = {}
        def profile():
            if "body" not in cache:
                cache["body"] = get(_public_url(instrument.isin), timeout=10)
            return cache["body"]
        def issuer_reader(_instrument_id):
            bindings = []
            if not registry.empty:
                for binding in registry.to_dict("records"):
                    if binding.get("instrument_id") == instrument.id and binding.get("authority") == "issuer_document" and binding.get("document_type") in {"factsheet", "kid", "holdings"} and binding.get("source_url"):
                        bindings.append((binding["source_url"], binding["document_type"]))
            if instrument.isin in _ISSUER_DOCUMENTS:
                bindings.append((_ISSUER_DOCUMENTS[instrument.isin], "factsheet"))
            if not bindings:
                # Discovery downloads only the public profile. Its observations
                # are not selected until after the issuer documents were tried.
                body = profile()
                _public_records(body, instrument, acquired, _public_url(instrument.isin))
                parsed = _Profile(body.decode("utf-8"))
                bindings = [(urljoin(_public_url(instrument.isin), link), "factsheet") for link, label in parsed.links if label.strip().casefold() == "factsheet (en)"]
            rows, errors = [], []
            for url, kind in dict.fromkeys(bindings):
                try:
                    payload = get(url, timeout=10)
                    rows.extend(_issuer_records(payload, instrument, observed_time(), url, kind))
                except Exception as exc:
                    from etf_cockpit.core.session_log import redact_text

                    errors.append(redact_text(f"{type(exc).__name__}: {exc}"))
            if errors:
                messages.append(f"{instrument.id} issuer: " + "; ".join(errors))
            if not rows:
                raise ValueError("; ".join(errors) if errors else "issuer_source_binding_missing")
            return rows
        def public_reader(_instrument_id):
            body = profile()
            return _public_records(body, instrument, observed_time(), _public_url(instrument.isin))
        def vendor_reader(_instrument_id):
            result = vendor_result("etf_metadata")
            if result.data is None:
                raise ValueError(str(result.message))
            rows = []
            for row in result.data.to_dict("records"):
                if row.get("etf_id") == instrument.id:
                    row.update(instrument_id=instrument.id, as_of=str(row["as_of_date"]), known_at=observed_time(), source_id="yfinance", source_authority="yfinance", fee_unit="decimal_fraction")
                    rows.append(row)
            if not rows:
                raise ValueError("yfinance_instrument_unavailable")
            return rows
        result = fetch_etf_economics_sources(instrument.id, decision_time=observed_time, issuer_reader=issuer_reader, public_reader=public_reader, vendor_reader=vendor_reader)
        for name, reason in result["failure_details"].items():
            messages.append(f"{instrument.id} {name}: {reason}")
        for source_rows in result["records"]:
            for row in source_rows:
                row["source_failures"] = result["failure_details"]
                metadata_rows.append(_envelope(row, instrument.id))
                if row.get("holdings_unavailable_reason"):
                    messages.append(f"{instrument.id} holdings: {row['holdings_unavailable_reason']}")
                for holding in row.get("holdings", ()):
                    holding_rows.append(_envelope(dict(holding, instrument_id=instrument.id, as_of=holding["as_of_date"], source_id=holding["source"]), instrument.id))

    vendor_holdings = vendor_result("etf_holdings")
    if vendor_holdings.data is not None:
        present = {row["etf_id"] for row in holding_rows}
        for row in vendor_holdings.data.to_dict("records"):
            if row["etf_id"] not in present:
                row.update(instrument_id=row["etf_id"], as_of=str(row["as_of_date"]), known_at=observed_time(), source_id="yfinance_top_holdings", authority="vendor")
                holding_rows.append(_envelope(row, row["etf_id"]))
    if holding_rows:
        from etf_cockpit.data.fund_holdings import holdings_splits, select_holdings_as_of

        selected_rows = []
        frame = pd.DataFrame(holding_rows)
        for instrument_id in frame["etf_id"].unique():
            selected = select_holdings_as_of(frame, instrument_id, observed_time())
            if holdings_splits(selected)["reason"] is None:
                selected_rows.extend(selected.to_dict("records"))
            else:
                messages.append(f"{instrument_id} holdings: holdings_weights_not_usable")
        holding_rows = selected_rows
    if not vendor_holdings.ok:
        messages.append(f"etf_holdings: {vendor_holdings.message}")
    # Retain the existing non-ETF vendor reference rows as part of the same
    # publication, without changing stock acquisition or contracts.
    metadata = vendor_result("etf_metadata")
    if not metadata.ok:
        messages.append(f"etf_metadata: {metadata.message}")
    if metadata.data is not None:
        present = {row.get("etf_id") for row in metadata_rows}
        metadata_rows.extend(row for row in metadata.data.to_dict("records") if row.get("etf_id") not in present)
    results = []
    for dataset, rows in (("etf_metadata", metadata_rows), ("etf_holdings", holding_rows)):
        results.append((dataset, ProviderResult("etf_e1_sources", dataset, "ok" if rows else "unavailable", f"ETF source chain acquired {len(rows)} {dataset} rows.", pd.DataFrame(rows) if rows else None)))
    return results, messages


def _document_date(text: str) -> str:
    """Issuer documents write '31 August 2026' or '31 Aug 2026'."""

    for pattern in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"issuer_document_date_unparsed: {text!r}")
