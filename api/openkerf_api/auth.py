"""
Write-action protection.

Reading is always open. Writing — anything that moves the machine or queues a
job — needs a token as soon as the API is reachable beyond this computer.
Binding to localhost keeps a local session frictionless; binding to 0.0.0.0 so
the phone can reach it is exactly when a stray request becomes dangerous.
"""

import ipaddress
import secrets

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def is_loopback(bind: str) -> bool:
    if bind in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(bind).is_loopback
    except ValueError:
        return False


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def extract_token(headers) -> str | None:
    """Accept either `Authorization: Bearer <token>` or `X-OpenKerf-Token`."""
    header = headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return headers.get("x-openkerf-token")


def token_matches(supplied: str | None, expected: str) -> bool:
    if not supplied:
        return False
    # Constant-time: token comparison should not leak length or prefix.
    return secrets.compare_digest(supplied, expected)
