"""Bounded GET that follows redirects only to caller-approved URLs."""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class NoRedirect(HTTPRedirectHandler):
    """Disable automatic redirects so an unapproved target is never contacted."""

    def redirect_request(self, *_args, **_kwargs):
        return None


def get_checked(
    url: str,
    *,
    allowed: Callable[[str], bool],
    headers: Mapping[str, str],
    timeout: float,
    max_bytes: int,
    max_redirects: int = 3,
) -> tuple[bytes, int, Mapping[str, str]]:
    """GET `url`, following at most `max_redirects` redirects that `allowed` approves.

    Returns (payload read up to max_bytes + 1, status, headers). A redirect to a URL
    that `allowed` rejects raises ValueError("source_redirect_not_supported") before
    that URL is contacted; other HTTP errors propagate unchanged.
    """
    opener = urllib.request.build_opener(NoRedirect())
    for _ in range(max_redirects + 1):
        try:
            with opener.open(Request(url, headers=dict(headers)), timeout=timeout) as response:
                payload = response.read(max_bytes + 1)
                return payload, int(getattr(response, "status", 200)), getattr(response, "headers", {})
        except HTTPError as exc:
            if exc.code not in REDIRECT_STATUSES:
                raise
            url = urljoin(url, exc.headers.get("Location", ""))
            if not allowed(url):
                raise ValueError("source_redirect_not_supported") from exc
    raise ValueError("source_redirect_limit")
