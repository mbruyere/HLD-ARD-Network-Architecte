# MCP Client Hang Fix — Persistent Background Event Loop

Date: 2026-04-15
Commit triggering the discovery: `4b71831` (HLD Device Inventory Table
reconciliation — 4 VyOS firewall rows added)
Predecessor: [FIX_NOTES_Slice4_Approval_Gate.md](FIX_NOTES_Slice4_Approval_Gate.md)

## Symptom

The post-commit hook fired on `4b71831` and the pipeline exited
silently after ~20 seconds. The hook log only contained the first
Live-Memory MCP call — no stage results, no error, no traceback.
Running the pipeline foreground reproduced the hang: the process
stayed alive indefinitely after making a single `live_note()` call.

Every Slice 1-4 integration test still passed in isolation, but the
first sync invocation of the LiveMemoryClient from a library context
would hang forever.

## Root cause

`asyncio.run()` on Python 3.14.3 + mcp 1.27 + httpx 0.28 + anyio 4.13
**hangs in the teardown phase** after a coroutine that uses
`streamablehttp_client` returns. The coroutine body completes and
returns a value, but the outer `asyncio.run()` never unwinds because
the anyio TaskGroup inside `streamablehttp_client` leaves background
tasks (SSE GET stream + connection manager) that keep the loop alive.

Proof: adding a `print()` between the `await` and the function's
`return` showed the value was received, but the outer code after
`asyncio.run()` never ran.

This bug was present from Slice 1 onwards. It was masked in most
places by:

- **Short-lived scripts:** `asyncio.run(main())` at the top of a
  script, with no code after. Python interpreter exit forcibly tore
  down the stuck loop — `time` reported ~5s total, not 0s, because
  the teardown cost was real — but the script "succeeded."
- **Timing:** on fresh Live-Memory instances with no pre-existing
  sessions, the TaskGroup sometimes drained fast enough before being
  checked.
- **atexit luck:** Python's own cleanup paths sometimes interrupted
  the stuck loop before the next MCP call was issued.

Today the bug stopped masking itself. Library code that runs many
MCP calls back-to-back inside a long-lived process (the orchestrator
+ hook pipeline) hangs on the **first** call.

## The fix

Run all MCP coroutines on a **persistent background event loop** in
a daemon thread, submitted via `asyncio.run_coroutine_threadsafe`.
The loop never tears down → no teardown bug. Each coroutine's own
`async with streamablehttp_client` still runs its TaskGroup cleanup
inline before the future resolves, so nothing leaks inside the loop.

```python
# src/ibn/core/live_memory_client.py  (and identical in graph_memory_client.py)

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()

def _get_background_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()
        def _runner(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        _loop_thread = threading.Thread(
            target=_runner, args=(_loop,), daemon=True, name="ibn-mcp-loop",
        )
        _loop_thread.start()
        atexit.register(_shutdown_background_loop)
        return _loop


def _run(coro_factory, *args, **kwargs):
    loop = _get_background_loop()
    async def _wrapper():
        if asyncio.iscoroutine(coro_factory):
            return await coro_factory
        coro = coro_factory(*args, **kwargs)   # instantiate INSIDE loop
        return await coro
    return asyncio.run_coroutine_threadsafe(_wrapper(), loop).result(timeout=120)
```

### Call-site API change

`_run(coro)` → `_run(factory, *args, **kwargs)`. Every `_call` in
both clients now passes the async function plus its arguments so the
coroutine is instantiated **inside** the event loop:

```python
# before
return _run(_call_mcp_tool(self._base, self._token, tool, args))
# after
return _run(_call_mcp_tool, self._base, self._token, tool, args)
```

Creating the coroutine inside the loop avoids a subtler variant of
the same bug where a coroutine created on no loop, then handed to a
loop, sometimes captured a stale context.

### atexit cleanup

Without a shutdown hook, Python 3.14 would segfault on interpreter
exit when the daemon thread was torn down while the loop was still
running. `_shutdown_background_loop()` is registered via `atexit`
and:
1. calls `loop.call_soon_threadsafe(loop.stop)` from the main thread
2. joins the daemon thread with a 2s timeout
3. closes the loop

The cleanup is best-effort — if it fails, the interpreter will
still exit, and any orphan work is non-recoverable anyway.

## Before / after

| Scenario | Before fix | After fix |
|---|---|---|
| Single `lm.live_note()` from a library context | **hangs indefinitely** (process must be killed) | 1.5s, status=created |
| Three sequential `lm.*` calls | hangs on first, second never runs | 1.6s **total** — connection reuse via the persistent loop |
| Full pipeline run on `4b71831` commit (A1 + Provisioning + A4 + Gate) | hung at first MCP call, exited ~20s via interpreter death | completed cleanly at the approval gate |
| `ibn approve 4b71831` (resume A3 → A5 → A7) | would never have worked | completed end-to-end, MigrationPlan APPLIED |
| Full Slice 1/2/3/4 regression suite | 100/100 pass (88s) | 100/100 pass (65s — faster because of connection reuse) |

## Orchestrator bug fixed at the same time

With MCP unblocked, the pipeline surfaced a latent bug for
device-only HLD commits (only device inventory changes, no
populations): the orchestrator fabricated a sentinel
`INT-DEVICE-PROVISION-<sha>` intent id and passed it to A2, which
raised `ValueError: Intent ... not found in Neo4j`.

Fix in `src/ibn/pipeline/hld_commit.py`: split intent lists into
`real_intent_ids` (from A1 ingestion, fed to A2) and
`render_intent_ids` (fed to A3/A5/A7 — includes the sentinel when
necessary). A2 stage now reports `status=skipped` with summary
"device-only commit — no intents to decompose" when there are no
real intents.

## Live reconciliation outcome

The HLD Device Inventory Table in `Enterprise_Campus_Network_HLD
(1).md` was extended with 4 VyOS firewall rows matching the running
lab containers. The closed loop reconciled Neo4j against the HLD:

| Device | Before | After |
|---|---|---|
| DEV-HQ-USF-01/02 | Fortinet / `platform=None` / no clabContainer | VyOS / vyos / clab-ibnlab-usf1 (usf2) — **ACTIVE** |
| DEV-HQ-DMZFW-01/02 | Fortinet / `platform=None` / no clabContainer | VyOS / vyos / clab-ibnlab-dmzfw1 (dmzfw2) — **ACTIVE** |
| `fw-hq-usr-01` orphan | — | (left in place — separate cleanup) |

All 4 firewalls got ADOPTED `LifecycleEvent` nodes (lifecycle went
PLANNED → ACTIVE via the new Provisioner adopt path, since the
containers were already running from netlab). MigrationPlan
`PLAN-4b71831` transitioned PENDING → APPROVED (by `ubuntu`) →
APPLIED.

This was the first end-to-end HLD-driven **reconciliation** (existing
devices being brought under SSoT governance) rather than brand-new
provisioning. Same pipeline, same agents, same approval gate — just
the Provisioner's adopt path instead of `clab deploy`.

## Files changed

| File | Change |
|---|---|
| `src/ibn/core/live_memory_client.py` | Persistent background loop + atexit shutdown. `_run` signature changed from `(coro)` to `(factory, *args, **kwargs)`. `_call` updated. |
| `src/ibn/core/graph_memory_client.py` | Same fix applied (identical `_run` pattern). |
| `src/ibn/pipeline/hld_commit.py` | Split `real_intent_ids` / `render_intent_ids` so device-only commits don't pass a fake intent id to A2. |
| `src/ibn/agents/provisioner.py` | `provision()` now has an **adopt path**: if target container is already running, skip clab deploy, write ADOPTED LifecycleEvent, mark Device ACTIVE. |
| `Enterprise_Campus_Network_HLD (1).md` | Device Inventory Table gained 4 VyOS firewall rows. |

## Known limitations

1. **Segfault cosmetic warning at interpreter exit** — atexit hook
   stops the loop cleanly but Python 3.14 can still emit a segfault
   during daemon-thread teardown. All pipeline work is complete by
   that point; the segfault does not affect state. Worth revisiting
   on Python 3.15.
2. **VyOS push still skipped** — A3 renders empty content for
   `platform=vyos` devices because there is no VyOS template chain
   defined (only `srlinux` and the legacy VyOS-firewall chain that
   expects a FirewallPair relationship the seed doesn't provide).
   A5 correctly skips them. Slice 2.5's analysis still applies: the
   `sysoleg/vyos-container` lab image can't accept a real config
   commit anyway.
3. **`MigrationPlan.status=APPROVED` vs. `APPLIED` timing** — the
   approval CLI marks the plan APPLIED *after* A3-A5-A7 complete,
   including any A5 failures. If A5 partially fails on one device,
   the plan still gets APPLIED. Slice 4 accepts this; a finer-grained
   distinction (PARTIALLY_APPLIED) is deferred.

## Recommended followups

- Revisit the Python 3.14 exit-time segfault once mcp / anyio /
  httpx ship a release that doesn't rely on TaskGroup cleanup after
  loop close.
- Reset the `modelState` of the adopted firewalls from CANDIDATE to
  POR (they're ACTIVE in lifecycle, so POR makes more sense for
  model state). Could be a one-shot seed cleanup or a follow-up
  approve to land them in POR.
- Add a VyOS template chain to `_TEMPLATE_CHAINS` so A3 actually
  renders something the Provisioner could push (even if just as
  write-to-config-file, per Slice 2.5 notes).
- Consider upgrading mcp/anyio as soon as a newer release lands that
  fixes the TaskGroup orphan issue, then possibly revert the
  persistent-loop pattern for simplicity.
