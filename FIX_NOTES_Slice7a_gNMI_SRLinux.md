# Slice 7a — gNMI Executor for SR Linux

Date: 2026-04-15
Plan reference: [PLAN_Slice7_NETCONF_gNMI.md](PLAN_Slice7_NETCONF_gNMI.md)
Predecessor: [FIX_NOTES_Slice5_FRR_SRLinux.md](FIX_NOTES_Slice5_FRR_SRLinux.md)

## What shipped

A second, standards-based transport for SR Linux config push:
**gNMI over TLS:57400** via `pygnmi`, gated by
`IBN_SRLINUX_TRANSPORT=gnmi`. Default (`cli`) behaviour is unchanged —
CI and production stay on the Slice-5 `docker exec sr_cli` path.

The A3→A5 contract is preserved: A3 still renders the same
`srl_base` / `srl_interfaces` / `srl_vlans` `set /` CLI blob. A5's new
executor translates the blob into gNMI `(path, value)` updates and
issues a single `SetRequest`. SR Linux commits atomically; no
`enter candidate / commit now` wrapper needed.

## New components

| File | Purpose |
|---|---|
| `src/ibn/agents/_srlinux_yang.py` | Narrow SR Linux `set /` CLI → gNMI `(path, value)` translator. Pure-Python, table-driven, ~120 lines. Merges multiple leaves under the same container into one gNMI op. Unknown lines raise `UnknownCliLine` so template drift can't silently drop config. |
| `tests/unit/test_t23_srlinux_gnmi.py` | 22 unit tests: every line shape the three `srl_*.j2` templates emit, full-blob merge semantics, executor dispatch (`IBN_SRLINUX_TRANSPORT` env flag), monkey-patched `Set` call. |
| `FIX_NOTES_Slice7a_gNMI_SRLinux.md` | this file |

## Modified components

| File | Change |
|---|---|
| `requirements.txt` | `pygnmi>=0.8,<1` |
| `src/ibn/agents/agent5_orchestration.py` | `_srlinux_mgmt_ip()`, `_srlinux_gnmi_executor()`, `_srlinux_gnmi_verifier()`. `_resolve_executor` / `_resolve_verifier` honour `IBN_SRLINUX_TRANSPORT` and route to the gNMI path when set to `gnmi`. |

## Why gNMI (and not NETCONF) first

Both endpoints are live on the stock `ghcr.io/nokia/srlinux:latest`
image — NETCONF on `:830` (SSH-wrapped, `ssh-server mgmt-netconf`) and
gNMI on `:57400` (gRPC/TLS). `pygnmi`'s `(path, value)` API maps
one-to-one to SR Linux's native `set /` CLI structure, which made the
translator trivial. NETCONF's RFC-7950 edit-config payload is a more
verbose XML template and slotted for 7b.

## Translation strategy

Rather than fork the template chain per transport, keep A3
transport-agnostic and translate at A5. The translator has exactly
one rule per line shape the templates emit — ten rules total:

| Line shape | gNMI update |
|---|---|
| `set / system name host-name X` | `(/system/name, {"host-name": "X"})` |
| `set / system information location "X"` | `(/system/information, {"location": "X"})` |
| `set / interface E admin-state S` | `(/interface[name=E], {"admin-state": "S"})` |
| `set / interface E description "X"` | `(/interface[name=E], {"description": "X"})` |
| `set / interface E vlan-tagging B` | `(/interface[name=E], {"vlan-tagging": <bool>})` |
| `set / interface E subinterface I type T` | `(/interface[name=E]/subinterface[index=I], {"type": "T"})` |
| `set / interface E subinterface I description "X"` | `(/interface[name=E]/subinterface[index=I], {"description": "X"})` |
| `set / interface E subinterface I vlan encap single-tagged vlan-id V` | `(/interface[name=E]/subinterface[index=I]/vlan/encap/single-tagged, {"vlan-id": V})` |
| `set / network-instance N type T` | `(/network-instance[name=N], {"type": "T"})` |
| `set / network-instance N interface R` | `(/network-instance[name=N]/interface[name=R], {})` |

Lines under the same container merge — e.g. the three `interface
ethernet-1/1 ...` lines collapse into a single update with three
leaves, cutting wire ops from 10 down to 7 for a typical render.

## Test results

### Unit tests

| Suite | Result |
|---|---|
| `tests/unit/test_t23_srlinux_gnmi.py` (Slice 7a unit) | **22/22 pass** |
| Adjacent regression (T5/T6/T20/T21/T22 + hld_parser) | 116/116 pass |

### Live run (commit `0e93b29` + this work)

```
$ IBN_CLAB_PREFIX=ibnlab-switches IBN_SRLINUX_TRANSPORT=gnmi \
    python -c "from ibn.agents.agent5_orchestration import _resolve_executor; \
               _resolve_executor('srlinux')('DEV-HQ-ACC-01', <rendered blob>)"
executor: _srlinux_gnmi_executor
push result: {
  'status': 'ok',
  'device': 'DEV-HQ-ACC-01',
  'container': 'clab-ibnlab-switches-acc-01',
  'transport': 'gnmi',
  'updates': 7,
  'ops': ['UPDATE','UPDATE','UPDATE','UPDATE','UPDATE','UPDATE','UPDATE']
}
verify: {'verified': True, 'device': 'DEV-HQ-ACC-01', 'checked': 2}
```

Container readback via `sr_cli` confirmed the pushed subinterface and
mac-vrf landed on the device. Cleaned up with a gNMI
`SetRequest(delete=...)` after the smoke test.

## Architectural decisions made during execution

1. **Merge leaves per container, not per line.** Preserves gNMI's
   "atomic by Set-op" semantics and cuts wire round-trips. The
   translator returns an ordered list of `(path, dict)` tuples so
   ordering is still deterministic for debug.

2. **Verifier stays on `sr_cli info from running`.** The existing
   free-form snippet-matching verifier works for gNMI-pushed config
   too — the config lands in `running` the same way. A later slice
   will do schema-aware gNMI Get diffs against the POR model.

3. **TLS `skip_verify=True` for now.** SR Linux presents a
   self-signed cert from clab's lab CA. Pinning the CA is a trivial
   7b followup but out of scope here.

4. **No changes to A3 template chains.** The translator absorbs the
   transport difference, so adding NETCONF (7b) or OpenConfig JSON
   (7c) later is another translator alongside this one — not a
   template fork.

5. **`UnknownCliLine` raises instead of silently dropping.** If the
   SR Linux templates evolve (e.g. Slice 6's per-port VLAN assignment
   work), the translator fails loudly until a rule is added. Unit
   tests cover every currently-emitted line shape.

## Known limitations

1. **Container prefix override.** The gNMI executor reuses
   `_srlinux_container_for`, which derives the clab name from
   `IBN_CLAB_PREFIX` (default `ibnlab`). On this lab the actual
   prefix is `ibnlab-switches`, so the env var must be set. Existing
   sr_cli path has the same behaviour — not a Slice 7a regression.

2. **Translator coverage is bounded by current templates.** Ten
   rules cover Slice 2/5's output. Slice 6's richer per-port VLAN
   assignment will need additional rules; T23 will fail them until
   added.

3. **No CA pinning.** `skip_verify=True` accepts any cert. 7b
   followup.

4. **Atomicity.** The gNMI `SetRequest` is atomic within a single
   call, but we issue one call per device — same blast semantics
   as the sr_cli path, so no regression vs Slice 5.

## Followups

- **7b — NETCONF via ncclient** for SR Linux (port 830, same creds,
  XML edit-config with `candidate` + `commit`). Pair with CA
  pinning.
- **7c — OpenConfig shared templates** rendered once, translated
  to vendor-native paths per transport.
- **7d — gNMI streaming telemetry** in Agent 6 for sub-second inner
  loop cycle time.
- **Schema-aware A7** drift detection using gNMI Get + YANG-aware
  diff rather than free-form snippet matching.
- **Wire `IBN_CLAB_PREFIX` auto-detection** from the clab YAML's
  `name` field so operators don't need to export the env var.
