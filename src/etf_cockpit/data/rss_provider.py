from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RssProbe:
    provider_id: str
    status: str
    message: str


class RssProvider:
    def __init__(self, feeds: tuple[str, ...] = ()) -> None:
        self.feeds = feeds

    def probe(self) -> RssProbe:
        if not self.feeds:
            return RssProbe("rss", "unavailable", "RSS is disabled until an explicit local feed list is configured.")
        return RssProbe("rss", "configured", "RSS feed list configured; no network request was made by the probe.")
