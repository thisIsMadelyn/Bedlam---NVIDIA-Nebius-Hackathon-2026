# CLAUDE.md

Operating instructions for Claude Code in this repository.

---

## What this is

**Bedlam** — an adversarial chaos agent. It breaks a running three-tier FastAPI
system, waits for the developer to patch it, analyses what the patch changed, and
breaks it again from a different direction. After two cycles it stops breaking
things and escalates to a performance trade-off that the developer must choose.

Built solo for the Nebius x NVIDIA Global AI Hackathon. Hard deadline 30 Oct 2026.
Read `PLAN.md` for the current phase before starting work.

---

## Session protocol

1. Read `PLAN.md`, find the current phase, work only inside it.
2. State what you are about to change before changing it.
3. One concern per change. When the user reports one issue, fix that issue only.
4. Propose any broader refactor before doing it — do not bundle it in.
5. Run the relevant check before claiming something works.

---

## Non-negotiable constraints

Violating any of these loses the competition entry. They are not preferences.

- **The target system never runs on Nebius infrastructure.** Nebius is used for
  inference only. FastAPI, Postgres, Redis and Toxiproxy run locally via Docker.
  Never suggest deploying the target to Nebius AI Cloud — their AUP prohibits
  attack-like traffic against Nebius-hosted systems, including your own.
- **Never vendor the target repo.** `benavlabs/FastAPI-boilerplate` is a dependency
  (pip, submodule or image). Copying its source into this repo breaks the rule that
  the submission must be the builder's own work.
- **Never remove or relocate `LICENSE`.** It must stay in the repo root, MIT, where
  GitHub detects it.
- **Every string in this repo is English.** Code, comments, docstrings, commit
  messages, README, CLI output, TUI labels. No exceptions — the rules require it.
- **Never commit `.env` or any real key.** `.env.example` holds placeholder values
  only. Never print an API key, not even truncated, not even in a debug path.

---

## Architecture invariants

- **Faults are sequential.** One fault, one layer, one cycle. Never inject into two
  layers at once. The product depends on a clean causal link between one fault and
  one patch; concurrent faults destroy the attribution.
- **Probes may run concurrently.** They are read-only. `asyncio.gather` across the
  three layers is correct and intended.
- **Specialist routing is driven by live Tavily output**, not a hardcoded branch.
  Search results are classified by layer, and that classification picks the
  specialist. If you find yourself writing `if layer == "db"` against a static list,
  you have broken the design.
- **Scope cap: 2 re-break cycles + 1 trade-off escalation.** Do not add a third
  cycle, a fourth specialist, or a second escalation.
- **The trade-off escalation presents a choice.** Bedlam never picks for the
  developer. If a code path makes the decision automatically, it is a bug.

---

## Model map contract

`bedlam/models/map.py` is the single source of truth. **Never write a model ID
anywhere else in the codebase.** Never hardcode a temperature or seed at a call site.

Model IDs have inconsistent casing between models. Copy them verbatim. Do not
normalise, lowercase, or "fix" them:

```
nvidia/nemotron-3-super-120b-a12b
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
nvidia/Nemotron-3_5-Lightning
nvidia/Nemotron-3-Ultra-550b-a55b
```

Only the first two are in use. Lightning and Ultra are deliberately unused —
adding a third model is scope creep, not an improvement.

Each entry in the map carries: model, temperature, seed, max_tokens, fallback.
Fallback chain is Super → Nano. A fallback must be logged, never silent.

Every model call is logged with its call site, model name, token counts, latency
and outcome. The TUI reads this log — model attribution on screen is a deliverable,
not debug output.

---

## Determinism

The demo must reproduce. A judge running this build should see what the video shows.

- Fault selection runs at `temperature=0.0` with a fixed seed.
- Any new randomness must be seeded from a single configurable root seed.
- Never use unseeded `random`, `uuid4` in a decision path, or wall-clock time as an
  input to a decision.
- Before declaring a change done in the decision chain, run `make test`: the replay
  test feeds a recorded live run back three times and must reproduce its fault
  sequence. If the change made the recording stale (prompt, model map or patch
  edits), re-record with `make record` first. Three live runs are not the check:
  Token Factory is not deterministic at temperature 0 with a fixed seed.

---

## Tavily usage

- Queries target **dependency names and versions** — `asyncpg 0.29 connection pool
  exhaustion`, not `FastAPI boilerplate bug`. Searching the boilerplate name returns
  noise.
- `include_domains` covers GitHub issues and PRs, plus blogs and changelogs.
  Explicitly exclude `nvd.nist.gov` and `osv.dev` — structured vulnerability
  databases hold CVEs but not the failure narratives this agent needs.
- The Tavily call happens at **runtime**, during the run. Never pre-fetch results at
  build time and cache them as fixtures for the demo path. The prize condition is a
  functional runtime call, and a judge must be able to see it happen.
- Free tier is 1,000 credits/month. Cache within a single run; do not cache across runs.

---

## Commands

Establish these as the only entry points. Keep them working.

```
make up          # docker compose up, full target stack
make down        # tear down, remove volumes
make run         # launch the Bedlam TUI against the running stack
make headless    # full loop, no UI, writes a JSON trace
make smoke       # one live call to Token Factory and one to Tavily
make test        # test suite
make lint        # ruff + format check
```

If a command does not exist yet, add it to the Makefile rather than documenting a
raw invocation.

---

## Code conventions

- Python 3.12, type hints on every public function.
- `ruff` for lint and format. No competing formatter.
- Async throughout the probe and model layers.
- Structured logging (JSON), never bare `print` outside the TUI.
- Prompts live in `bedlam/prompts/` as files, not as string literals inside logic.
- The TUI is **fluid with an 82-column minimum**: it fills the terminal and must stay
  fully readable at exactly 82. Verify at 82 and at a wide size before committing any
  layout change.

---

## Do not

- Add a dependency without asking first.
- Create, rewrite or delete a file the user did not ask about.
- Refactor outside the current phase.
- Add a third model, a fourth specialist, or a third cycle.
- Replace the templated voice layer with a model call. It is templated on purpose:
  determinism, zero latency, zero cost.
- Let anything wrap or clip at 82 columns (the TUI may grow wider, never need more).
- Write a commit message in any language other than English.
