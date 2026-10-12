"""Credentials for satellite services, read from environment variables only.

Secrets never leave memory: `Credential` hides its values from repr/str, errors name only the
missing variable NAMES, and `redact` scrubs secret values from any text (e.g. exception
messages that might echo a URL) before it is printed or written to provenance.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

import requests


class AuthenticationBoundary(RuntimeError):
    """Required credentials are not configured. The message lists variable names only."""

    def __init__(self, service: str, missing: list[str]) -> None:
        self.service = service
        self.missing = missing
        super().__init__(
            f"{service}: credentials not configured; set {', '.join(missing)} in .env "
            "(see .env.example). Stopping at the authentication boundary."
        )


@dataclass(frozen=True)
class Credential:
    service: str
    user_var: str
    secret_var: str
    user: str = field(repr=False)
    secret: str = field(repr=False)

    def __str__(self) -> str:
        return f"Credential({self.service}: {self.user_var}=<set>, {self.secret_var}=<set>)"

    __repr__ = __str__

    def basic_auth(self) -> requests.auth.HTTPBasicAuth:
        return requests.auth.HTTPBasicAuth(self.user, self.secret)

    def redact(self, text: str) -> str:
        return redact(text, [self.user, self.secret])


def status(names: list[str], env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Which variables are set (booleans only — never values)."""
    env = os.environ if env is None else env
    return {n: bool(env.get(n)) for n in names}


def load(
    service: str, user_var: str, secret_var: str, env: Mapping[str, str] | None = None
) -> Credential:
    env = os.environ if env is None else env
    missing = [n for n in (user_var, secret_var) if not env.get(n)]
    if missing:
        raise AuthenticationBoundary(service, missing)
    return Credential(service, user_var, secret_var, env[user_var], env[secret_var])


def redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return text
