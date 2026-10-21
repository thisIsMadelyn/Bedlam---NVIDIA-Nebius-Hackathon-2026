"""Probe through the app: did the developer's patch hold?

The layer probes reach Postgres and Redis straight through Toxiproxy, past
the app, so no patch to the app can change what they see. This probe goes
through the app instead: one authenticated read that loads the session from
Redis and the tiers from Postgres. The loop runs it under the fault before
the patch, and again once the api runs the patch and the same fault is back,
and compares the two.

Signing in is the one write: once, at baseline, before any fault, as the
admin `make up` seeds. Every probe after it is a read.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from bedlam.logging import get_logger, log_event
from bedlam.topology import Layer, endpoint_for

_LOG = get_logger("bedlam.probes.app")

# Longer than the layer probes' 2s: a patch that adds a 5s pool timeout must
# be able to fail fast inside the window, or both sides read as a hang.
APP_TIMEOUT_S: Final[float] = 6.0
SIGN_IN_PATH: Final = "/api/v1/auth/login"
READ_PATH: Final = "/api/v1/tiers/"
# Defaults match docker-compose.yml; both are local placeholders.
_USERNAME_ENV: Final = "BEDLAM_ADMIN_USERNAME"
_PASSWORD_ENV: Final = "BEDLAM_ADMIN_PASSWORD"
_DEFAULT_USERNAME: Final = "bedlam"
_DEFAULT_PASSWORD: Final = "Bedlam-local-1"
# From a hang or a slow answer, a patch held if the read now ends this many
# times faster.
HELD_SPEEDUP: Final = 2.0


class AppSignInError(RuntimeError):
    """The probe could not sign in, so it cannot read through the app."""


@dataclass(frozen=True, slots=True)
class AppResult:
    ok: bool  # the read answered 2xx
    latency_ms: float
    status_code: int | None = None  # None: no HTTP answer at all
    error: str | None = None

    @property
    def hung(self) -> bool:
        return self.error is not None and "Timeout" in self.error

    def text(self) -> str:
        ms = f"{self.latency_ms:.0f}ms"
        if self.ok:
            return f"answered in {ms}"
        if self.hung:
            return f"hung {ms}"
        if self.status_code is not None:
            return f"{self.status_code} in {ms}"
        return f"failed in {ms}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1),
            "status_code": self.status_code,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> AppResult:
        return cls(body["ok"], body["latency_ms"], body["status_code"], body["error"])


def held(before: AppResult, after: AppResult) -> bool:
    """The rule: the read went from hanging or erroring to answering; or it
    hung, or answered slowly, and now ends at least `HELD_SPEEDUP` times
    faster without getting worse. Both numbers are always shown.

    An error that comes back faster is still an error, so a speedup counts
    only from a hang or from a slow answer to an answer."""
    if after.ok and not before.ok:
        return True
    faster = after.latency_ms * HELD_SPEEDUP <= before.latency_ms
    if before.hung and not after.hung:
        return faster
    if before.ok and after.ok:
        return faster
    return False


class AppProbe:
    """Signs in once, then reads through the app on every call."""

    def __init__(self, *, timeout_s: float = APP_TIMEOUT_S) -> None:
        base_url = endpoint_for(Layer.API).base_url
        if base_url is None:
            raise ValueError("the api layer has no base URL")
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._session: str | None = None

    async def sign_in(self) -> None:
        credentials = {
            "username": os.environ.get(_USERNAME_ENV, _DEFAULT_USERNAME),
            "password": os.environ.get(_PASSWORD_ENV, _DEFAULT_PASSWORD),
        }
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_s) as client:
            resp = await client.post(SIGN_IN_PATH, data=credentials)
        session = resp.cookies.get("session_id")
        if resp.status_code != 200 or not session:
            raise AppSignInError(
                f"sign-in answered HTTP {resp.status_code}. Run `make up`: it seeds the admin."
            )
        self._session = session
        log_event(_LOG, "signed in")

    async def __call__(self) -> AppResult:
        if self._session is None:
            await self.sign_in()
        # The session cookie is marked Secure; over plain http to localhost
        # it is sent by hand.
        cookies = {"session_id": self._session or ""}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout_s, cookies=cookies
            ) as client:
                resp = await client.get(READ_PATH)
        except Exception as exc:  # noqa: BLE001 - any failure is the measurement
            elapsed_ms = (time.perf_counter() - started) * 1000
            return AppResult(False, elapsed_ms, None, f"{type(exc).__name__}: {exc}")
        elapsed_ms = (time.perf_counter() - started) * 1000
        ok = 200 <= resp.status_code < 300
        error = None if ok else f"HTTP {resp.status_code}"
        return AppResult(ok, elapsed_ms, resp.status_code, error)
