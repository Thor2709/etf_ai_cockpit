from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionalProviderProbe:
    provider_id: str
    status: str
    message: str


class FredProvider:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def probe(self) -> OptionalProviderProbe:
        if not self.api_key.strip():
            return OptionalProviderProbe("fred", "unavailable", "FRED is disabled until a local API key is configured.")
        return OptionalProviderProbe("fred", "configured", "FRED is configured but no network request was made by the probe.")
