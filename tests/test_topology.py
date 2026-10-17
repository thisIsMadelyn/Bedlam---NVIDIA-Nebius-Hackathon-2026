"""Topology: how BEDLAM_API_URL becomes the API layer's endpoint."""

from __future__ import annotations

import pytest

from bedlam.topology import Layer, _build_topology


def _api(monkeypatch: pytest.MonkeyPatch, url: str):
    monkeypatch.setenv("BEDLAM_API_URL", url)
    return _build_topology()[Layer.API]


@pytest.mark.parametrize(
    ("url", "host", "port", "base_url"),
    [
        ("http://localhost:8000", "localhost", 8000, "http://localhost:8000"),
        ("http://localhost:8000/", "localhost", 8000, "http://localhost:8000"),
        ("http://localhost:8000/api", "localhost", 8000, "http://localhost:8000"),
        ("localhost:8000", "localhost", 8000, "http://localhost:8000"),
        ("http://localhost", "localhost", 80, "http://localhost:80"),
        ("https://api.test", "api.test", 443, "https://api.test:443"),
        ("https://api.test:8443/", "api.test", 8443, "https://api.test:8443"),
        ("http://[::1]:8000/", "::1", 8000, "http://[::1]:8000"),
    ],
)
def test_api_url_resolves_host_port_and_base_url(
    monkeypatch: pytest.MonkeyPatch, url: str, host: str, port: int, base_url: str
) -> None:
    api = _api(monkeypatch, url)
    assert (api.host, api.port, api.base_url) == (host, port, base_url)


@pytest.mark.parametrize("url", ["http://", "ftp://localhost:8000"])
def test_unusable_api_url_is_rejected_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    with pytest.raises(ValueError, match="BEDLAM_API_URL"):
        _api(monkeypatch, url)


def test_proxied_layers_have_no_base_url() -> None:
    topology = _build_topology()
    assert topology[Layer.DB].base_url is None
    assert topology[Layer.CACHE].base_url is None
