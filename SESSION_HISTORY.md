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
