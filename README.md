# Bedlam

An adversarial chaos agent for developers inheriting a codebase they did not
write and do not yet know the fragile parts of.

Bedlam breaks a running three-tier FastAPI system, waits for you to patch it,
reads what your patch actually changed, and breaks it again from a direction
your patch did not cover. After two cycles it stops breaking things and
escalates to a performance trade-off that you choose -- it does not choose
for you.

## Limits, stated up front

- **Blast radius is bounded and computed before injection**, never discovered
  after. One fault, one layer, one cycle.
- **Termination is guaranteed**: two re-break cycles, then one trade-off
  escalation, then it stops. There is no open-ended loop.
- **Faults are injected sequentially.** Bedlam never breaks two layers at once,
  because the whole point is a clean causal link between one fault and one patch.
- **The target runs entirely on your machine.** Nebius is used for model
  inference only.

## The jester

<p align="center">
  <img src="docs/jester-splash.svg" alt="Bedlam's jester above the BEDLAM wordmark" width="360">
</p>

Bedlam has a face. The big jester holds the screen for 2.5 seconds at launch
(any key skips it). During the run a small one sits beside the NOW box and
changes mood with each step of the loop:

| Mood | Face | When |
|---|---|---|
| idle | `(◕‿◕)` | baseline, after the choice, finished |
| scheming | `(¬‿¬)` | a round starts, searching, routing, just before the trade-off |
| striking | `(ò▿ó)` | a fault is picked and injected |
| gloating | `(^▽^)` | your app shows a symptom, or the chosen cost bites |
| sulking | `(-_-)` | the fault did no visible damage |
| your turn | `(•‿•)` | waiting for your patch: the bells light green |
| reading | `(◉_◉)` | reading your patch |
| two-faced | `(◐‿◑)` | the trade-off: half option A, half option B |

Like Bedlam's voice, the jester is display only: no randomness, no model
call, and nothing it shows feeds a decision. The small jester appears from 93
columns up, so the screen stays fully readable at the 82-column minimum.

## Status

Phase 0 — foundations. See `PLAN.md` for the build schedule and the current phase.

## Setup

Requires Python 3.12+ and Docker.

```bash
cp .env.example .env     # then fill in NEBIUS_API_KEY and TAVILY_API_KEY
pip install -e ".[dev]"
make smoke               # verifies both live APIs
```

## Models and Nebius usage

Documented in full in `PLAN.md` section 2 and in `bedlam/models/map.py`, which
is the single source of truth. Summary:

| Call site | Model | temp |
|---|---|---|
| Probe classification | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 0.0 |
| Tavily query formulation | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 0.0 |
| Layer classification | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 0.0 |
| Diff analysis | `nvidia/nemotron-3-super-120b-a12b` | 0.1 |
| Search synthesis | `nvidia/nemotron-3-super-120b-a12b` | 0.3 |
| Fault selection | `nvidia/nemotron-3-super-120b-a12b` | 0.0 + seed |
| Trade-off escalation | `nvidia/nemotron-3-super-120b-a12b` | 0.4 |

All inference runs through the Nebius Token Factory OpenAI-compatible endpoint.
Bedlam's own voice is templated, not generated -- deliberately, for determinism.

## License

MIT. See `LICENSE`.
