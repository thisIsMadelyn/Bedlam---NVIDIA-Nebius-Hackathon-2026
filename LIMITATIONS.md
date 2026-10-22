# Limitations

What Bedlam does not do, where it is known to fail, and what it does when a
step goes wrong. The design guarantees (bounded blast radius, one fault at a
time, a fixed stop after two cycles and one trade-off) are in the README;
this file is about the edges.

## Determinism

- **Live runs do not reproduce exactly.** Nebius Token Factory is not
  deterministic at temperature 0 with a fixed seed: two live runs with the
  same root seed can pick different faults. What reproduces is a replay.
  `make record` saves one live run's model replies, Tavily results and probe
  snapshots, and `make test` feeds them back three times and must get the
  same fault sequence each time.
- **The Tavily results change over time.** The search is live by design, so
  a run next month can read different issues than the run in the video and
  route to a different specialist.

## Model output

- **Nano mislabels search results.** Layer classification is checked: a
  label must name a component that its result actually mentions. An invalid
  reply is retried once with the rejection reason; labels that still fail
  are dropped and logged as unverified. Recorded runs show this happening.
- **Routing falls back when the labels run out.** If no verified label is
  left, the specialist is chosen from the probe symptom, and if there is no
  symptom, by a draw from the seeded RNG. Every decision records which basis
  it used (`search`, `symptom` or `seeded`), and the screen shows it.
- **A failed synthesis does not stop the round.** Fault selection falls back
  to the specialist's own fault options, under the same rules.
- **No valid query falls back to a templated one.** Nano writes the Tavily
  queries. If it returns at least one valid query, the round goes on with
  fewer searches. If every attempt returns none, Bedlam searches one
  templated query instead: a seeded pick from a fixed list of dependency and
  failure-term pairs, never one already searched. The search and the routing
  on its results stay live, and the timeline marks the query `(templated)`.
  Nano has no fallback model.
- **The diff analysis is a model's reading.** Super reports what a patch
  defends and what it leaves open. That reading picks the next direction of
  attack; it is not a proof.

## Fault coverage

- **Network faults only.** Faults go in through Toxiproxy between the api and
  Postgres or Redis: latency, bandwidth limits, cut connections, timeouts.
  Bedlam does not inject CPU, memory or disk pressure, does not kill
  containers, and does not change application code.
- **Three layers, two fault points.** Bedlam probes the api, the database and
  the cache, but faults go only on the api's links to the database and the
  cache. The api itself is never faulted directly, and anything else the app
  talks to is out of reach.
- **Two cycles may not reach the deepest weakness.** The stop after two
  re-breaks is fixed. A third cycle could find more, but it would make the
  run open-ended, which the design rules out.

## Patch verdict

- **"Held" is measured on one request.** After the patch, the same fault goes
  back in and one read through the app (session from Redis, tiers from
  Postgres) is compared with the read before the patch. It held if it went
  from hanging or erroring to answering, or got at least twice as fast. A
  patch can pass this and still fail on an endpoint the read does not touch.
  Both timings are on screen, so the verdict can be checked.
- **The api restarts between the fault and the re-test.** A reload under a
  database fault leaves the boilerplate down, because it connects to
  Postgres at startup, so the patched code starts clean and is warmed by one
  read. Real traffic would warm it differently.

## Patches

- **The demo patches are prepared.** In scripted mode (the judge-facing run
  and `make record`), pressing P applies one of the diffs in `demo/patches/`
  that targets the live fault. They are real diffs, applied to the real
  files and running in the container, but the developer did not write them.
- **Real patch mode needs a developer who can patch the target.** It reads
  your own `git diff` of `targets/fastapi-boilerplate`. That means editing an
  unfamiliar codebase while a fault is live, which is why judges are not
  asked to do it.

## Scope

- **One target.** Bedlam runs against `benavlabs/FastAPI-boilerplate` only.
  Another repo needs its own compose stack, topology and Toxiproxy wiring.
- **Local only.** The target stack runs in Docker on your machine. Bedlam
  never attacks a remote host, and Nebius is used for inference only.
- **Tested on one machine.** It has been built and run on Windows 11. A clean
  run on a second machine from the README alone is still open (Phase 5 in
  `PLAN.md`).
- **Tavily free tier.** 1,000 credits a month. Results are cached within a
  run, never across runs, so every run spends a few credits.
