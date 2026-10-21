# Live patch

Since 21 Oct the developer's patch actually runs, and Bedlam measures
whether it held. Before that, the patch was only read.

## Before and after

| | **Before 21 Oct** | **Now** |
|---|---|---|
| **Pressing P (scripted)** | Bedlam read `cycle1.diff` as text. No file changed. | Bedlam `git apply`s it to the submodule. The real source file changes on disk. |
| **Pressing P (real mode)** | Bedlam read your `git diff`. Your edit sat on disk; the container ran its baked-in copy. | Same `git diff`, but the container mounts the submodule, so your edit is the code it runs. |
| **Is the patch running?** | No. The api always ran the original image. | Yes. The api container restarts with the patched files. |
| **"Recovery"** | Bedlam removed its own fault. The app turned green; the patch had nothing to do with it. | Bedlam removes the fault, restarts the app with the patch, then injects the **same fault again** to test it. |
| **Did the fix work?** | Unknown. Super read the diff and guessed what it defends. | Measured: one request through the app (session from Redis, tiers from Postgres) under the same fault, before and after the patch. |
| **On screen** | `patch in: cycle1.diff`, then `fault removed` | `patch in`, then `same fault again`, then `through the app: hung 6194ms → 500 in 248ms · patch held` |
| **After the run** | Nothing to clean up. | Applied diffs are reverted; the submodule is back to its commit. A killed run is cleaned up at the next start. |
| **Diff analysis (Super)** | Ran. | Still runs, unchanged, now beside a measured result. |

## One cycle

```
1. inject fault          e.g. db.connection_cut, through Toxiproxy
2. probe                 layer probes + one read through the app  -> BEFORE
3. your turn             P: the diff is applied to the real files (scripted)
                         or your saved edits are taken as they are (real)
4. remove fault          stack healthy again
5. restart api           the container starts clean with the patched code
6. same fault again      the same fault goes back in, alone
7. read through the app  -> AFTER, compared with BEFORE: held or not
8. remove fault, analyse Super reads the diff, as before
```

Only one fault is ever live. Step 6 re-injects the same fault after the
first one is removed, so one fault still maps to one patch.

The api restarts at step 5 instead of reloading under the fault: the
boilerplate connects to Postgres at startup, and a reload under a db fault
fails and leaves the api down.

## The held rule

`bedlam/probes/app.py`, `held()`:

- the read went from hanging or erroring to **answering**: held
- it **hung** before and now ends at least twice as fast (for example it now
  fails fast instead of hanging): held
- anything else: did not hold

A speedup counts only after a hang. An error that comes back faster is
still an error, and a freshly restarted app is faster anyway. Both numbers
are always on screen, so the verdict can be checked.

## Setup it needs

- `docker-compose.yml` mounts `targets/fastapi-boilerplate/backend/src` into
  the api container; the watcher polls (`WATCHFILES_FORCE_POLLING`).
- `make up` runs the boilerplate's own seed script, which creates the admin
  the app probe signs in as (`bedlam` / `Bedlam-local-1`, local placeholders).
- Scripted diffs are applied with `core.autocrlf=false`, so a Windows git
  does not leave the submodule dirty.
