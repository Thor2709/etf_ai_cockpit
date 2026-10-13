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


def requests_get_checked(
    get: Callable[..., object],
    url: str,
    *,
    allowed: Callable[[str], bool],
    max_redirects: int = 3,
    **kwargs: object,
) -> object:
    """Call a ``requests.get``-style function, following only redirects `allowed` approves.

    The first URL is the caller's own; every redirect target is checked before it is
    requested, so credentials in `kwargs` (headers) never reach an unapproved host.
    """
    current = url
    for _ in range(max_redirects + 1):
        response = get(current, allow_redirects=False, **kwargs)
        status = getattr(response, "status_code", 200)
        if not isinstance(status, int) or status not in REDIRECT_STATUSES:
            return response
        headers = getattr(response, "headers", None) or {}
        current = urljoin(current, str(headers.get("Location", "")))
        if not allowed(current):
            raise ValueError("source_redirect_not_supported")
    raise ValueError("source_redirect_limit")


def same_host_https(reference_url: str) -> Callable[[str], bool]:
    """Return a predicate approving only HTTPS URLs on the host of `reference_url`."""
    from urllib.parse import urlsplit

    host = (urlsplit(reference_url).hostname or "").lower().rstrip(".")

    def allowed(candidate: str) -> bool:
        parts = urlsplit(candidate)
        return parts.scheme == "https" and bool(host) and (parts.hostname or "").lower().rstrip(".") == host

    return allowed


_NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirect())


def host_checked_urlopen(request: Request, timeout: float | None = None, *, max_redirects: int = 3):
    """``urlopen`` drop-in that follows redirects only to the request's own HTTPS host.

    A redirect to any other host (or to plain HTTP) raises ValueError before that URL is
    contacted, so URL- or header-borne credentials never leave the provider's host.
    """
    allowed = same_host_https(request.full_url)
    current = request
    for _ in range(max_redirects + 1):
        try:
            return _NO_REDIRECT_OPENER.open(current, timeout=timeout)
        except HTTPError as exc:
            if exc.code not in REDIRECT_STATUSES:
                raise
            target = urljoin(current.full_url, exc.headers.get("Location", ""))
            if not allowed(target):
                raise ValueError("source_redirect_not_supported") from exc
            current = Request(target, headers=dict(current.header_items()), method="GET")
    raise ValueError("source_redirect_limit")
