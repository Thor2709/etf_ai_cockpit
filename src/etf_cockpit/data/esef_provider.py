from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import pandas as pd

from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.data.providers import ProviderResult


Transport = Callable[[str, dict[str, str]], bytes]


class FilingsXbrlOrgProvider:
    def __init__(self, *, cache_dir: Path, transport: Transport | None = None, timeout: float = 20.0) -> None:
        self.cache_dir = cache_dir
        self.transport = transport
        self.timeout = timeout

    def list_filings(self, country: str, limit: int = 10) -> ProviderResult:
        url = f"https://filings.xbrl.org/api/filings?filter[country]={country}&sort=-processed&page[size]={limit}"
        try:
            payload = self._get(url)
            parsed = json.loads(payload.decode("utf-8"))
            data = parsed.get("data", []) if isinstance(parsed, dict) else parsed
            if not isinstance(data, list):
                raise ValueError("filings response data must be a list")
            return ProviderResult(
                "filings_xbrl_org",
                "filings",
                "ok",
                "Official filings discovery response loaded.",
                data=pd.DataFrame(data),
            )
        except Exception as exc:
            return ProviderResult("filings_xbrl_org", "filings", "error", f"Official filings discovery unavailable: {type(exc).__name__}")

    def download_report_package(self, filing_id: str, package_url: str) -> RawDocument:
        payload = self._get(package_url)
        path = self.cache_dir / f"{filing_id}.xbri"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return RawDocument(path, package_url, datetime.now(timezone.utc), hashlib.sha256(payload).hexdigest(), "filings_xbrl_org", "esef_report_package", "application/octet-stream", 200)

    def _get(self, url: str) -> bytes:
        headers = {"User-Agent": "ETF AI Evidence Cockpit/1.0"}
        if self.transport is not None:
            return self.transport(url, headers)
        request = Request(url, headers=headers)
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()
