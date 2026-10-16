"""Thin async wrapper over Toxiproxy's control API.

Every fault primitive in `primitives.py` goes through this client. Nothing
here knows about Postgres or Redis specifically -- it only knows proxies and
toxics, exactly as Toxiproxy's REST API models them.
"""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any

import httpx

from bedlam.logging import get_logger, log_event

_LOG = get_logger("bedlam.faults.toxiproxy")


class ToxiproxyClient:
    """Async client for Toxiproxy's control API (default: localhost:8474)."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or os.environ.get("TOXIPROXY_URL", "http://localhost:8474")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=5.0)

    async def __aenter__(self) -> ToxiproxyClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def version(self) -> str:
        resp = await self._client.get("/version")
        resp.raise_for_status()
        return resp.text

    async def list_proxies(self) -> dict[str, Any]:
        resp = await self._client.get("/proxies")
        resp.raise_for_status()
        return resp.json()

    async def get_proxy(self, name: str) -> dict[str, Any]:
        resp = await self._client.get(f"/proxies/{name}")
        resp.raise_for_status()
        return resp.json()

    async def set_proxy_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        resp = await self._client.post(f"/proxies/{name}", json={"enabled": enabled})
        resp.raise_for_status()
        log_event(_LOG, "proxy toggled", proxy=name, enabled=enabled)
        return resp.json()

    async def list_toxics(self, proxy: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f"/proxies/{proxy}/toxics")
        resp.raise_for_status()
        return resp.json()

    async def create_toxic(
        self,
        proxy: str,
        *,
        name: str,
        kind: str,
        stream: str,
        toxicity: float,
        attributes: dict[str, int],
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "type": kind,
            "stream": stream,
            "toxicity": toxicity,
            "attributes": attributes,
        }
        resp = await self._client.post(f"/proxies/{proxy}/toxics", json=body)
        resp.raise_for_status()
        log_event(_LOG, "toxic created", proxy=proxy, toxic=name, kind=kind, attributes=attributes)
        return resp.json()

    async def delete_toxic(self, proxy: str, name: str) -> None:
        resp = await self._client.delete(f"/proxies/{proxy}/toxics/{name}")
        if resp.status_code != 404:
            resp.raise_for_status()
        log_event(_LOG, "toxic removed", proxy=proxy, toxic=name)
