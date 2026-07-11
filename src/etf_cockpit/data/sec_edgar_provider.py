from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from etf_cockpit.parsers.contracts import RawDocument


Transport = Callable[[str, dict[str, str]], bytes]


class SecEdgarProvider:
    def __init__(self, user_agent: str, *, cache_dir: Path, transport: Transport | None = None, timeout: float = 20.0) -> None:
        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError("SEC provider requires a descriptive User-Agent with contact email")
        self.user_agent = user_agent.strip()
        self.cache_dir = cache_dir
        self.transport = transport
        self.timeout = timeout

    def fetch_companyfacts(self, cik: str) -> RawDocument:
        cik_text = str(cik).strip().zfill(10)
        return self._fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_text}.json", f"companyfacts_{cik_text}.json", "sec_companyfacts")

    def fetch_submissions(self, cik: str) -> RawDocument:
        cik_text = str(cik).strip().zfill(10)
        return self._fetch(f"https://data.sec.gov/submissions/CIK{cik_text}.json", f"submissions_{cik_text}.json", "sec_submissions")

    def _fetch(self, url: str, filename: str, document_type: str) -> RawDocument:
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.transport is not None:
            payload = self.transport(url, headers)
            status = 200
        else:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                status = int(response.status)
        json.loads(payload.decode("utf-8"))
        path = self.cache_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return RawDocument(path, url, datetime.now(timezone.utc), hashlib.sha256(payload).hexdigest(), "sec_edgar", document_type, "application/json", status)
