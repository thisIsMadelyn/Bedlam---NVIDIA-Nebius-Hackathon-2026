# Live patch

Since 21 Oct the developer's patch actually runs, and Bedlam measures
whether it held. Before that, the patch was only read.

## Before and after

| | **Before 21 Oct** | **Now** |
|---|---|---|
| **Pressing P (scripted)** | Bedlam read the round's fixed diff (`cycle1.diff`, `cycle2.diff`) as text, whatever the fault. No file changed. | Bedlam picks the prepared fix that targets the live fault and `git apply`s it to the submodule. The real source files change on disk. |
| **Pressing P (real mode)** | Bedlam read your `git diff`. Your edit sat on disk; the container ran its baked-in copy. | Same `git diff`, but the container mounts the submodule, so your edit is the code it runs. |
| **Is the patch running?** | No. The api always ran the original image. | Yes. The api container restarts with the patched files. |
| **"Recovery"** | Bedlam removed its own fault. The app turned green; the patch had nothing to do with it. | Bedlam removes the fault, restarts the app with the patch, then injects the **same fault again** to test it. |
| **Did the fix work?** | Unknown. Super read the diff and guessed what it defends. | Measured: one request through the app (session from Redis, tiers from Postgres) under the same fault, before and after the patch. |
| **On screen** | `patch in: cycle1.diff`, then `fault removed` | `patch in: fix db-failfast`, then `same fault again`, then `through the app: hung 6191ms → answered in 200ms · patch held` |
| **After the run** | Nothing to clean up. | Applied diffs are reverted; the submodule is back to its commit. A killed run is cleaned up at the next start. |
| **Diff analysis (Super)** | Ran. | Still runs, unchanged, now beside a measured result. |

## One cycle

```
1. inject fault          e.g. db.connection_cut, through Toxiproxy
2. probe                 layer probes + one read through the app  -> BEFORE
3. your turn             P: the diff is applied to the real files (scripted)
                         or your saved edits are taken as they are (real)
4. remove fault          stack healthy again
5. restart api           the container starts clean with the patched code,
                         and one read through the app warms it up
6. same fault again      the same fault goes back in, alone
7. read through the app  -> AFTER, compared with BEFORE: held or not
8. remove fault, analyse Super reads the diff, as before
```

Only one fault is ever live. Step 6 re-injects the same fault after the
first one is removed, so one fault still maps to one patch.

The api restarts at step 5 instead of reloading under the fault: the
boilerplate connects to Postgres at startup, and a reload under a db fault
fails and leaves the api down. The warm-up read stands in for the real
traffic that fills caches between a deploy and the next failure; without
it, a fix that caches has nothing to serve.

## The prepared fixes

Scripted mode applies the fix for the live fault (`bedlam/patches.py`,
`FIX_FOR`). Each fix is one or more component diffs in `demo/patches/`, one
file each, so fixes stack across rounds without conflict; a component
already in is not applied twice.

| Component | Real change in the boilerplate |
|---|---|
| `db-timeouts` | engine: pool checkout 2s, connect 1s, every statement 2s |
| `redis-timeouts` | Redis clients: connect and read 1s, one quick retry instead of three backed-off ones |
| `auth-cache` | the authenticated principal kept in memory: served while fresh (30s), or up to 5 min old when the session store or db fails; safe methods only |
| `user-cache` | the same for the user row `get_current_user` reloads |
| `tiers-cache` | the same for the tiers query |

| Fix | Components | For |
|---|---|---|
| `db-fallback` | auth-cache, user-cache, tiers-cache | db cut, db +300ms, db 1 KB/s |
| `db-failfast` | db-timeouts + the three caches | db +2500ms, db black hole, db 3s freeze |
| `session-cache` | redis-timeouts, auth-cache | every cache fault |

Timeouts alone do not defend a db hang: one request makes several db calls,
so a hang only becomes a slow error. Failing fast into the fallback is what
answers. The fallbacks are a real trade-off: a revoked session or a changed
user or tier is seen up to 30s late, 5 minutes while the store is down.

Checked live on 21 Oct, every fault against its fix through the real path
(apply, restart, warm-up, same fault): all 12 held. Before → after, ms:

| Fault | Fix | Before | After |
|---|---|---|---|
| cache +300ms | session-cache | answered 2312 | answered 499 |
| cache +2500ms | session-cache | hung 6181 | answered 2169 |
| cache 1 KB/s | session-cache | answered 1351 | answered 226 |
| cache cut | session-cache | 500 in 191 | answered 229 |
| cache black hole | session-cache | hung 6202 | answered 2202 |
| cache 3s freeze | session-cache | 500 in 3216 | answered 2225 |
| db +300ms | db-fallback | answered 2647 | answered 205 |
| db +2500ms | db-failfast | hung 6197 | answered 200 |
| db 1 KB/s | db-fallback | answered 876 | answered 186 |
| db cut | db-fallback | 500 in 201 | answered 196 |
| db black hole | db-failfast | hung 6191 | answered 200 |
| db 3s freeze | db-failfast | hung 6175 | answered 189 |

The db fixes answer from memory here because the warm-up read is under 30s
old. Past that, the db call is tried first and the stale copy answers only
once it fails; that path, timeouts into a stale copy under a hang, was not
part of this check.

## The held rule

`bedlam/probes/app.py`, `held()`:

- the read went from hanging or erroring to **answering**: held
- it **hung** before and now ends at least twice as fast (for example it now
  fails fast instead of hanging): held
- it **answered slowly** and now answers at least twice as fast: held
- anything else: did not hold

An error that comes back faster is still an error, so a speedup never
counts from an error. Both numbers are always on screen, so the verdict
can be checked.

## Setup it needs

- `docker-compose.yml` mounts `targets/fastapi-boilerplate/backend/src` into
  the api container; the watcher polls (`WATCHFILES_FORCE_POLLING`).
- Real patch mode needs no library: your own saved edits are what runs.
- `make up` runs the boilerplate's own seed script, which creates the admin
  the app probe signs in as (`bedlam` / `Bedlam-local-1`, local placeholders).
- Scripted diffs are applied with `core.autocrlf=false`, so a Windows git
  does not leave the submodule dirty.
