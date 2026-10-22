# Devpost description (draft)

Draft for the Phase 8 submission: the project description, then the
separate NVIDIA / Token Factory field at the end.

---

## Inspiration

Backend developers who fix an outage often ship the patch hoping it holds.
Chaos tools break your system once and stop there. Nobody checks whether the
fix actually held, or what it left exposed. I wanted a tool that does that
second part.

## What it does

Bedlam breaks your app, runs your fix, and then breaks it again where your fix
didn't reach.

It targets a running three-tier FastAPI app (api, Postgres, Redis):

1. **Break.** Bedlam injects one network fault between the api and the
   database or the cache (latency, a bandwidth cap, a cut connection, a
   timeout) and shows the symptom your app develops.
2. **Your turn.** You patch the code. Bedlam restarts the api with your patch
   running, puts the same fault back, and tells you whether the patch held.
   Both timings are on screen, so you can check the verdict yourself.
3. **Read the patch.** Bedlam analyses your diff: what it defends, and what it
   leaves open.
4. **Break it again.** Bedlam searches the web live for how the affected
   dependencies fail in real projects. It routes the round to a specialist
   (api, db or cache) based on what the search found, then picks a new fault
   aimed at what your patch didn't cover.
5. **Trade-off.** After two re-break cycles, Bedlam stops breaking things and
   presents a performance trade-off with two options. It never chooses for
   you.

The run always ends: one fault at a time, two cycles, one trade-off, then it
stops.

## Why a terminal, and why local

Bedlam is for the developer who has just patched an outage, and that developer
is already in a terminal next to Docker. The app it attacks runs on your
machine on purpose: Bedlam sends real faults to it, and Nebius's acceptable-use
policy forbids attack-like traffic against Nebius-hosted systems. Nebius runs
Bedlam's brain, never its victim.

## How I built it

- **NVIDIA Nemotron on Nebius Token Factory makes every decision.** Seven call
  sites, all live calls:
  - Nemotron Super handles the steps that need deeper reasoning: diff
    analysis, search synthesis, fault selection and the trade-off.
  - Nemotron Nano handles the fast classification steps: probe results,
    writing search queries, and labelling search results by layer.
  - If Super fails, the call falls back to Nano, and the fallback is logged,
    never silent. The AGENT panel shows every call as it happens: model,
    tokens, latency and outcome.
- **Tavily runs live during every run.** Queries target dependency names and
  versions (for example, connection-pool behaviour in a specific driver), not
  the app's name. Results come from GitHub issues, blogs and changelogs,
  because those hold failure stories that vulnerability databases don't. Nano
  labels each result by layer, the labels are scored, and the winning layer
  picks the specialist. The routing is shown on screen.
- **Faults go in through Toxiproxy**, without changing a line of the target
  app's code. The target is the open-source FastAPI-boilerplate, used as a
  dependency.
- **The demo reproduces.** Fault selection runs at temperature 0 with a fixed
  seed, and the test suite replays a recorded live run three times and must
  get the same fault sequence each time.
- Python 3.12, asyncio, a Textual terminal UI, Docker Compose.

## Challenges

- **Token Factory isn't deterministic, even at temperature 0 with a fixed
  seed.** Two live runs can pick different faults. So "the demo reproduces"
  had to mean replaying recorded model replies and search results, not
  repeating live runs.
- **Small models mislabel search results.** Every label is checked against
  the text of the result it describes. An invalid label is retried once, then
  dropped and logged.
- **Judging whether a patch "held" honestly.** Bedlam measures it the same way
  before and after the patch, and shows both numbers on screen.

## What I'm proud of

The cycle-2 moment: "your patch held, but it didn't cover X." That's the point
where Bedlam stops being a chaos tool and starts reviewing your fix.

## Limitations

- Network faults only: no CPU, memory or disk pressure, no killed containers.
- "Held" is measured on one representative request, so a patch can pass and
  still fail on an endpoint that request doesn't touch.
- The diff analysis is a model's reading of your patch, not a proof.
- Live search results change over time, so a run next month can route
  differently from the one in the video.

Full list: [LIMITATIONS.md link]

## What's next

Support other target apps, and add fault types beyond the network.

---

# NVIDIA models and Nebius Token Factory (separate field)

Also the source for the README's "Models and Nebius usage" section (Phase 6).

## NVIDIA models and Nebius Token Factory

Every decision Bedlam makes is a live call to NVIDIA Nemotron on Nebius Token
Factory. Nothing is pre-computed. Bedlam calls Token Factory through its
OpenAI-compatible endpoint at runtime, with seven call sites in each run's
loop. Without Token Factory, Bedlam can't pick a fault, read a search result
or judge a patch.

**Models**

- `nvidia/nemotron-3-super-120b-a12b` (Super): the steps that need reasoning.
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (Nano): fast classification and
  extraction.

**Where each one runs**

| Step | Model | Temp | Why this model |
|---|---|---|---|
| Classify the app's health from probes | Nano | 0.0 | Picks a label from a fixed list; no judgement needed |
| Write the Tavily search queries | Nano | 0.0 | Structured extraction: dependency, version, failure term |
| Label search results by layer | Nano | 0.0 | Classification that routes the round to a specialist |
| Analyse the developer's patch | Super | 0.1 | Reasoning over code: what the patch defends and what it leaves open |
| Turn search results into candidate faults | Super | 0.0 | Messy GitHub-issue prose into concrete hypotheses |
| Select the next fault | Super | 0.0 | Must reproduce, so it isn't sampled |
| Build the final trade-off | Super | 0.4 | The part the developer reads closely |

**How it's used**

- **One file defines the models.** `bedlam/models/map.py` sets every call
  site's model, temperature, token limit and fallback, and nothing else in the
  code names a model.
- **Seeded.** Every call's seed comes from one root seed, so one setting
  reproduces a whole run.
- **Reasoning mode off.** Nemotron 3's thinking mode is switched off at every
  call site: each call asks for a small JSON object, and the full loop has to
  fit in a short demo.
- **Fallback is visible.** If Super fails, the call retries on Nano. The
  fallback is logged as a warning and flagged on screen, never silent.
- **Every call is on screen.** The AGENT panel shows each call as it happens:
  step, model, tokens, latency and outcome. `/calls` lists every model call
  per call site.

**What I chose not to use**

- **Nemotron Ultra:** too slow for a loop that has to finish inside a
  sub-3-minute demo.
- **Nemotron Lightning:** no step needs a 1M-token context.

Two models, each placed deliberately, beat four used for show.

**Why the target doesn't run on Nebius**

The app Bedlam attacks runs locally in Docker. Bedlam sends real faults to
it, and Nebius's acceptable-use policy forbids attack-like traffic against
Nebius-hosted systems. Nebius runs Bedlam's brain, never its victim.
