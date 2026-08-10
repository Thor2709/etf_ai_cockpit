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


def _is_loopback_host(host: object) -> bool:
    value = str(host).strip().strip("[]")
    if value.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def install() -> Callable[[], None]:
    """Deny non-loopback INET connections and return an idempotent restore hook."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyaddr = socket.gethostbyaddr
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_getnameinfo = socket.getnameinfo
    original_sendto = socket.socket.sendto
    original_sendmsg = getattr(socket.socket, "sendmsg", None)

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

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback_host(host):
            raise PermissionError(f"ISSUE-0014 denied non-loopback hostname: {host!r}")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host: Any) -> str:
        if not _is_loopback_host(host):
            raise PermissionError(f"ISSUE-0014 denied non-loopback hostname: {host!r}")
        return original_gethostbyname(host)

    def guarded_gethostbyname_ex(host: Any) -> tuple[str, list[str], list[str]]:
        if not _is_loopback_host(host):
            raise PermissionError(f"ISSUE-0014 denied non-loopback hostname: {host!r}")
        return original_gethostbyname_ex(host)

    def guarded_gethostbyaddr(host: Any) -> tuple[str, list[str], list[str]]:
        if not _is_loopback_host(host):
            raise PermissionError(f"ISSUE-0014 denied non-loopback hostname: {host!r}")
        return original_gethostbyaddr(host)

    def guarded_getnameinfo(address: Any, flags: int) -> tuple[str, str]:
        if not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback hostname: {address!r}")
        return original_getnameinfo(address, flags)

    def guarded_sendto(instance: socket.socket, data: Any, *args: Any) -> int:
        address = args[-1] if args else None
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback datagram: {address!r}")
        return original_sendto(instance, data, *args)

    def guarded_sendmsg(instance: socket.socket, *args: Any, **kwargs: Any) -> int:
        address = args[3] if len(args) > 3 else kwargs.get("address")
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _is_loopback(address):
            raise PermissionError(f"ISSUE-0014 denied non-loopback datagram: {address!r}")
        assert original_sendmsg is not None
        return original_sendmsg(instance, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyaddr = guarded_gethostbyaddr
    socket.gethostbyname = guarded_gethostbyname
    socket.gethostbyname_ex = guarded_gethostbyname_ex
    socket.getnameinfo = guarded_getnameinfo
    socket.socket.sendto = guarded_sendto  # type: ignore[method-assign]
    if original_sendmsg is not None:
        socket.socket.sendmsg = guarded_sendmsg  # type: ignore[attr-defined,method-assign]
    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection
        socket.getaddrinfo = original_getaddrinfo
        socket.gethostbyaddr = original_gethostbyaddr
        socket.gethostbyname = original_gethostbyname
        socket.gethostbyname_ex = original_gethostbyname_ex
        socket.getnameinfo = original_getnameinfo
        socket.socket.sendto = original_sendto  # type: ignore[method-assign]
        if original_sendmsg is not None:
            socket.socket.sendmsg = original_sendmsg  # type: ignore[attr-defined,method-assign]
        restored = True

    return restore
