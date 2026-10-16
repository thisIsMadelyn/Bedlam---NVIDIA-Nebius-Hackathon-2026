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
