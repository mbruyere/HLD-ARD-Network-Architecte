# Slice 7 Plan — NETCONF / YANG / gNMI Config Push

Date: 2026-04-15
Predecessors: [PLAN_Slice5_FRR_SRLinux_Provisioning.md](PLAN_Slice5_FRR_SRLinux_Provisioning.md)

## Goal

Replace CLI-over-`docker exec` with standards-based, schema-validated transports:
**gNMI** (primary, gRPC + OpenConfig/vendor YANG) and **NETCONF** (secondary, SSH + YANG).
CLI path stays as a fallback — dispatch chooses transport per device.

## Why now

Probing a running SR Linux container (`clab-ibnlab-switches-acc-01`, image
`ghcr.io/nokia/srlinux:latest`) confirms the default image already exposes:

| Port | Protocol | Auth | Default config |
|---|---|---|---|
| 830 | NETCONF-over-SSH | `admin / NokiaSrl1!` | `ssh-server mgmt-netconf` enabled, `disable-shell true` |
| 57400 | gNMI/gRPC (TLS) | `admin / NokiaSrl1!` | reachable from host mgmt subnet |
| 22 | SSH | `admin / NokiaSrl1!` | shell (used today by `sr_cli`) |

No lab changes needed for 7a/7b — both endpoints are live and reachable
at `192.168.100.131:{830,57400}` today.

## Scope: four sub-slices

| Sub | Deliverable | Risk | Order |
|---|---|---|---|
| **7a** | gNMI executor for SR Linux via `pygnmi` | low | **first** |
| 7b | NETCONF executor for SR Linux via `ncclient` | low | follow 7a |
| 7c | OpenConfig YANG templates shared across vendors | medium | after 7b |
| 7d | gNMI streaming telemetry in Agent 6 | medium | independent |

Only **7a is in scope for this slice.** 7b–7d are followups documented here
for context; each will get its own plan/fix notes.

## Slice 7a — gNMI for SR Linux (this slice)

### Design

The A3→A5 boundary today is a list of `{device, platform, content}` steps
where `content` is vendor-CLI text rendered from Jinja2. For gNMI we keep
the same A3 template chain (`srl_base`/`srl_interfaces`/`srl_vlans`) — the
rendered CLI text *is* the commit set. At A5 the new executor:

1. Parses the CLI text back into SR Linux YANG paths (lightweight — we
   already know what the templates produce: `/system/name/host-name`,
   `/interface[name=*]/subinterface[index=*]/vlan/encap/single-tagged/vlan-id`,
   `/network-instance[name=*]/type`, etc.)
2. Issues a single gNMI `SetRequest` (replace semantics where appropriate,
   update otherwise) to `<mgmt-ipv4>:57400`.
3. Reads back via gNMI `Get` to verify.

**Alternative considered + rejected:** a separate `srlinux_gnmi`
template chain that renders JSON directly. That forks the template chain
per transport and doubles maintenance. The "parse CLI → YANG paths"
shim is ~60 lines and keeps A3 transport-agnostic.

### Feature flag

`IBN_SRLINUX_TRANSPORT` env var — values `cli` (default) or `gnmi`.
Executor dispatch picks from `_VENDOR_EXECUTORS` keyed on `(platform,
transport)` tuple. Default stays `cli` so CI/tests unaffected.

### Files touched

| File | Change |
|---|---|
| `requirements.txt` | `pygnmi>=0.9,<1` |
| `src/ibn/agents/agent5_orchestration.py` | `_srlinux_gnmi_executor` + dispatch that honours `IBN_SRLINUX_TRANSPORT`; keep `_srlinux_ssh_executor` unchanged |
| `src/ibn/agents/_srlinux_yang.py` (new) | tiny CLI-line → gNMI `(path, value)` parser for the paths our templates emit |
| `tests/unit/test_t23_srlinux_gnmi.py` (new) | parser tests + executor dispatch tests (gNMI client monkey-patched) |
| `FIX_NOTES_Slice7a_gNMI_SRLinux.md` | post-slice notes |

### Verification

Unit: `test_t23_srlinux_gnmi.py` — all green.
Regression: Slice 1–5 suite (118/118) still green.

Live: `IBN_SRLINUX_TRANSPORT=gnmi` + HLD commit that toggles a VLAN on
DEV-HQ-ACC-01 → approve → confirm via
`docker exec clab-ibnlab-switches-acc-01 sr_cli "info from running /interface ethernet-1/1"`
that the change landed.

Verify TLS cert handling: SR Linux presents a self-signed cert from clab's
lab CA — client uses `skip_verify=True` for now (documented followup in 7b
to pin the clab CA).

### Acceptance

- [ ] A3 renders unchanged SR Linux CLI content
- [ ] When `IBN_SRLINUX_TRANSPORT=gnmi`, A5 pushes via `pygnmi` and
      config lands on the live container (verified with `sr_cli`)
- [ ] When `IBN_SRLINUX_TRANSPORT=cli` (default), behaviour is identical
      to Slice 5 (`docker exec sr_cli`)
- [ ] 118/118 existing tests still pass
- [ ] T23 tests pass (parser + dispatch)

## Non-goals

- FRR/VyOS via NETCONF — FRR has a `mgmtd` NETCONF frontend but it's
  not wired in the `ibn-frr:local` image; VyOS 1.4 has NETCONF but our
  pipeline bypasses it already via commit-scripts-over-SSH. Leaving as
  7b/future work.
- OpenConfig unified templates — requires nontrivial work to reconcile
  SR Linux's native YANG coverage with OpenConfig augments. 7c.
- gNMI streaming telemetry (Agent 6 subscriptions). 7d.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| TLS cert issues | `skip_verify=True` initially; pin clab CA in 7b |
| gNMI commit atomicity differs from sr_cli `commit now` | start with `SetRequest` (replace at subtree root); SR Linux does the commit; followup: explicit `commit` via vendor-ext if needed |
| Parser drift as templates evolve | parser is tied to the three known templates; unit tests cover each path |
| `pygnmi` pulls grpc binary wheel | already common dep; falls back to sdist on rare archs |
