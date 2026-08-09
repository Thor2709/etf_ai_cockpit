from __future__ import annotations

from collections.abc import Callable
import ipaddress
import socket
from typing import Any


def _is_loopback(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0]).strip().strip("[]")
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def install() -> Callable[[], None]:
    """Deny non-loopback INET connections and return an idempotent restore hook."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def guarded_connect(instance: socket.socket, address: Any) -> Any:
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback socket: {address!r}")
        return original_connect(instance, address)

    def guarded_connect_ex(instance: socket.socket, address: Any) -> int:
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback socket: {address!r}")
        return original_connect_ex(instance, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        if not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback socket: {address!r}")
        return original_create_connection(address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection
    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection
        restored = True

    return restore
