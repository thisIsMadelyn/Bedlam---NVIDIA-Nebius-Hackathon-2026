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
- Live patch (scheduled 21 Oct, see "Council review decisions"): the target's
  source is bind-mounted into the api container, which reloads on change.
  After the patch, the same fault is probed again and the screen says whether
  the patch held, before the fault is removed. Scripted patches are applied to
  the submodule for the cycle and reverted at the end of the run
- Tavily routing on screen (scheduled 21 Oct): one beat per cycle with the
  results, Nano's layer labels, the summed scores and the winning specialist;
  layout approved before it is built
- Scripted patches for the demo, applied as real commits so the diff analysis is live
- Three consecutive clean end-to-end runs from a fresh `docker compose up`
- Determinism verified by replay: re-record the final demo run with `make record`,
  then `make test` reproduces its fault sequence
- Replay mode as a no-key fallback — **never the default**, because a judge running
  it must see the live Tavily call
- Onboarding line (judges' meeting, 22 Oct; landed the same day): from
  launch until the first turn, the NOW box's "You:" line says the whole
  loop instead of "just watch": "You: watch. Two rounds of break, fix and
  re-test, then a trade-off you pick." The baseline screen itself lasts
  milliseconds, so the line covers round 1's lead-in instead. Templated,
  76 columns
- No-query abort (judges' meeting, 22 Oct; fixed 22 Oct): when Nano
  returns no valid Tavily query after its retries, one templated query is
  searched instead of stopping the run. A seeded pick from a fixed list of
  (dependency, failure term) pairs in `bedlam/search/query.py`, version
  from the lockfile, never one already searched. No model call; the search
  and routing stay live. The timeline marks it `(templated)`

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
- README restructure (judges' meeting, 22 Oct): the pitch leads with the
  re-break, not the break (see "Judges' meeting advice"); a screenshot of
  the cycle-2 moment at the top (`/shot`); the jester section moves below
  setup; a link to `LIMITATIONS.md` beside the stated limits
- "Why a terminal, and why local" block (raised 22 Oct; landed the same
  day, under the current pitch until the restructure), right under the
  pitch. Draft: "Bedlam is for the developer who has just patched an
  outage, and that developer is already in a terminal next to Docker. The
  app it attacks runs on your machine on purpose: Bedlam sends real faults
  to it, and Nebius's acceptable-use policy forbids attack-like traffic
  against Nebius-hosted systems. Nebius runs Bedlam's brain, never its
  victim." Phase 8 reuses it word for word in the Devpost description
- "Models and Nebius usage" leads with what Nebius does (raised 22 Oct;
  landed the same day),
  not with a pointer to `PLAN.md`. Draft: "Every decision Bedlam makes is a
  live call to NVIDIA Nemotron on Nebius Token Factory: seven call sites,
  from reading probe results to building the final trade-off. Nothing is
  pre-computed, and the AGENT panel shows each call as it happens: model,
  tokens, latency, outcome." Never write "inference only" without first
  saying what that inference does
- Fix the README model table: search synthesis is temperature 0.0 in
  `map.py` and section 2, not the 0.3 the README shows (fixed 22 Oct with
  the section rewrite)
- `LIMITATIONS.md` (created 22 Oct): kept current with every change before
  content freeze, so it matches the shipped build
- Developer manual (raised 21 Oct): for the developer running the app. The
  loop step by step (fault, symptom, your turn, restart, same fault, verdict,
  analysis, trade-off), scripted vs real patch mode, every key and slash
  command, the post-mortem page, and what each panel shows

Done when:
- [ ] A stranger can run the project from the README with no other input
- [ ] The NVIDIA/Nebius usage section is standalone and could be pasted into Devpost

---

### Phase 7 — Video · Wed 28 Oct

**Content freeze.** No code changes after the script is written.

Artifacts:
- Script, under 2:40 to leave margin
- Cold open (judges' meeting, 22 Oct): the first 10–15 seconds show the
  cycle-2 re-break ("your patch held, but it did not cover X"), then the
  video goes back to the start. The aha lands inside 30 seconds
- On screen: the loop, the trade-off, and a commands segment of `/why`,
  `/diff`, `/calls`, `/cost` and `/log` (widened from `/why` only on
  22 Oct). The other commands, the post-mortem page and the jester's moods
  are left to the manual
- Format (decided 22 Oct): screen recording with a voice-over recorded
  afterwards, not live, plus a few burned-in captions for the key beats.
  No repo URL in the video: it is in the description
- Introduction (Draft A, decided 22 Oct), right after the cold open, over a
  plain title card (name + Bedlam, no logos) then the TUI at baseline:
  "I'm [name], and this is Bedlam. It's for backend developers who fix an
  outage and ship the patch hoping it holds. Chaos tools break your system
  once. Bedlam breaks it, runs your fix, and then breaks it again where
  your fix didn't reach. Here's a run from the start." The pitch sentence
  follows whatever Phase 6 settles
- Outline (22 Oct):

  | Time | Segment |
  |---|---|
  | 0:00–0:15 | Cold open: cycle-2 re-break |
  | 0:15–0:35 | Introduction (Draft A) |
  | 0:35–0:55 | Cycle 1: Tavily queries, routing, specialist, fault |
  | 0:55–1:10 | Damage: probes, symptom, AGENT panel model attribution |
  | 1:10–1:25 | Patch handed over, analysed, held |
  | 1:25–1:45 | Cycle 2: re-route, re-break |
  | 1:45–2:05 | Trade-off: A or B, the developer chooses |
  | 2:05–2:35 | Commands: `/why`, `/diff`, `/calls`, `/cost`, `/log` |
  | 2:35–2:40 | End on the decided page, or Q for the moral |

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

- [x] Devpost: track = Coding and Agentic Engineering
- [x] Project description, named target user in the first line, using the
  re-break pitch from the README
- [x] Limitations from `LIMITATIONS.md` summarised in the description, with a link
- [x] Separate field: NVIDIA models / Token Factory / Nebius tools usage
- [x] Demo URL: repo link plus "test build — `docker compose up`, see README"
- [ ] Video URL
- [x] Feedback field completed seriously
- [x] Repo public, LICENSE badge visible in About

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

Also approved 22 Oct, to show the mechanics under the hood:

- `/search [N]` — one cycle's search from request to routing: each query
  with its latency, results kept and cut, or cached; the credits; the
  search depth and the allowed and excluded sites; Nano's layer labels;
  the summed scores as bars; the winning specialist
- `/loop` — the seven steps of a round, one per row with what happens at
  each, the current step marked, the rounds done, and the trade-off after
  round 2. A ring design was turned down for this vertical one

Dropped: `/patched` (that's `/patch`), `/trace` (the AGENT panel shows it),
`/moral`, `/pause`, history recall, `/time`. Constraints: read-only, built from state the TUI already holds,
no command may make the trade-off decision on the developer's behalf
(`/choose a` is fine, `/auto` is not). Every line fits 82 columns.

### Post-mortem page

Approved 21 Oct, before Phase 5. A completed run ends on the trade-off page,
decided: the choice marked, the cost shown live, the decision record, and a
POST-MORTEM log under it where every command replies. It stays until Q.
While the trade-off waits, the same log shows as a 5-row strip when the
options leave room. Commands, all read from the run's own events:

- `/cycles` — one line per cycle, then the trade-off
- `/cycle N` — one cycle step by step: search, routing, pool, pick, fault,
  symptom, patch, analysis
- `/why N`, `/diff N` — the existing commands, for any cycle
- `/calls` — model calls per call site, Tavily, totals
- `/cost` — the chosen option's cost, health before, under and after it
- `/log` — switch between the trade-off page and the run log

### End splash

Approved 21 Oct, before Phase 5. When a completed run is quit, the launch
splash comes back with the jester's moral under the wordmark, fixed text, no
model call:
"it was never stable. you just stopped patching." and, dim, "same time next
sprint." Changed 22 Oct: the run stays on the decided page after the choice,
for commands and `/log`; Q or `/quit` brings up the moral, and any key on it
quits. A failed or unfinished run quits straight away.

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

### Council review decisions

Recorded 21 Oct after an outside review. Each item is scheduled into its
phase before work starts.

- **The patch must run.** Today the developer's edit is read but never
  reaches the running container, so the re-break never tests the fix.
  Make the edit live in the api container, then re-apply the same fault
  to show whether the patch held, before pivoting to the gap. Accepted
  cost: testing the app gets slower (re-record and replay after it lands).
  Landed 21 Oct; what changed, the cycle and the held rule are in
  `docs/live-patch.md`.
- **Tavily routing is shown on screen.** One visible beat per cycle: the
  live results, Nano's layer label on each, the summed scores and the
  winning specialist.
- **Judges run the scripted patches only.** Judges are not expected to run
  the build locally or read the code; the judge-facing run uses
  `demo/patches/` so nobody has to patch an unfamiliar codebase. Real
  patch mode stays for the builder, and may be used for the video.
- **Video length is not a risk.** The loop finishes in seconds; 3:00 is
  ample.

### Judges' meeting advice

Recorded 22 Oct from the judges' meeting (Nebius, Tavily, NVIDIA). Each
item is scheduled into its phase above.

- **Real problem, real audience.** No developers are available to interview
  before freeze, so the change is to the pitch, not the features. The pitch
  leads with what no plain chaos tool does: Bedlam runs your patch, says
  whether it held, and breaks the system again where the patch did not
  reach. Draft, to settle in Phase 6: "Bedlam breaks your app, runs your
  fix, and then breaks it again where your fix didn't reach."
- **Aha fast.** The first break lands within about 15 seconds of a run
  starting; the aha is the cycle-2 re-break. Phase 6 puts it at the top of
  the README and Phase 7 opens the video on it.
- **One thing done well.** Every integration already supports the loop. No
  new features before freeze beyond what is already approved; the video
  shows the loop, the trade-off and `/why` (widened 22 Oct to a short
  commands segment, see Phase 7).
- **Action first, onboarding, which model.** Model attribution is already
  on screen (AGENT panel). Phase 5 adds one onboarding line in the NOW
  box until the first turn (landed 22 Oct).
- **Publish limitations.** Documented failure cases live in
  `LIMITATIONS.md`, separate from the design guarantees in the README.
- No accessibility claim: Bedlam was not built for it, so the submission
  says nothing about it.

### Trade-off page redesign

Raised 21 Oct: the user does not like the trade-off page's graphics and
wants them redesigned. Brought forward the same day, before Phase 5's
freeze: A and B as two cards side by side with their rows aligned, the
same look while the choice waits; "how you got here", one line per round
with the patch verdict, replaces the CPU chart under the trade-off, which
is removed along with `/cpu`. The panel takes only the rows it needs; the
command replies get the rest. The empty reply log shows a dim field (from
a Claude Design session): a thin band rising from A to B in two shades, at
4:1 contrast, until the first command reply takes its place.

**Fixed 22 Oct:** the field showed only after the choice, not while the
trade-off waits, on screens under about 42 rows: the "how you got here"
recap left the replies too few rows for it. While the replies are empty,
the recap now gives way when only that makes room for the field; it is
still in `/cycles`, and taller screens show both.

**Animated 22 Oct:** a lighter ink (ACCENT at the crest) swings along the
band A → B → A, about 3 s each way at 10 frames a second, while the choice
waits; once chosen it travels to that letter and rests. Same glyphs and
shades; driven by a frame counter, display only.

**Fixed 22 Oct:** the cards changed proportions on the first frame and
after `/log`, because a hidden or not-yet-laid-out panel measured 0 columns
and the cards fell back to 76. They are now sized from the frame, so they
keep one width through the run.
