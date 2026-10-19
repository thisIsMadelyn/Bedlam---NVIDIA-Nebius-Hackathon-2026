"""Phase 0 gate: prove every model id in the map is callable, verbatim.

Confirms the Nebius Token Factory runtime call works and that the inconsistent
casing of the NVIDIA model ids is accepted exactly as written. Never prints
the API key.

Run: python scripts/smoke_nebius.py
"""

from __future__ import annotations

import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletion

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bedlam.models.map import ALL_KNOWN_MODELS, MODELS  # noqa: E402

PROMPT = "Reply with exactly one word: ok"


def main() -> int:
    load_dotenv()
    key = os.environ.get("NEBIUS_API_KEY")
    base_url = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

    if not key:
        print("NEBIUS_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1

    client = OpenAI(api_key=key, base_url=base_url)
    failures = 0
    last_ok: tuple[str, ChatCompletion] | None = None

    for model in ALL_KNOWN_MODELS:
        in_use = "in use" if model in MODELS else "unused"
        started = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT}],
                max_tokens=16,
                temperature=0.0,
                # Same as ModelClient: with thinking on, the reasoning trace
                # eats the whole 16-token budget and the reply comes back empty.
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except Exception as exc:  # noqa: BLE001 - smoke test reports, never raises
            elapsed = time.perf_counter() - started
            print(f"FAIL  {model}  ({in_use}, {elapsed:.2f}s)")
            print(f"      {type(exc).__name__}: {exc}")
            failures += 1
            continue

        elapsed = time.perf_counter() - started
        content = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        print(f"OK    {model}  ({in_use}, {elapsed:.2f}s)")
        print(f"      content={content!r}")
        if usage:
            print(f"      tokens in={usage.prompt_tokens} out={usage.completion_tokens}")
        last_ok = (model, resp)

    if last_ok:
        last_model, last_resp = last_ok
        print()
        print(f"--- raw response, last successful model: {last_model} ---")
        print(json.dumps(last_resp.model_dump(), indent=2, default=str))

    print()
    if failures:
        print(f"{failures} of {len(ALL_KNOWN_MODELS)} model ids failed.")
        return 1
    print(f"All {len(ALL_KNOWN_MODELS)} model ids callable with exact casing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
