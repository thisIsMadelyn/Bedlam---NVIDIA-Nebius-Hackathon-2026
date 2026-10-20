# Session History

A running log of every Claude Code session on this repository. This file is
public — keep entries factual and free of secrets, keys, or internal-only detail.

Each session is logged as it ends. Sessions are listed newest first.

## Format

```
## <local date> <local time>

- **Start status:** <repo/phase state when the session began>
- **End status:** <repo/phase state when the session ended>
- **Badges:**
  - 🆕 Addition — <short description>
  - 🐛 Bug fix — <short description>
```

Badge legend: 🆕 Addition (new capability, file, or feature) · 🐛 Bug fix
(corrects a defect in existing work). A session may carry zero, one, or several
badges of either kind.

---

## Session [2026-10-19-2113]

- **Start status:** `478a3be`, working tree clean, 39 tests passing. Open:
  the suspected HTTP 409 on a leftover Toxiproxy toxic, and the live
  Phase 2 determinism check.
- **End status:** The leftover-toxic bug was reproduced live and fixed
  (`075ef00`). The live determinism check failed: three runs with seed
  1729 gave three different fault sequences, and one run crashed. Root
  cause: Token Factory returns different outputs for identical requests at
  temperature 0 with a fixed seed (layer classification on one frozen
  result set labelled 5/6 one way, 1/6 another). The crash is fixed
  (`e24547a`) and synthesis now runs at temperature 0 (`a9ab11b`). 42
  tests pass, lint and format clean. Measured on frozen inputs: fault
  selection alone is stable (8/8); synthesis keeps a stable eligible pool
  (5/5) but rewords its hypotheses (3 distinct of 5), and the pick follows
  the wording (4/1). A tier-rating selection variant was tried and dropped:
  it rated every fault "medium", which would hand the choice to the RNG.
  Still open, deferred to a later session:
  - Replay test: record one live run's model and Tavily responses, replay
    them, and assert the same fault sequence.
  - Reword the PLAN.md Phase 2 Done-when item from "same seed, same fault
    sequence across three runs" to reproducibility given recorded inputs.
  - Deferred, may not be done: show fault selection only the structured
    candidate fields, not the hypothesis prose.

  Later in the session, `make prove-routing` showed live that Tavily output
  changes the specialist. Three searches gave two distinct specialists
  (db, db, api), and dropping the winning layer's results from the merged
  set moved the route from db to api. It held on a second live run. Three
  Phase 2 Done-when items are now ticked in PLAN.md; the determinism item
  stays open.
- **Badges:**
  - 🆕 Addition — `scripts/prove_routing.py` and `make prove-routing`: runs
    the loop's real search, classify and route path against live Tavily and
    live Nano, with the model side held fixed. It writes the evidence to
    `traces/routing-proof.json` and exits non-zero if routing does not
    follow the search output.
  - 🐛 Bug fix — Layer classification labelled Redis results `db` (20 of 20
    labels on a saved redis-py result set), so the cache specialist was
    never reached. Nano now names the failed component of each result
    before choosing its layer. On the same saved sets, Redis went to
    `cache` 20 of 20 and asyncpg/SQLAlchemy stayed `db` 20 of 20. An
    explicit "Redis is cache" rule was tested and left out: naming the
    component was enough on its own. `make prove-routing` now reaches all
    three specialists (cache, db, api) on two live runs, up from db, db, api.
  - 🐛 Bug fix — Layer classification had `max_tokens=256`, which truncated
    the reply mid-JSON on a 15-result set. It is now 768, enough for the
    loop's maximum of 10 results with the component field.
  - 🐛 Bug fix — A run killed while a fault was live left its toxic in
    Toxiproxy. The next run failed with HTTP 409 when re-creating the same
    toxic name, or failed the baseline with a misleading "Run `make up`"
    message. The loop now clears every toxic on the proxied layers before
    the baseline probe and logs what it removed. `fault.apply()` moved
    inside the `try`, so a toxic is removed even when its create times out
    on the client side. The primitives docstring no longer claims that
    re-injection replaces a toxic.
  - 🐛 Bug fix — On an invalid model reply, the retry resent the identical
    request, which at temperature 0 returned the same invalid answer. Nano
    sites have no fallback, so the run failed (query formulation copied
    the prompt's example failure term and repeated a previous query). The
    retry now includes the rejected reply and the parser's reason. A
    fallback model still gets the original request.
  - 🐛 Bug fix — Synthesis ran at temperature 0.3, so the eligible fault
    pool changed from run to run. It now runs at 0.0, in the model map and
    the PLAN.md table.

## Session [2026-10-19-1051]

- **Start status:** Phase 2 bug fixes committed (`0ebbc9c`, 39 tests
  passing). Working tree clean. Still open: the suspected HTTP 409 on a
  leftover Toxiproxy toxic, and the live Phase 2 determinism check.
- **End status:** `make smoke` passes live. All four model ids are
  callable with their exact casing and each replies `ok`. Tavily returns
  five usable results for a dependency-targeted asyncpg query. Earlier
  runs got HTTP 401 until real keys were in `.env`. The open items from
  the previous session are unchanged.
- **Badges:**
  - 🐛 Bug fix — `scripts/smoke_nebius.py`: when every model failed, the
    raw-response dump crashed with `UnboundLocalError: resp` and hid the
    clean failure summary. When only the last model failed, the dump
    showed an earlier model's response under the wrong label. It now dumps
    the last successful response, names its model, and is skipped when no
    call succeeded.
  - 🐛 Bug fix — `scripts/smoke_nebius.py`: the smoke call left Nemotron's
    thinking mode on, so the reasoning trace used the whole 16-token budget.
    Super and Nano returned empty replies, but the script still reported
    OK. It now sends `enable_thinking: False`, the same way `ModelClient`
    does.

## Session [2026-10-17-2200]

- **Start status:** Phase 2 decision chain built and verified offline
  (`36012ea`, 27 tests passing). Live three-run determinism check still
  pending.
- **End status:** A read-only bug hunt over the whole codebase found three
  confirmed defects and one suspected. All three confirmed defects are fixed
  with regression tests; 39 tests pass, lint and format clean. Still open,
  unverified against a live Toxiproxy: a toxic left behind by a killed run
  may make the next injection of the same fault fail with HTTP 409. The live
  Phase 2 determinism check is still pending.
- **Badges:**
  - 🐛 Bug fix — `bedlam/trace.py`: a run that failed mid-cycle crashed
    while writing its trace (`KeyError: 'selection'`), losing the trace file,
    masking the real error and skipping transport cleanup. Partial cycles are
    now kept in the trace but left out of the fault and specialist sequences.
  - 🐛 Bug fix — `bedlam/topology.py`: `BEDLAM_API_URL` with a trailing
    slash or a path crashed every `bedlam` import. The URL is now parsed with
    `urllib.parse.urlsplit`; unusable URLs fail with a clear message.
  - 🐛 Bug fix — `bedlam/topology.py`, `bedlam/probes/api.py`: an `https`
    API URL without a port resolved to port 80 and was probed over `http`.
    The default port now follows the scheme, and the probe uses a new
    `base_url` on the endpoint, which also keeps IPv6 hosts bracketed.
  - 🆕 Addition — `tests/test_topology.py` and a failed-run trace test in
    `tests/test_loop.py`, covering the three fixes above.

## Session [2026-10-16-2225]

- **Start status:** Phase 1 complete (`900dd61`). Phase 2 (intelligence
  layer, headless) not started.
- **End status:** Phase 2 decision chain built and verified offline: 27
  tests pass, covering a full two-cycle headless loop, a structured trace,
  identical fault sequences across three same-seed runs, and different
  Tavily output routing to different specialists. Not yet verified live:
  the local `.env` holds placeholder keys and Docker was not running, so
  the Phase 2 done-when boxes stay unticked until a live
  `make up && make headless` run three times.
- **Badges:**
  - 🆕 Addition — `bedlam/models/client.py`: Token Factory wrapper with
    retries, logged Super → Nano fallback and per-call records.
  - 🆕 Addition — `bedlam/seed.py`: every model-site seed and RNG stream
    now derives from the single `BEDLAM_SEED` root.
  - 🆕 Addition — `bedlam/search/`: lockfile-driven dependency manifest,
    Nano query formulation, live Tavily client with a per-run cache.
  - 🆕 Addition — `bedlam/router.py` and `bedlam/specialists/`:
    search-result layer labelling, score-weighted routing, three
    specialists over a discrete fault catalog.
  - 🆕 Addition — `bedlam/diff.py`, `bedlam/select.py`,
    `bedlam/probes/classify.py`, `bedlam/loop.py`, `bedlam/trace.py`,
    prompts in `bedlam/prompts/`, scripted patches in `demo/patches/`.
  - 🆕 Addition — `tests/` with offline fakes; `pytest` added as a dev
    dependency.

## Session [2026-10-16-1426]

- **Start status:** Phase 0 complete, `SESSION_HISTORY.md` added (`92326f5`).
  Phase 1 (target stack and fault injection) not started.
- **End status:** Phase 1 done-when criteria all met: `docker compose up`
  brings Postgres + Redis + Toxiproxy + the FastAPI target to healthy from a
  clean checkout; latency, bandwidth, connection-cut and timeout faults are
  injected and removed via Toxiproxy's control API with zero changes to the
  boilerplate's source; concurrent per-layer probes return a structured
  health snapshot; blast radius is a static lookup computed before injection.
  Manually verified end to end: a Redis latency fault degrades the cache
  probe and the stack recovers once the fault is removed.
- **Badges:**
  - 🆕 Addition — `docker-compose.yml` + Toxiproxy bootstrap config wiring
    the target stack with Toxiproxy fronting Postgres and Redis.
  - 🆕 Addition — `bedlam/topology.py`: single source of truth for layer
    endpoints and static blast-radius computation.
  - 🆕 Addition — `bedlam/faults/`: Toxiproxy control-API client plus the
    four fault primitives (latency, bandwidth, connection cut, timeout).
  - 🆕 Addition — `bedlam/probes/`: concurrent api/db/cache health probes.
  - 🆕 Addition — `bedlam/logging.py`: structured JSON logging helper.
  - 🆕 Addition — `scripts/demo_fault_injection.py`: the manual
    inject-degrade-recover proof.

## Session [2026-10-16-1349]

- **Start status:** Phase 0 complete (`fe72885` — repo foundations, model map,
  live API smoke tests). Working tree clean, one commit on `main`.
- **End status:** `SESSION_HISTORY.md` added to the repo root to track session
  history going forward.
- **Badges:**
  - 🆕 Addition — Created `SESSION_HISTORY.md` as the standing session log.
