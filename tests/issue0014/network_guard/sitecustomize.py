from __future__ import annotations

import os

if os.getenv("ETF_COCKPIT_SOCKET_GUARD") == "1":
    from tests.issue0014._socket_guard import install

    install()
