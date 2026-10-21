# Bedlam — Implementation Plan

Adversarial chaos agent for the Nebius x NVIDIA Global AI Hackathon.
Track: Coding and Agentic Engineering. Solo builder.

**Deadline:** 30 Oct 2026, 10:00 PDT (20:00 EET).
**Target submission date:** 29 Oct 2026 — one full day of buffer. Do not plan to submit on the 30th.

---

## How to use this file

Every Claude Code session starts by reading the current phase here. A phase is
done when its **Done when** list is fully satisfied — not when the code "works".
If a phase slips, cut scope inside that phase; do not borrow days from a later one.

---

## 1. Hard constraints

These are disqualifiers or prize conditions. They are not design preferences.

| Constraint | Consequence if missed |
|---|---|
| Runtime call to Nebius Token Factory inference API | Disqualified |
| At least one NVIDIA open model | Disqualified |
| `LICENSE` in repo root, detected by GitHub and shown in About | Disqualified |
| README with setup + run instructions | Disqualified |
| All materials in English | Disqualified |
| Functional runtime call to the Tavily API | Loses the Tavily bonus award |
| Demo video under 3:00, **public** on YouTube, no third-party trademarks | Disqualified |
| Judge access to a working build stays free until **15 Dec 2026** | Effectively disqualified at judging |
| Stage One pass: the required APIs must be *reasonably applied*, not decorative | Cut before scoring |

Two things that follow from the above and are easy to get wrong:

- **The target system never runs on Nebius infrastructure.** Nebius AUP §6.1 and §5.1
  prohibit scanning and attack-like traffic against Nebius-hosted hosts, with no
  exception for your own systems. Bedlam uses Nebius for **inference only**. The
  FastAPI target, Postgres, Redis and Toxiproxy all run locally.
- **The target repo is a dependency, never vendored.** Submission must be the
  builder's own work. Pull `benavlabs/FastAPI-boilerplate` via pip, submodule or
  image — do not copy its source into this repo.

---

## 2. Architecture, as locked

**Loop:** inject fault → probe and classify → developer patches → analyse diff →
search and synthesise → select next fault → (×2 cycles) → trade-off escalation.

**Scope cap:** 2 re-break cycles + 1 trade-off escalation. The escalation is the
differentiating feature and is never cut.

**Concurrency rule:** faults are injected **sequentially, one layer at a time**.
Probes may run concurrently because they are read-only. Two simultaneous faults
destroy the causal link between one fault and one patch, which is the entire
product premise.

**Specialist routing:** Tavily results are classified by layer (api / db / cache)
and that classification selects which specialist prompt handles the cycle. The
router is driven by live search output, not a hardcoded branch. This is what makes
Tavily architectural rather than decorative, and it is the Stage One argument.

**Model map:**

| Call site | Model | temp | Notes |
|---|---|---|---|
| Probe classification | Nano | 0.0 | enum output |
| Tavily query formulation | Nano | 0.0 | structured extraction |
| Layer classification of results | Nano | 0.0 | routes to specialist |
| Diff analysis | Super | 0.1 | reasoning over code |
| Tavily synthesis → candidate faults | Super | 0.0 | messy prose → hypotheses; feeds the eligible pool, so unsampled |
| Fault selection | Super | 0.0 + fixed seed | must reproduce |
| Trade-off escalation | Super | 0.4 | judge-visible |
| Bedlam's voice | no model — templates | — | determinism, zero latency |

Ultra is excluded on latency grounds in a sub-3-minute demo, not on cost. At this
call volume cost is not the binding constraint, and a cost argument is checkable
in ten seconds by a judge.

---

## 3. Phases

### Phase 0 — Foundations · Fri 16 Oct

**Goal:** remove every cheap disqualifier and prove both external APIs are live.

Artifacts:
- Public GitHub repo, MIT `LICENSE` in root
- `.env.example` with `NEBIUS_API_KEY`, `TAVILY_API_KEY`, no real values
- `.gitignore` covering `.env`
- `scripts/smoke_nebius.py` — one real chat completion, prints raw response
- `scripts/smoke_tavily.py` — one real search, prints raw response
- `pyproject.toml`, Python 3.12, dependency manager chosen and committed

Done when:
- [ ] GitHub About panel shows "MIT license"
- [ ] Both smoke scripts return 200 with real content
- [ ] All four model IDs confirmed callable with exact casing, recorded in `model_map`
- [ ] `$25` promo code submitted at `nebius.com/promo-code` using the account email

Risk: model ID casing is inconsistent across the four models. Copy verbatim, never
normalise case.

---

### Phase 1 — Target stack and fault injection · Sat 17 – Sun 18 Oct

**Goal:** prove a fault can be injected into a running three-tier system without
touching application code. This is the highest-risk unknown in the project.

Artifacts:
- `docker-compose.yml`: FastAPI target + Postgres + Redis + Toxiproxy
- Toxiproxy sitting in front of both Postgres and Redis
- `bedlam/faults/` — fault primitives: latency, bandwidth, connection cut, timeout
- `bedlam/probes/` — read-only health probes per layer, running concurrently
- Manual proof: inject Redis latency, observe the API degrade, remove it, observe recovery

Done when:
- [x] `docker compose up` brings the full stack to healthy from a clean checkout
- [x] A fault is injected and removed via Toxiproxy API with zero changes to boilerplate source
- [x] Probes return a structured per-layer health snapshot
- [x] Blast radius is computable before injection, not after

Risk gate — **Mon 20 Oct**: if Toxiproxy is not working against this boilerplate,
abandon it and fall back to in-process ASGI middleware that injects latency and
errors at the data-access boundary. Decide by the 20th; do not keep debugging.

---

### Phase 2 — Intelligence layer, headless · Mon 19 – Wed 21 Oct

**Goal:** the full decision chain runs from a terminal with no UI.

Artifacts:
- `bedlam/models/map.py` — the model map as the single source of truth, with
  per-site temperature, seed, max_tokens and fallback chain
- `bedlam/models/client.py` — Token Factory wrapper: retries, fallback Super → Nano,
  structured call logging (site, model, tokens, latency, outcome)
- `bedlam/search/` — Tavily query builder (targets **dependency versions**, never the
  boilerplate name), `include_domains` set to GitHub plus blogs and changelogs,
  explicitly excluding nvd.nist.gov and osv.dev
- `bedlam/router.py` — layer classification → specialist selection
- `bedlam/specialists/` — three prompt+tool bundles: api, db, cache
- `bedlam/diff.py` — patch analysis
- `bedlam/select.py` — fault selection constrained by blast radius and cycle history

Done when:
- [x] A full two-cycle run completes headless and writes a structured JSON trace
- [x] Given the same recorded inputs (model replies, Tavily results, probe
  snapshots) and seed, three replays produce the live run's fault sequence
  (`make record`, `tests/test_replay.py`). Reworded 20 Oct from "same seed,
  same fault sequence across three live runs": Token Factory is not
  deterministic at temperature 0 with a fixed seed, so live runs can diverge.
- [x] Every model call appears in the trace with its site and model name
- [x] Tavily output demonstrably changes which specialist is selected

Risk: Tavily queries returning noise. Mitigation is in the query builder — search
`asyncpg 0.29 connection pool`, never `FastAPI boilerplate bug`.

---

### Phase 3 — Terminal UI · Thu 22 – Sat 24 Oct

**Goal:** the loop is legible to someone watching for 90 seconds.

Artifacts:
- Textual TUI, fluid with an 82-column minimum (changed 20 Oct from a fixed 82),
  header showing the cycle counter; the blast radius shows on the live fault's
  line in the system panel
- Panels: TIMELINE, SYSTEM, AGENT
- AGENT panel shows **which model answered each step** — this is what turns the model
  map from a claim in the README into something demonstrated on screen
- Concurrent probes render as three lines filling together
- Bedlam's voice: templated, with humour, terminal-only

Done when:
- [x] Nothing wraps or clips at 82 columns
- [x] A viewer can identify the current phase of the loop without narration
- [x] Model attribution is visible per step
- [x] Hardcoded placeholder metrics are fully replaced by real ones

---

### Phase 4 — Trade-off escalation · Sun 25 Oct

**Goal:** the differentiating feature, given its own day because it is what the
judges actually watch.

Artifacts:
- Escalation trigger: fires when further breakage stops adding information
- Full-frame takeover of the TUI
- Presents a genuine choice with costs on both sides — latency vs consistency,
  throughput vs durability — and **the developer chooses**; Bedlam does not decide
- The choice is recorded and visibly changes what happens next

Done when:
- [x] Escalation fires deterministically at the end of cycle 2
- [x] Both branches are reachable and produce different subsequent behaviour
- [x] The framing is a trade-off, not a recommendation with extra steps

---

### Phase 5 — Rehearsal and freeze · Mon 26 Oct

**Feature freeze at end of day.** Anything not working by Monday night does not ship.

Artifacts:
- Scripted patches for the demo, applied as real commits so the diff analysis is live
- Three consecutive clean end-to-end runs from a fresh `docker compose up`
- Determinism verified by replay: re-record the final demo run with `make record`,
  then `make test` reproduces its fault sequence
- Replay mode as a no-key fallback — **never the default**, because a judge running
  it must see the live Tavily call

Done when:
- [ ] Three clean runs in a row, no manual intervention
- [ ] A fresh clone on a different machine reproduces the run from README alone

---

### Phase 6 — Documentation · Tue 27 Oct

Artifacts:
- `README.md`: what it is, named target user in the first line, explicit limits
  (blast radius, termination guarantee) up front, setup, run, `.env.example` instructions
- A dedicated README section documenting NVIDIA model and Token Factory usage —
  this is required in the README *and* as a separate Devpost field
- `model_map` documented with the reasoning for each assignment
- Architecture notes: why sequential faults, why Tavily over structured vulnerability
  databases, why Super over Ultra

Done when:
- [ ] A stranger can run the project from the README with no other input
- [ ] The NVIDIA/Nebius usage section is standalone and could be pasted into Devpost

---

### Phase 7 — Video · Wed 28 Oct

**Content freeze.** No code changes after the script is written.

Artifacts:
- Script, under 2:40 to leave margin
- Screen recording showing the project actually running
- The live Tavily call visible on screen
- Uploaded **public** to YouTube, not unlisted
- No NVIDIA logos or third-party trademarks anywhere in frame

Done when:
- [ ] Runtime under 3:00
- [ ] Opened in a private browser window to confirm public visibility
- [ ] The live search call is unambiguously visible

---

### Phase 8 — Submit · Thu 29 Oct

Do not leave this for the 30th.

- [ ] Devpost: track = Coding and Agentic Engineering
- [ ] Project description, named target user in the first line
- [ ] Separate field: NVIDIA models / Token Factory / Nebius tools usage
- [ ] Demo URL: repo link plus "test build — `docker compose up`, see README"
- [ ] Video URL
- [ ] Feedback field completed seriously
- [ ] Repo public, LICENSE badge visible in About

---

## 4. Gates

| Date | Gate | Action if failed |
|---|---|---|
| 20 Oct | Toxiproxy working | Switch to in-process fault middleware |
| 24 Oct | TUI legible at 82 cols | Cut panels, keep TIMELINE and AGENT |
| 26 Oct | Feature freeze | Ship what works; no exceptions |
| 27 Oct | Content freeze | No code changes after this point |

---

## 5. Post-submission

- Keep API keys funded and the build runnable until **15 Dec 2026**. Judging runs
  1–15 Dec, not up to the submission deadline.
- Judging result announced ~11 Jan 2027. If it wins, there are **10 business days**
  to return a W-8BEN. Set a reminder.

---

## 6. Out of scope

Settled; reopen only with new information.

- Changing the idea or the track
- Targeting the Overall Award — it would forfeit the Tavily bonus
- Using VMS as the target system
- City Winner awards
- Concurrent fault injection
- A third model in the map

---

## 7. Backlog

Ideas captured, not scheduled. Each one needs a phase and a yes before work starts.

### Real patch mode

Approved and landed 20 Oct: the TUI's default (`GitPatchSource`), with
`--scripted` as the fallback; headless runs and `make record` stay
scripted. Pressing P before this
sends a prepared diff from `demo/patches/`; the analysis of it is live, but
the developer did not write it, and the product promise is "it reads your
patch".

- While a fault is live, the developer edits `targets/fastapi-boilerplate`
  (already a git submodule) in their own editor.
- P reads the real `git diff` of that working tree. An empty diff is
  reported on screen, not passed on.
- The prepared diffs stay as an explicit fallback flag, so the video and a
  judge's run still reproduce.
- Limit, stated on screen and in the README: the edit is not hot-loaded into
  the running container. Recovery comes from removing the fault. Rebuilding
  the API container per round costs about a minute; decide separately.
- Other target repos stay out of scope until after submission: each needs
  its own compose stack, topology and Toxiproxy wiring.

### Slash commands in the TUI

Raised 20 Oct. The command line landed with `/help`, `/patch`, `/choose` and
`/quit`. Approved 21 Oct, before Phase 5:

- `/status` — cycle (1, 2 or trade-off), live fault, blast radius, what Bedlam waits on
- `/why` — the routing weights and basis, plus the top Tavily results behind them
- `/diff` — what the diff analysis read in the last patch: defends and gaps
- `/seed` — the root seed, the `make run SEED=…` rerun, and that only replays
  reproduce exactly (Token Factory varies at temperature 0)

Also approved 21 Oct, for managing the output and layout:

- Tab completes commands and their fixed arguments
- `/grep <text>` — timeline shows only matching lines; command rows always show
- `/zoom timeline|agent` — one log fills the screen; `/zoom` alone ends it
- `/copy` — the last command's output, or `/copy timeline` for what is shown
- `/save` — timeline and model log as text beside the trace
- `/shot` — SVG screenshot beside the trace
- `/sudo …` — hidden easter egg; runs nothing
- Textual's Ctrl+P palette is off: `/` is the only command line

Dropped: `/patched` (that's `/patch`), `/trace` (the AGENT panel shows it),
`/moral`, `/pause`, history recall, `/time`. Constraints: read-only, built from state the TUI already holds,
no command may make the trade-off decision on the developer's behalf
(`/choose a` is fine, `/auto` is not). Every line fits 82 columns.

### End splash

Approved 21 Oct, before Phase 5. When a run completes, the launch splash comes
back with the jester's moral under the wordmark, fixed text, no model call:
"it was never stable. you just stopped looking." and, dim, "same time next
sprint." Any key returns to the frame; Q quits from there.

### Agent and resource usage on screen

Raised 20 Oct by the judges, who asked to see agent and resource usage. Rendered
with ASCII (bars, sparklines) so it stays inside 82 columns. Candidates:

- Per-model calls, tokens and latency, read from the existing model call log
- Fallbacks (Super → Nano) shown explicitly
- Tavily calls made this run and credits used
- Target stack load per container (CPU, memory) during each fault

Overlaps with the Phase 3 AGENT panel, so it may fit there. Container stats
landed 20 Oct (`f874fae`): CPU with a sparkline and memory per layer, read from
the `docker` CLI, so no new dependency. Display only.
