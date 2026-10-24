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

## Session [2026-10-24-2206]

- **Start status:** `9a5a1b0`, working tree clean, 206 tests. Phase 5 in
  progress, Devpost form text drafted except the Phase 8 items. Open list:
  the nine-item `bedlam/tui.py` clean-up, weak "why" evidence, clean run 3
  and a fresh clone on another machine. The README setup stopped at
  `make smoke`.
- **End status:** `84ef844` plus this entry (updated after the first log
  at `c5f1078`). 209 tests, lint clean. The replay recording was
  re-recorded twice, for the trade-off and the "why" prompt changes.
  Phase 5's three clean runs and Phase 6's Nebius section box are ticked.
  The fresh clone on another machine is still open, and it also decides
  Phase 6's "a stranger can run it" box. Phase 8 is ticked except the video
  URL. `tui.py` items 1-7 are done, 8 and 9 are left. A first video script
  is drafted and kept local, out of the repo.
- **Badges:**
  - 🆕 Addition — README setup runs from `git clone --recurse-submodules`
    through `make up` to `make run SCRIPTED=1`, and says what P does in
    scripted and real patch mode. `make run` takes `SCRIPTED=1`
    (`7752020`).
  - 🐛 Bug fix — the trade-off's first reply broke a screen length limit in
    every one of three clean runs, and one run fell back to the templated
    trade-off. The prompt puts each limit next to its field and a rejection
    says how many characters to cut. Three fresh runs after: first reply
    accepted 3 of 3 (`23ef4b5`).
  - 🐛 Bug fix — round 1 backed db and cache faults with httpx issues, and
    the "why" line said "No prior faults exist" or named prompt fields like
    `last_patch`. A db or cache candidate must now cite a result about its
    own layer (checked in the synthesis parser, one retry with the reason),
    and the "why" names the dependency and failure in at most 240
    characters instead of being cut at 400. Round 1 now opens on
    `db.timeout.0`, backed by asyncpg pool issues (`ff20106`).
  - `tui.py` clean-up, no change on screen: `fit` replaces its copy
    `_clip`, and `_snapshot`, `_hold_fault`, `_rule`, `_say_wrapped`,
    `_defended` and `_reply` replace repeated code (`9479f2e` to
    `ed27dbf`, `b07e545`).
  - README screenshot replaced (`e4cf6db`) and README status updated
    (`bdccfc5`). PLAN ticks: Phase 8 items (`466e234`), Phase 5 clean runs
    (`b130f40`), Phase 6 Nebius section (`84ef844`).
  - 🆕 Addition — `docs/manual.md`, the developer manual: the loop step by
    step, scripted and real patch mode, every key and command, each part of
    the screen, the post-mortem and the files a run leaves. Linked from the
    README setup (`6f01386`).
  - The README's first line names the target user as on Devpost and in the
    video: backend developers who fix an outage and ship the patch hoping
    it holds (`3683aa8`).
  - 🐛 Bug fix — the README's Nemotron and Nebius section named an "AGENT"
    panel (it is AI MODELS) and said one seed reproduces a live run, which
    Token Factory does not guarantee. It now says the replay test is what
    reproduces a run, and ends with why the target never runs on Nebius,
    so it reads on its own (`b8a019b`).

## Session [2026-10-22-2250]

- **Start status:** `17d76e7`, working tree clean, 201 tests. Phase 5 in
  progress; open list from the previous session: log-scaled latency bars,
  the empty `ReadTimeout: ` message, weak "why" evidence.
- **End status:** `004a792` plus this entry. 206 tests, lint clean. The
  replay recording was not re-recorded: no prompt or model-map change.
  Next session starts with a nine-item list for shortening `bedlam/tui.py`
  (kept in the local checkpoint). Still open in Phase 5: clean run 3 and a
  fresh clone on another machine.
- **Badges:**
  - 🐛 Bug fix — the patch-held check recorded a bare "ReadTimeout: " when
    httpx timed out with no message; the app probe now formats its error
    like the layer probes, "no answer in 6000 ms" (`ec56e88`).
  - 🐛 Bug fix — latency bars use a square-root scale: on the log scale
    318 ms and 2 s drew nearly alike (15 vs 20 cells, now 8 vs 20)
    (`72d04cc`).
  - 🆕 Addition — `/search [N]`: one cycle's search from request to
    routing: queries with latency and results kept, cut or cached, credits,
    depth and site filters, Nano's layer labels, the summed scores as bars,
    and the winning specialist (`97ff614` plan, `1c3cc24`).
  - 🆕 Addition — `/loop`: the round's seven steps, one per row with what
    happens at each, the current step marked, and the trade-off after
    round 2. A ring layout was turned down for this one (`004a792`).
  - Removed four unused Toxiproxy client methods (`0d97d68`).

## Session [2026-10-22-2210]

- **Start status:** `b250165`, Phase 5 in progress. Run in parallel with
  session 2026-10-22-1520 at first. The Devpost fields were not drafted,
  and the README had no screenshot and no "why a terminal" section.
- **End status:** `0d723ab` plus this entry. 201 tests, lint clean. The
  replay recording was not re-recorded: no prompt or model-map change.
  Still open in Phase 5: clean run 3 and a fresh clone on another machine.
- **Badges:**
  - 🆕 Addition — `docs/devpost.md`: the Devpost description, the NVIDIA
    and Token Factory field, and a feedback draft (`06e57d8`, `bd51003`,
    `f18156c`). PLAN.md Phase 6 gained the terminal and Nebius framing
    (`668130a`).
  - 🆕 Addition — README: "Why a terminal, and why local", the limits say
    what Nebius does, "Models and Nebius usage" rewritten to lead with
    Token Factory, the jester moved below setup, and a screenshot of a run
    under the intro (`abb09b6`, `733715f`, `7094249`, `a070364`,
    `5a9ab7b`, `c457b7d`).
  - 🐛 Bug fix — each health bar follows the status beside it: api was red
    beside UP under a cache fault, and a down layer turned green once the
    fault was lifted (`2945b27`).
  - 🐛 Bug fix — TUI panels repaint only when their text changes; every
    update had re-laid out the whole screen, which flickered (`b38c32e`).
  - 🐛 Bug fix — the routing voice line "the search results voted. api
    lost." read as api being ruled out; it now says the vote went to that
    layer (`1a663d4`).
  - 🐛 Bug fix — a probe that times out shows "TimeoutError: no answer in
    2000 ms" instead of a bare "TimeoutError:" (`0d723ab`).

## Session [2026-10-22-1520]

- **Start status:** `8df54c9`, working tree clean. Phase 5 in progress:
  the no-query abort undecided, no clean runs logged, no fresh clone.
  Run in parallel with a session drafting the Devpost fields (`668130a`
  to `f18156c`), whose commits are not part of this entry.
- **End status:** `8b81860` plus this entry. 197 tests, lint clean. The
  replay recording was not re-recorded: no prompt or model-map change.
  Clean runs: 2 of 3 from a fresh `make up` (`--scripted`). Still open in
  Phase 5: clean run 3 and a fresh clone on another machine.
- **Badges:**
  - 🆕 Addition — a round where Nano returns no valid Tavily query
    searches one templated query instead of stopping the run: a seeded
    pick of a dependency and failure term, version from the lockfile,
    never one already searched, marked `(templated)` on screen
    (`b2f96e4`).
  - 🐛 Bug fix — a model outage stops the run before any search instead of
    templating the query and failing later on the wrong call site
    (`78990e3`). Found by a QA bug hunt on `b2f96e4`.
  - 🐛 Bug fix — an invalid item in Nano's reply no longer discards a valid
    query beside it (`b250165`). Found by the same hunt.
  - 🆕 Addition — closing the terminal window reverts the scripted fixes
    on Windows; before, they stayed applied until the next run
    (`023708a`). Every revert is now logged, whichever path runs it
    (`8b81860`).
  - 🐛 Bug fix — `/zoom` with nothing zoomed says what to zoom instead of
    doing nothing (`646899a`).

## Session [2026-10-22-1503]

- **Start status:** `9f23fed`, working tree clean. Phase 5 in progress, run
  in parallel with session 2026-10-22-1315. Phase 7 (video) had its rules
  but no format, introduction, outline or script.
- **End status:** `a03731a` plus this entry. Documentation only, no code
  change. A report that the run stayed on "press p when it is saved" was
  caused by the launch mode, not the code: the TUI was started in real
  patch mode instead of `--scripted`, with the target's edits saved before
  the run began, so P found no new changes. Still open: the script's
  take-dependent brackets, filled in when the video is recorded on Wed
  28 Oct.
- **Badges:**
  - 🆕 Addition — Phase 7 plan: screen recording with a voice-over recorded
    afterwards and a few captions; a Draft A introduction after the cycle-2
    cold open; a 2:40 outline; a commands segment (`/why`, `/diff`,
    `/calls`, `/cost`, `/log`); no repo URL in the video.
  - 🆕 Addition — `demo/SCRIPT.md`: the voice-over script, segment by
    segment, with captions and a pre-recording checklist.

---

## Session [2026-10-22-1315]

- **Start status:** `34a27b0`, working tree clean, 184 tests passing.
  Phase 5 in progress. The dim field on the trade-off page showed only
  after the choice on screens under about 42 rows; choosing A or B went
  straight to the end splash; the field was motionless.
- **End status:** `0bc8f47` plus this entry, 193 tests passing, lint and
  format clean. No decision-chain change, so the replay fixture stands.
  Still open: the no-query abort decision, the Phase 5 runs (three clean
  in a row, a fresh clone elsewhere); feature freeze Mon 26 Oct.
- **Badges:**
  - 🆕 Addition — `LIMITATIONS.md`: documented failure cases, separate
    from the design guarantees in the README.
  - 🆕 Addition — Judges' meeting advice planned into Phases 5–8: the
    re-break pitch, the cycle-2 cold open, the README restructure and a
    limitations summary in Devpost.
  - 🆕 Addition — The run stays on the decided page after the choice, for
    commands and `/log`; Q or `/quit` brings up the moral, any key quits.
  - 🆕 Addition — A pendulum glow swings along the trade-off field while
    the choice waits, then rests on the chosen letter.
  - 🆕 Addition — Onboarding line in the NOW box until the first turn:
    "You: watch. Two rounds of break, fix and re-test, then a trade-off
    you pick."
  - 🐛 Bug fix — The field showed only after the choice on screens under
    about 42 rows; the recap now gives way while the replies are empty.
  - 🐛 Bug fix — The trade-off cards changed width on the first frame and
    after `/log`; they are now sized from the frame.
  - 🐛 Bug fix — `/log` refused while the chosen cost ran ("the run log is
    already on screen"); it now switches to the decided page then too.

---

## Session [2026-10-21-2230]

- **Start status:** `a2f1275`, working tree clean, 145 tests passing.
  Phases 1–4 complete; Phase 5 (rehearsal and freeze) not started. The
  developer's patch was only read, never run; scripted mode applied one
  fixed diff per round; routing evidence was behind `/why`; the trade-off
  page stacked A and B over a CPU chart.
- **End status:** `88b861a` plus this entry, working tree clean, 184 tests
  passing, lint and format clean. Replay fixture re-recorded with `make
  record`; the replay test passes. Containers down. First thing next
  session: the dim field on the trade-off page shows after the choice
  instead of while the choice waits. Still open: the Phase 5 runs (three
  clean in a row, a fresh clone elsewhere); feature freeze Mon 26 Oct.
- **Badges:**
  - 🆕 Addition — The patch runs: the target's source is mounted into the
    api container; after a patch Bedlam removes the fault, restarts the
    api with the patch, injects the same fault again and reads through
    the app (Redis session, Postgres user and tiers). Before and after are
    shown with a held verdict: hanging or erroring to answering, a hang or
    slow answer at least twice as fast; a faster error never counts.
    `make up` seeds the admin the probe signs in as. `docs/live-patch.md`.
  - 🆕 Addition — Prepared fix library: scripted mode applies the fix for
    the live fault (db-fallback, db-failfast, session-cache), built from
    one-file pieces that stack across rounds. All 12 catalog faults held
    against their fix in a live check.
  - 🆕 Addition — The Tavily routing on screen each cycle: results with
    Nano's labels, scores and sources, a bar per layer of the summed
    scores, the winning specialist and the basis, honest about fallbacks.
  - 🆕 Addition — Trade-off page redesign: A and B as two cards with
    aligned rows, identical while waiting; "how you got here" with each
    round's patch verdict; the panel takes only the rows it needs, the
    replies get the rest; a dim field (a band rising from A to B) in the
    empty reply log. The CPU chart and `/cpu` are removed.
  - 🆕 Addition — Planned: a developer manual (Phase 6).
  - 🐛 Bug fix — A reload under a db fault failed at startup and left the
    api down into the next cycle; the api now restarts on a healthy stack.
  - 🐛 Bug fix — Scripted fixes failed to apply on a fresh Windows clone
    with autocrlf on ("patch does not apply"); the diff now follows the
    patched file's line endings.
  - 🐛 Bug fix — After a killed TUI run, the next run's cleanup restarted
    the api under the baseline probe ("layers down before any fault");
    the run now waits for the api first.
  - 🐛 Bug fix — The admin seed was silently skipped: the boilerplate's
    example password fails its own password policy.

---

## Session [2026-10-21-1737]

- **Start status:** `84a89e6`, working tree clean, 122 tests passing.
  Phases 1–4 complete. The TUI command line had `/help`, `/patch`,
  `/choose` and `/quit`; the run ended back on the run log, and commands
  typed on the trade-off page replied into a hidden panel.
- **End status:** `710a48d`, working tree clean apart from this entry, 145
  tests passing, lint and format clean. Replay test passes; no decision
  path changed, so the fixture was not re-recorded. Still open: `/grep`'s
  count reads "1 lines match"; the README does not yet mention the
  commands, the end splash or `make run SEED=` (Phase 6). Next: Phase 5
  (rehearsal and feature freeze, Mon 26 Oct).
- **Badges:**
  - 🆕 Addition — End splash: a completed run brings the jester back with
    the moral, fixed text, no model call: "it was never stable. you just
    stopped looking." and, dim, "same time next sprint." Any key returns to
    the frame; a failed run ends without it.
  - 🆕 Addition — `make run SEED=1729` passes the root seed to the TUI.
  - 🆕 Addition — Run commands: `/status`, `/why` (routing weights and the
    Tavily results behind them; the `routed` event now carries the
    classified results already in the trace), `/diff`, `/seed` (states that
    only replays reproduce exactly).
  - 🆕 Addition — Output and layout commands: Tab completion, `/grep`,
    `/zoom timeline|agent`, `/copy` (OSC 52), `/save` (text beside the
    trace), `/shot` (SVG), and a hidden `/sudo` that runs nothing.
    Textual's Ctrl+P palette is off, so `/` is the only command line.
  - 🆕 Addition — Post-mortem page: the run ends on the decided trade-off
    (choice marked, cost shown live, decision record) with a POST-MORTEM
    log under it, until Q; a 5-row strip of the same log while choosing,
    when the options leave room. `/cycles`, `/cycle N`, `/why N`,
    `/diff N`, `/calls`, `/cost`, `/cpu`, `/log`, all read from the run's
    own events.
  - 🐛 Bug fix — On the trade-off page every command replied into the
    hidden timeline, so the command line looked dead there.
  - 🐛 Bug fix — The footer offered P after the run was over.
  - 🆕 Addition — `/grep` filters the post-mortem log: earlier replies
    filtered, echoes and the latest reply always shown.
  - 🆕 Addition — A test runs every command, `/sudo`, an unknown command
    and free text during the trade-off and after the run, and fails if the
    model or Tavily call counts move: the command line is not a chat.

## Session [2026-10-21-1506]

- **Start status:** `ea2af77`, working tree clean, 96 tests passing. Phases 3
  and 4 complete. Open: Super did not always match an option's consequence
  fault to its stated cost; the wide layout left the trade-off panel half
  empty.
- **End status:** `4529e30`, working tree clean apart from this entry, 122
  tests passing, lint and format clean. Both open issues closed. Replay
  fixture re-recorded live after the escalation prompt change. Still open:
  the fault now always matches the condition an option names, but whether
  that condition matches the option's cost sentence is the model's call (in
  the live record, "drops valid requests on temporary stalls" was given
  "cache drops connections"); the mismatch is now visible on screen in plain
  words. Next: Phase 5 (rehearsal and feature freeze, Mon 26 Oct).
- **Badges:**
  - 🐛 Bug fix — The trade-off's consequence fault could contradict the
    option's cost. Options now give a cost layer and one of five plain
    conditions (slow, hangs, stalls then drops, drops connections, crawls);
    code maps the pair to the catalog fault and rejects anything off the
    list. The screen shows `felt when cache is slow · shown live as
    cache.latency.2500` on one line, so the longest trade-off still fits at
    82 x 30; the decision record gains "Felt when".
  - 🆕 Addition — THE RUN SO FAR: every CPU sample of the run, charted per
    container under the trade-off options with each round's fault window
    labelled, in whatever height the options leave (one row per container
    at 82 x 30, up to eight on a tall terminal, none without samples).
    Updates live while the developer decides. Display only.
  - 🆕 Addition — The jester, designed with Claude Design: a big launch
    splash with the BEDLAM wordmark (2.5 s, any key skips) and a 9 x 3 face
    beside the NOW box from 93 columns up, its mood following the voice's
    event keys. Display only, no randomness.
  - 🆕 Addition — README section on the jester: the splash as an SVG
    exported with Rich in the TUI's colours, and a table of moods.

## Session [2026-10-20-2344]

- **Start status:** `8a4cbf9`, working tree clean, 85 tests passing. Phase 3
  built but its done-when boxes not ticked; Phase 4 not started.
- **End status:** `5aa960e`, working tree clean apart from this entry, 96
  tests passing, lint and format clean. Phases 3 and 4 complete, every
  done-when box ticked; the Phase 4 framing box after the developer read the
  trade-off screen live. Replay fixture re-recorded live with the escalation
  call. Open: Super does not always match an option's consequence fault to
  its stated cost; the wide layout leaves the trade-off panel half empty.
  Next: Phase 5 (rehearsal and feature freeze, Mon 26 Oct).
- **Badges:**
  - 🆕 Addition — `bedlam/escalation.py` and
    `prompts/tradeoff_escalation.md`: after round 2, Super writes one
    trade-off with two options (gain, cost, and the catalog fault under
    which that cost is felt). Code rejects recommendation wording, a shared
    consequence, unknown faults and text too long for 82 columns; a logged
    templated pair stands in if every model fails.
  - 🆕 Addition — The developer chooses with A/B or `/choose`; Bedlam never
    picks. The chosen cost is applied once, probed and removed, and a
    decision record is written beside the trace. Headless runs take
    `--choice a|b`; without it the options are recorded and nothing is
    picked.
  - 🆕 Addition — A full-frame TRADE-OFF panel in the TUI, with NOW box,
    voice and footer for every escalation step.
  - 🐛 Bug fix — Round 2 could stop the run when Nano repeated a round-1
    query on every attempt. The round now goes on with the best usable
    queries (at least one), logged and marked `short` in the trace.

## Session [2026-10-20-2318]

- **Start status:** `287c95b`, working tree clean, 48 tests passing.
  Phase 2 complete; Phase 3 (TUI) not started.
- **End status:** `f874fae`, working tree clean apart from this entry, 85
  tests passing, lint and format clean. The Phase 3 TUI is built and was
  run live end to end. The Phase 3 done-when boxes are not ticked yet.
  Real patch mode is now the default: P reads the developer's own edit
  with git and waits on an empty diff; `--scripted` keeps the old one-key
  patch. Other target repos are deferred until after submission. Next:
  close Phase 3, then Phase 4 (trade-off escalation).
- **Badges:**
  - 🆕 Addition — Textual dependency; loop events through an optional
    observer hook; the TUI with YOUR APP, WHAT BEDLAM DID and AI MODELS
    panels, fluid above an 82-column minimum, in the Bedlam palette.
  - 🆕 Addition — `bedlam/voice.py`: templated, seeded voice lines, with
    eight film lines played first at their matching moments; the latest
    line holds still in a BEDLAM SAYS row.
  - 🆕 Addition — `bedlam/guide.py`: a NOW box that says which step the
    loop is in, where to look and when it is the developer's turn; probe
    lines fill while probes run.
  - 🆕 Addition — Real patch mode (`bedlam/patches.py`): git snapshots of
    `targets/fastapi-boilerplate` before and after the developer's edit.
  - 🆕 Addition — A command line with a cursor: `/help`, `/patch`,
    `/quit`, ready for later slash commands.
  - 🆕 Addition — `bedlam/stats.py`: per-container CPU (with sparkline)
    and memory from `docker stats`, display only, the judges' request.
  - 🐛 Bug fix — The BEDLAM SAYS text was invisible: the label's
    background style leaked onto the line.
  - 🐛 Bug fix — Round-2 query formulation failed with "need 2 new
    queries"; the rejection now names each skipped query and why, so the
    retry can fix it.

## Session [2026-10-20-2114]

- **Start status:** `c62ba28`. Uncommitted: the Redis labelling fix and
  `max_tokens` 768 from the previous session. Open: the replay test and the
  Phase 2 determinism rewording.
- **End status:** `9b697fe`, working tree clean apart from this entry, 48
  tests passing, lint and format clean. Phase 2 is complete: the determinism
  item is reworded to replay of recorded inputs and ticked, and CLAUDE.md
  and the Phase 5 rehearsal check now say the same. PLAN.md has a new §7
  Backlog with two TUI ideas from the judges meeting: slash commands, and
  agent and resource usage on screen (the judges asked for the latter).
  Still open: Nano still labels some Redis results `db` (a wrong layer, which
  the new check does not catch), and one fault-selection rationale did not
  match the fault it picked. Phase 3 (TUI) starts 22 Oct.
- **Badges:**
  - 🆕 Addition — `bedlam/replay.py`, `make record` and
    `tests/test_replay.py`: one live run's model replies, Tavily responses
    and probe snapshots are recorded, then replayed three times. Each replay
    must reproduce the live fault sequence. Replay answers only
    byte-identical requests, so a prompt or model-map change asks for a
    re-record.
  - 🆕 Addition — The component Nano names for each search result is
    recorded in the trace.
  - 🐛 Bug fix — Batched layer labels drifted by one index at the boundary
    between two queries' results. A phpredis issue was labelled `httpx/api`,
    and that one label routed cycle 2 to the api specialist instead of
    cache. A label must now name a component that appears in its own
    result. A failure is retried with the reason. If Nano keeps failing, the
    failing labels are left out of the vote and logged, and the run goes on.

## Session [2026-10-19-2113]

- **Start status:** `478a3be`, working tree clean, 39 tests passing. Open:
  the suspected HTTP 409 on a leftover Toxiproxy toxic, and the live
  Phase 2 determinism check.
- **End status:** The leftover-toxic bug was reproduced live and fixed
  (`075ef00`). The live determinism check failed: three runs with seed
  1729 gave three different fault sequences, and one run crashed. Root
  cause: Token Factory returns different outputs for identical requests at
  temperature 0 with a fixed seed (layer classification on one frozen
  result set labelled 5/6 one way, 1/6 another). The crash is fixed
  (`e24547a`) and synthesis now runs at temperature 0 (`a9ab11b`). 42
  tests pass, lint and format clean. Measured on frozen inputs: fault
  selection alone is stable (8/8); synthesis keeps a stable eligible pool
  (5/5) but rewords its hypotheses (3 distinct of 5), and the pick follows
  the wording (4/1). A tier-rating selection variant was tried and dropped:
  it rated every fault "medium", which would hand the choice to the RNG.
  Still open, deferred to a later session:
  - Replay test: record one live run's model and Tavily responses, replay
    them, and assert the same fault sequence.
  - Reword the PLAN.md Phase 2 Done-when item from "same seed, same fault
    sequence across three runs" to reproducibility given recorded inputs.
  - Deferred, may not be done: show fault selection only the structured
    candidate fields, not the hypothesis prose.

  Later in the session, `make prove-routing` showed live that Tavily output
  changes the specialist. Three searches gave two distinct specialists
  (db, db, api), and dropping the winning layer's results from the merged
  set moved the route from db to api. It held on a second live run. Three
  Phase 2 Done-when items are now ticked in PLAN.md; the determinism item
  stays open.
- **Badges:**
  - 🆕 Addition — `scripts/prove_routing.py` and `make prove-routing`: runs
    the loop's real search, classify and route path against live Tavily and
    live Nano, with the model side held fixed. It writes the evidence to
    `traces/routing-proof.json` and exits non-zero if routing does not
    follow the search output.
  - 🐛 Bug fix — Layer classification labelled Redis results `db` (20 of 20
    labels on a saved redis-py result set), so the cache specialist was
    never reached. Nano now names the failed component of each result
    before choosing its layer. On the same saved sets, Redis went to
    `cache` 20 of 20 and asyncpg/SQLAlchemy stayed `db` 20 of 20. An
    explicit "Redis is cache" rule was tested and left out: naming the
    component was enough on its own. `make prove-routing` now reaches all
    three specialists (cache, db, api) on two live runs, up from db, db, api.
  - 🐛 Bug fix — Layer classification had `max_tokens=256`, which truncated
    the reply mid-JSON on a 15-result set. It is now 768, enough for the
    loop's maximum of 10 results with the component field.
  - 🐛 Bug fix — A run killed while a fault was live left its toxic in
    Toxiproxy. The next run failed with HTTP 409 when re-creating the same
    toxic name, or failed the baseline with a misleading "Run `make up`"
    message. The loop now clears every toxic on the proxied layers before
    the baseline probe and logs what it removed. `fault.apply()` moved
    inside the `try`, so a toxic is removed even when its create times out
    on the client side. The primitives docstring no longer claims that
    re-injection replaces a toxic.
  - 🐛 Bug fix — On an invalid model reply, the retry resent the identical
    request, which at temperature 0 returned the same invalid answer. Nano
    sites have no fallback, so the run failed (query formulation copied
    the prompt's example failure term and repeated a previous query). The
    retry now includes the rejected reply and the parser's reason. A
    fallback model still gets the original request.
  - 🐛 Bug fix — Synthesis ran at temperature 0.3, so the eligible fault
    pool changed from run to run. It now runs at 0.0, in the model map and
    the PLAN.md table.

## Session [2026-10-19-1051]

- **Start status:** Phase 2 bug fixes committed (`0ebbc9c`, 39 tests
  passing). Working tree clean. Still open: the suspected HTTP 409 on a
  leftover Toxiproxy toxic, and the live Phase 2 determinism check.
- **End status:** `make smoke` passes live. All four model ids are
  callable with their exact casing and each replies `ok`. Tavily returns
  five usable results for a dependency-targeted asyncpg query. Earlier
  runs got HTTP 401 until real keys were in `.env`. The open items from
  the previous session are unchanged.
- **Badges:**
  - 🐛 Bug fix — `scripts/smoke_nebius.py`: when every model failed, the
    raw-response dump crashed with `UnboundLocalError: resp` and hid the
    clean failure summary. When only the last model failed, the dump
    showed an earlier model's response under the wrong label. It now dumps
    the last successful response, names its model, and is skipped when no
    call succeeded.
  - 🐛 Bug fix — `scripts/smoke_nebius.py`: the smoke call left Nemotron's
    thinking mode on, so the reasoning trace used the whole 16-token budget.
    Super and Nano returned empty replies, but the script still reported
    OK. It now sends `enable_thinking: False`, the same way `ModelClient`
    does.

## Session [2026-10-17-2200]

- **Start status:** Phase 2 decision chain built and verified offline
  (`36012ea`, 27 tests passing). Live three-run determinism check still
  pending.
- **End status:** A read-only bug hunt over the whole codebase found three
  confirmed defects and one suspected. All three confirmed defects are fixed
  with regression tests; 39 tests pass, lint and format clean. Still open,
  unverified against a live Toxiproxy: a toxic left behind by a killed run
  may make the next injection of the same fault fail with HTTP 409. The live
  Phase 2 determinism check is still pending.
- **Badges:**
  - 🐛 Bug fix — `bedlam/trace.py`: a run that failed mid-cycle crashed
    while writing its trace (`KeyError: 'selection'`), losing the trace file,
    masking the real error and skipping transport cleanup. Partial cycles are
    now kept in the trace but left out of the fault and specialist sequences.
  - 🐛 Bug fix — `bedlam/topology.py`: `BEDLAM_API_URL` with a trailing
    slash or a path crashed every `bedlam` import. The URL is now parsed with
    `urllib.parse.urlsplit`; unusable URLs fail with a clear message.
  - 🐛 Bug fix — `bedlam/topology.py`, `bedlam/probes/api.py`: an `https`
    API URL without a port resolved to port 80 and was probed over `http`.
    The default port now follows the scheme, and the probe uses a new
    `base_url` on the endpoint, which also keeps IPv6 hosts bracketed.
  - 🆕 Addition — `tests/test_topology.py` and a failed-run trace test in
    `tests/test_loop.py`, covering the three fixes above.

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
