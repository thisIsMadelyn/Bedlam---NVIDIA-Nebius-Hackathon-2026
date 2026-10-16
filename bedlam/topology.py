"""The target stack's topology: the single source of truth for where each
layer lives and what reaches it.

Faults and probes both resolve endpoints through here -- never hardcode a
host, port or proxy name at a call site. Blast radius is a static lookup
over this topology, computed before a fault is injected, not inferred from
probe results after the fact.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Layer(StrEnum):
    """The three tiers of the target stack."""

    API = "api"
    DB = "db"
    CACHE = "cache"


@dataclass(frozen=True, slots=True)
class LayerEndpoint:
    """Where Bedlam reaches a layer, and whether Toxiproxy fronts it.

    `proxy_name` is the Toxiproxy proxy this layer is faulted through. It is
    `None` for the API layer: Phase 1 fronts only Postgres and Redis, per
    PLAN.md -- the API layer has no fault primitive of its own yet.
    """

    layer: Layer
    host: str
    port: int
    proxy_name: str | None
    description: str


def _endpoint(
    layer: Layer,
    *,
    env_host: str,
    env_port: str,
    default_host: str,
    default_port: int,
    proxy_name: str | None,
    description: str,
) -> LayerEndpoint:
    host = os.environ.get(env_host, default_host)
    port = int(os.environ.get(env_port, str(default_port)))
    return LayerEndpoint(
        layer=layer, host=host, port=port, proxy_name=proxy_name, description=description
    )


def _build_topology() -> dict[Layer, LayerEndpoint]:
    api_url = os.environ.get("BEDLAM_API_URL", "http://localhost:8000")
    api_host = api_url.split("://", 1)[-1].split(":")[0]
    api_port = int(api_url.rsplit(":", 1)[-1]) if ":" in api_url.split("://", 1)[-1] else 80

    return {
        Layer.API: LayerEndpoint(
            layer=Layer.API,
            host=api_host,
            port=api_port,
            proxy_name=None,
            description="FastAPI app, probed directly over HTTP. Not fronted by Toxiproxy.",
        ),
        Layer.DB: _endpoint(
            Layer.DB,
            env_host="BEDLAM_DB_PROXY_HOST",
            env_port="BEDLAM_DB_PROXY_PORT",
            default_host="localhost",
            default_port=5433,
            proxy_name="postgres",
            description="Postgres, reached through its Toxiproxy proxy.",
        ),
        Layer.CACHE: _endpoint(
            Layer.CACHE,
            env_host="BEDLAM_CACHE_PROXY_HOST",
            env_port="BEDLAM_CACHE_PROXY_PORT",
            default_host="localhost",
            default_port=6380,
            proxy_name="redis",
            description="Redis, reached through its Toxiproxy proxy.",
        ),
    }


TOPOLOGY: Final[dict[Layer, LayerEndpoint]] = _build_topology()

# Static dependency graph: which layers a request through the API actually
# touches. The API depends on both the db and the cache; neither depends on
# the API or on each other.
_DEPENDS_ON_API: Final[frozenset[Layer]] = frozenset({Layer.DB, Layer.CACHE})


def endpoint_for(layer: Layer) -> LayerEndpoint:
    return TOPOLOGY[layer]


def blast_radius(layer: Layer) -> frozenset[Layer]:
    """Which layers are affected if `layer` is faulted.

    Computed from the static topology above, before any toxic is created --
    never measured after injection by comparing probe snapshots.
    """
    affected = {layer}
    if layer in _DEPENDS_ON_API:
        affected.add(Layer.API)
    return frozenset(affected)
