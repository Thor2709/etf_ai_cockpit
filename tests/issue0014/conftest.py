from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.issue0014._socket_guard import install


@pytest.fixture(autouse=True)
def deny_non_loopback_sockets() -> Iterator[None]:
    restore = install()
    try:
        yield
    finally:
        restore()
