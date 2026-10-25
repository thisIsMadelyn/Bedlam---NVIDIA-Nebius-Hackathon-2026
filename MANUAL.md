# Bedlam manual

For the developer running Bedlam. The README covers setup; this covers what
happens once it is running, what you can press and type, and what each part
of the screen shows.

## Starting a run

```bash
make up                  # the target app, Postgres, Redis and Toxiproxy
make run SCRIPTED=1      # Bedlam with the prepared patches
make run                 # Bedlam with your own patches
make run SEED=1729       # pick the root seed (default: BEDLAM_SEED in .env)
```

Bedlam opens with the jester for 2.5 seconds (any key skips it), then the
run starts on its own. The terminal needs at least 82 columns. A wider
terminal puts the timeline and the model log side by side.

## The loop

A run is a baseline, two rounds, and a trade-off.

**Baseline.** Bedlam probes the api, the database and the cache once, so
every later reading has something to compare against.

**Each round has seven steps.** The header names the current one, and
`/loop` lists them with the current step marked.

| Step | What happens |
|---|---|
| RESEARCHING | Nano writes search queries about your dependencies and their versions, and Tavily runs them live. Nano labels each result by layer (api, db or cache), and the scores pick a specialist. |
| CHOOSING | The specialist (Super) turns the results into candidate faults, each backed by a cited result. Super picks one from the eligible candidates and says why. |
| BREAKING | One network fault goes in through Toxiproxy, on the api's link to Postgres or to Redis: latency, a bandwidth limit, a cut connection or a timeout. Never two at once. |
| MEASURING | Probes read all three layers under the fault, and Nano names the symptom. |
| YOUR TURN | Bedlam waits for your patch. Press P when it is in. |
| TESTING YOUR FIX | The fault comes out, the api restarts with your patch and is warmed by one request, then the same fault goes back in. One request through the app is timed before and after the patch. |
| READING YOUR FIX | Super reads your diff: what it defends and what it leaves open. The next round attacks what it leaves open. |

**The verdict.** The patch held if that request went from hanging or
erroring to answering, or got at least twice as fast. Both timings are on
screen, so you can check it. It is measured on one request, so a patch can
pass and still fail elsewhere (see `LIMITATIONS.md`).

**The trade-off.** After round 2 Bedlam stops breaking things. It builds a
trade-off from this run's faults and patches: two options, each with what
you gain and what it costs. Bedlam does not recommend either. Press A or B.
Bedlam then applies the cost you accepted once, live, as a real fault, so
you see what you chose. Then it removes it, and the run is over.

## Patches: scripted or your own

**Scripted (`make run SCRIPTED=1`).** At your turn, P applies the prepared
fix for the live fault, one of the diffs in `demo/patches/`. They are real
diffs against the target's source, applied to the files on disk, and the
api runs them. They are reverted when you quit, and a run that was killed
is cleaned up at the next start.

**Your own (`make run`).** At your turn, edit the target in
`targets/fastapi-boilerplate` in your own editor, save, and press P. Bedlam
reads your `git diff` of that folder, and the api runs your edited code. If
you press P before saving any change, Bedlam says so and waits.

## Keys

| Key | What it does |
|---|---|
| P | Hand over your fix (at your turn) |
| A, B | Choose a side of the trade-off |
| / | Open the command line |
| Esc | Leave the command line |
| Q | Quit. A finished run shows its moral first, then any key quits |

In the command line, Tab completes command names and their arguments.

## Commands

Type `/` then the command. A command that takes a round number reads the
latest round without one.

| Command | What it shows |
|---|---|
| `/help` | The commands |
| `/status` | Where the run is and what Bedlam is waiting for |
| `/cycles` | The run in one line per round, then the trade-off |
| `/cycle 1` | One round step by step |
| `/why 1` | Why that layer: the routing scores and the results behind them |
| `/search 1` | How the search ran: queries, latency, results kept or cut, credits, labels, scores, the winning specialist |
| `/loop` | The seven steps of a round, and where the run is now |
| `/diff 1` | What Bedlam read in your patch: what it defends and its gaps |
| `/calls` | Model calls per call site: model, tokens, latency |
| `/cost` | What your choice cost, measured live |
| `/seed` | The root seed, and how to run this again |
| `/grep text` | Only the lines that contain the text. `/grep` alone shows all |
| `/zoom timeline` | One log fills the screen (`timeline` or `agent`). `/zoom` ends it |
| `/log` | Switch between the trade-off page and the run log |
| `/copy` | Copy the last command's output. `/copy timeline` copies what is shown |
| `/save` | Write the timeline and the model log to a text file |
| `/shot` | Save a screenshot of the screen as SVG |
| `/patch` | Same as P |
| `/choose a` | Same as A (or `b`) |
| `/quit` | Same as Q |

No command can choose the trade-off for you.

## The screen

Top to bottom:

- **Header.** The round, the current step and the seed.
- **NOW.** What is happening in plain words, where to look, and whether you
  need to act. It turns green when it is your turn.
- **Jester.** Bedlam's face. Its mood follows the loop (the README lists
  the moods). It is display only.
- **BEDLAM SAYS.** Bedlam's latest line, held until the next one. The voice
  is templated, not generated.
- **YOUR APP.** The health of each layer: status, latency and the live
  fault with its blast radius.
- **WHAT BEDLAM DID.** Every step in order, newest at the bottom: searches,
  routing, the picked fault and why, the damage, the patch verdict.
- **AI MODELS.** Every Nemotron call (call site, model, tokens, latency,
  outcome) and every Tavily call. A fallback from Super to Nano shows here.
- **Footer.** The keys.

While Bedlam waits for your choice, the **TRADE-OFF** panel takes the place
of the middle panels: the axis, why the run led here, and the two option
cards. `/log` switches back to the run log and returns.

## After the choice

The trade-off page shows your choice, the cost being applied and what it
did, then a **POST-MORTEM** below it: each round's fault, the before and
after timings, and whether your patch held. Type `/cycles` there to start
reading the run, or any other command.

Press Q to see the moral, then any key to quit.

## Files a run leaves

All in `traces/`, named after the seed, for example `tui-seed1729`:

- `.json`: the full trace (every step, model call and search)
- `.log`: the JSON log
- `.decision.md`: your trade-off decision, once you have chosen
- `.txt`: the timeline, the model log and the post-mortem, from `/save`
- `-shot1.svg`, `-shot2.svg`, ...: screenshots, from `/shot`

## Without the screen

`make headless` runs the same loop with no UI and writes a JSON trace. It
uses the prepared patches. It stops at the trade-off without choosing,
because Bedlam never fills in a choice it was not given.
