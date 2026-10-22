# Devpost description (draft)

Draft for the Phase 8 submission. The separate NVIDIA / Token Factory field
is not here: it comes from the README's "Models and Nebius usage" section
(Phase 6).

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
