"""Phase 0 gate: prove the Tavily runtime call works and returns usable evidence.

The query targets a dependency and its resolved version, never the boilerplate
name -- searching the boilerplate name returns noise. Structured vulnerability
databases are excluded on purpose: they hold CVEs, not the failure narratives
this agent needs.

Run: python scripts/smoke_tavily.py
"""

from __future__ import annotations

import json
import os
import time

from dotenv import load_dotenv
from tavily import TavilyClient

# Resolved from the target's uv.lock, not the ">=" floors in pyproject.toml.
QUERY = "asyncpg 0.31.0 connection pool exhaustion not recovering"

INCLUDE_DOMAINS = [
    "github.com",
    "stackoverflow.com",
    "dev.to",
    "medium.com",
]

# CVE databases carry vulnerabilities, not "why the pool never recovers".
EXCLUDE_DOMAINS = [
    "nvd.nist.gov",
    "osv.dev",
]

# Source-file links are not failure narratives.
NOISE_PATH_MARKERS = ("/commit/", "/blob/")


def main() -> int:
    load_dotenv()
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        print("TAVILY_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1

    client = TavilyClient(api_key=key)

    print(f"query: {QUERY}")
    started = time.perf_counter()
    try:
        resp = client.search(
            query=QUERY,
            search_depth="advanced",
            max_results=5,
            include_domains=INCLUDE_DOMAINS,
            exclude_domains=EXCLUDE_DOMAINS,
        )
    except Exception as exc:  # noqa: BLE001 - smoke test reports, never raises
        print(f"FAIL  {type(exc).__name__}: {exc}")
        return 1

    elapsed = time.perf_counter() - started
    results = resp.get("results", [])
    print(f"OK    {len(results)} results in {elapsed:.2f}s")
    print()

    kept = 0
    for i, r in enumerate(results, 1):
        url = r.get("url", "")
        noisy = any(m in url for m in NOISE_PATH_MARKERS)
        verdict = "filtered" if noisy else "usable"
        if not noisy:
            kept += 1
        print(f"[{i}] {verdict}  score={r.get('score', 0):.3f}")
        print(f"    {r.get('title', '')}")
        print(f"    {url}")
        snippet = (r.get("content") or "").replace("\n", " ")[:200]
        print(f"    {snippet}")
        print()

    print("--- raw response ---")
    print(json.dumps(resp, indent=2)[:3000])

    print()
    if kept == 0:
        print("No usable results after filtering. Tighten the query before Phase 2.")
        return 1
    print(f"{kept} usable result(s) after path filtering.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
