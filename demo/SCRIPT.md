# Demo video script

Voice-over for the Phase 7 video. Recorded after the screen capture, not
live. Paced at about 140 words a minute: each segment runs a little short of
its slot so the screen and Bedlam's own lines have room. About 290 words in
total, roughly 2:05 of speech in 2:40.

Text in [brackets] depends on the take: fill it in from the footage.

---

## 0:00–0:15 · Cold open

> I fixed the outage. Bedlam ran my fix, confirmed it held… and then broke
> the app again, somewhere my fix didn't reach.

- Caption: "…and breaks it again where your fix didn't reach."
- Let Bedlam's re-break line sit on screen for about 2 s before the cut.

## 0:15–0:35 · Introduction

> I'm [name], and this is Bedlam. It's for backend developers who fix an
> outage and ship the patch hoping it holds. Chaos tools break your system
> once. Bedlam breaks it, runs your fix, and then breaks it again where your
> fix didn't reach. Here's a run from the start.

- Plain title card (name + Bedlam, no logos), then the TUI at baseline.
- Caption on the title card: "Bedlam: it breaks your app again where your
  fix didn't reach."

## 0:35–0:55 · Cycle 1: search and routing

> Bedlam starts with a live Tavily search: how do these exact dependencies,
> at these versions, tend to fail? A model labels each result by layer, and
> the results vote. The winning layer picks the specialist, and the
> specialist picks one fault.

- Caption: "Live search → layer vote → specialist"
- Hold on the routing scores for a beat: this is the "live search call
  unambiguously visible" check.

## 0:55–1:10 · The damage

> One fault, one layer: [the cache now answers two and a half seconds
> late]. The probes show the damage. On the right, every model call shows
> which model made it.

- Caption: "One fault. One layer."

## 1:10–1:25 · The patch

> My turn. I write a fix and hand it over. Bedlam reads the diff, puts the
> patch into the running app, and hits it with the same fault again. It
> held.

- Caption: "Bedlam runs your fix."

## 1:25–1:45 · Cycle 2: the re-break

> Most tools would stop here. Bedlam looks at what my patch changed, and
> what it didn't. It searches again and goes for [the database], a layer my
> fix never touched. Down again.

- Caption: "…and breaks it again where your fix didn't reach."
- This repeats the cold open. Let Bedlam's line land without narration
  over it.

## 1:45–2:05 · Trade-off

> After two rounds, Bedlam stops breaking things. It asks a question only I
> can answer: two options, each with a cost it measures live. It never
> picks for me. I choose [A].

- Caption: "It never picks for you."

## 2:05–2:35 · Commands

> `/why` shows the search results that picked each layer.
> `/diff`: what Bedlam read in my fix.
> `/calls`: every model call: which model, how many tokens, how long.
> `/cost`: what my choice costs, measured live.
> And `/log` takes me back to the whole run.

## 2:35–2:40 · End

- No narration. Press Q and let Bedlam's moral close the video.

---

## Before recording

1. The fault wording in "The damage" and "Cycle 2" must match the faults
   the take shows. The run is fixed by the seed, so a scripted take shows
   the same faults every time. The last run was `cache.latency.2500`, then
   `db.bandwidth.1`.
2. "Puts the patch into the running app": check that it is true for the
   mode recorded in. If the hot-reload limit in `PLAN.md` still applies,
   say "restarts the app with the patch" instead.
3. Read it aloud once with a timer. If a segment overruns, cut adjectives
   first and keep the verbs.
4. Nothing in frame shows NVIDIA logos or other third-party trademarks.
