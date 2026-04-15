# Slice 5 — Second Vendor (FRR) + Provision the Remaining 6 Devices

Date: 2026-04-15
Status: **Approved — executing**
Predecessors: [PLAN_Slice4_Approval_Gate.md](PLAN_Slice4_Approval_Gate.md), [FIX_NOTES_MCP_Persistent_Loop.md](FIX_NOTES_MCP_Persistent_Loop.md)

## Goal

Close the residual SSoT↔lab gap by:

1. Adding **FRRouting** (FRR) as a second non-VyOS NOS in the pipeline — natural fit for the HLD's edge-router role.
2. Provisioning the 6 remaining seed devices (4 switches + 2 edges) via the HLD-driven loop so they match the running lab.

After Slice 5 the Neo4j SSoT will have 12 devices, all with live running containers and a clean audit trail of who provisioned them (netlab vs. the loop).

## Mapping

Per Option B from the earlier analysis:

| Seed deviceId | Role | New `vendor` | New `platform` | Container name |
|---|---|---|---|---|
| DEV-HQ-ACC-01 | ACCESS_SWITCH | Nokia | srlinux | clab-ibnlab-switches-acc-01 |
| DEV-HQ-ACC-02 | ACCESS_SWITCH | Nokia | srlinux | clab-ibnlab-switches-acc-02 |
| DEV-HQ-ACC-03 | ACCESS_SWITCH | Nokia | srlinux | clab-ibnlab-switches-acc-03 |
| DEV-HQ-ACC-04 | ACCESS_SWITCH | Nokia | srlinux | clab-ibnlab-switches-acc-04 |
| DEV-HQ-AGG-01 | AGGREGATION_SWITCH | Nokia | srlinux | clab-ibnlab-switches-agg-01 |
| DEV-HQ-AGG-02 | AGGREGATION_SWITCH | Nokia | srlinux | clab-ibnlab-switches-agg-02 |
| DEV-HQ-EDGE-01 | EDGE_ROUTER | FRR | frr | clab-ibnlab-switches-edge-01 |
| DEV-HQ-EDGE-02 | EDGE_ROUTER | FRR | frr | clab-ibnlab-switches-edge-02 |

(First 4 ACC rows overwrite the Slice 3 "acc-sw-01" entry via a re-seed — the pre-existing container will keep running and get adopted as `DEV-HQ-ACC-01`.)

## Why this mapping

- **Nokia SR Linux** for access + aggregation: already validated on this host (native ARM64, ~17s boot, ~500 MB RSS per instance), Slice 2 proved the render/push path. Adding 4 more instances of the same platform is zero code work; it just exercises the existing template chain + docker-exec executor.
- **FRR** for edge routers: real BGP/OSPF/IS-IS/MPLS support, ~50 MB RSS per instance, native ARM64 via a custom `debian:stable-slim + apt install frr` image we build ourselves. Slice 1-4 already has all the scaffolding (A3 template chains + A5 vendor dispatch + Provisioner `clab deploy`); this slice adds one entry per dispatch table.

## In scope

| # | Component | New / Modified | Description |
|---|---|---|---|
| 1 | `infra/frr-image/Dockerfile` | **new** | Minimal Debian-slim-based FRR container with preconfigured `frr.conf` skeleton (zebra, bgpd, ospfd enabled). ~100 MB image, native multi-arch. Published locally as `ibn-frr:local`. |
| 2 | `src/ibn/core/clab_yaml.py` | modified | Add `("frr","frr") → {kind: "linux", image: "ibn-frr:local"}` to `_KIND_MAP`. |
| 3 | `firewall_pipeline/templates/frr_*.j2` | **new** | FRR template chain: `frr_base.j2` (hostname), `frr_interfaces.j2` (interface admin state), `frr_routing.j2` (minimal BGP stub — router bgp + network statements from L1 Subnet nodes, best-effort if no subnets, just a router id). |
| 4 | `src/ibn/agents/agent5_orchestration.py` | modified | Add `_frr_executor` and `_frr_verifier` using `docker exec <container> vtysh -c "configure terminal ... end ... write memory"`. Register in `_VENDOR_EXECUTORS` / `_VENDOR_VERIFIERS`. |
| 5 | `src/ibn/agents/agent3_policy_config.py` | modified | Add `"frr"` entry to `_TEMPLATE_CHAINS`. |
| 6 | `tests/unit/test_t22_frr_dispatch.py` | **new** | Unit tests: FRR in kind map, FRR template chain resolved by `_resolve_chain("frr")`, FRR executor selected by `_resolve_executor("frr")`, FRR Jinja2 templates render cleanly with a synthetic device. |
| 7 | `Enterprise_Campus_Network_HLD (1).md` | modified | Device Inventory Table gains 8 rows (4 ACC + 2 AGG + 2 EDGE). The existing `acc-sw-01` row is kept for backward compat but marked as shadow — actual new rows use `DEV-HQ-ACC-01..04` IDs. |
| 8 | `FIX_NOTES_Slice5_FRR_SRLinux.md` | new | Final write-up with results. |

## Out of scope

- Real BGP/OSPF configuration (BGP AS numbers, peer definitions, route maps) — Slice 5 emits stubs. Slice 6+ can parse an HLD routing section.
- Arista cEOS support — still blocked by lack of Arista account.
- Cisco IOS-XE / NX-OS / Juniper / SONiC — additive in the same dispatch tables when needed.
- Scaling beyond the 8 GB lab host — if host memory can't accommodate all 6 new devices, some will stay `lifecycleState=PLANNED` until next provisioning attempt (A4 blast radius will reflect the gap).

## Architecture

Nothing structurally new — Slice 5 exercises the Slice 1-4 plumbing on a new vendor. The new FRR entries are a single row in each dispatch table:

```python
# _KIND_MAP  (clab_yaml.py)
("frr", "frr"): {"kind": "linux", "image": "ibn-frr:local"}

# _TEMPLATE_CHAINS  (agent3_policy_config.py)
"frr": ["frr_base.j2", "frr_interfaces.j2", "frr_routing.j2"]

# _VENDOR_EXECUTORS / _VENDOR_VERIFIERS  (agent5_orchestration.py)
"frr": _frr_executor / _frr_verifier
```

The Provisioner's `clab deploy` path handles adding/destroying FRR nodes identically to SR Linux (same `clab kind: linux` just different image). The adopt path from Slice 4.5 still works if an operator manually spun up an FRR container matching the declared name.

## Execution order

1. Probe: `docker run --arch linux/arm64 --rm debian:stable-slim apt-get install -y frr` smoke check (confirm ARM64 availability).
2. Write `infra/frr-image/Dockerfile` + build `ibn-frr:local`.
3. Add FRR to `_KIND_MAP` + unit test.
4. Write FRR Jinja2 templates + render smoke test against a fake Device dict.
5. Add FRR executor + verifier to A5 + wiring.
6. Unit tests for A3 template resolution and A5 executor resolution.
7. Add 8 rows to the HLD Device Inventory Table.
8. Commit the code + HLD.
9. Hook fires → Slice 4 gate → pending-plan markdown shows all 8 devices_added.
10. Approve via `python -m ibn.tools.approve <sha>`.
11. Provisioner spins up as many containers as memory allows — for each one:
    - YAML mutation (add node to `clab-ibnlab-switches.yml`)
    - `sudo containerlab deploy --reconfigure`
    - Container polled for readiness
    - Neo4j lifecycleState = PROVISIONED → ACTIVE after config push
12. A3 renders per-vendor config, A5 pushes each one (SR Linux via `docker exec sr_cli`, FRR via `docker exec vtysh`).
13. A7 assesses.
14. Verify: Neo4j matches lab, running configs reflect HLD VLANs (SR Linux) + FRR stub routing.
15. Commit + FIX_NOTES_Slice5_FRR_SRLinux.md.

## Memory budget

Host has ~1.5 GB free. Each SR Linux takes ~500 MB RSS, each FRR ~50 MB.

- Fit-all budget: 4×500 + 2×50 = 2100 MB → **doesn't fit all at once.**
- Realistic first-wave: 2 FRR (100 MB) + 2 SR Linux (1000 MB) = 1100 MB → fits with headroom.
- Remaining 2 SR Linux: provisioned on a later commit after other memory freed, or host upgrade.

The closed loop's declarative SSoT handles this naturally: HLD declares all 8 devices, Neo4j has all 8 as `PLANNED`/`ACTIVE`, the Provisioner provisions what it can and leaves the rest `PLANNED`. A7 will flag the gap as drift. When an operator re-runs (or a subsequent commit runs), the Provisioner completes.

## Acceptance criteria

- `ibn-frr:local` image builds and boots a container; `docker exec <c> vtysh -c "show version"` returns an FRR version string.
- `_resolve_chain("frr")` returns `["frr_base.j2", "frr_interfaces.j2", "frr_routing.j2"]`.
- `_resolve_executor("frr")` returns `_frr_executor` (not the VyOS fallback).
- Committing the HLD with 8 new rows triggers the Slice 4 approval gate with severity=HIGH (device additions).
- After approve, at least **2 FRR edge containers + 1 SR Linux switch** are live with HLD-driven config. (All 8 is the stretch goal; at least these 3 prove the two-vendor path.)
- Neo4j `MigrationPlan PLAN-<sha>` transitions PENDING → APPROVED → APPLIED.
- All Slice 1-4 regression tests still pass.
- New unit tests (T22) all pass.

## Known risks

| Risk | Mitigation |
|---|---|
| FRR container not native ARM64 | We're building it ourselves from `debian:stable-slim` which has apt packages for both arches; the build is arch-agnostic. |
| OOM during `clab deploy` (same as Slice 3 pain) | Deploy as many as fit; leave the rest PLANNED. Slice 4's per-stage error reporting will surface any partial provisioning. |
| FRR's `vtysh` doesn't play nice with `docker exec` | Alternative: write `/etc/frr/frr.conf` via `docker cp` and reload. Implementation falls back to this if vtysh fails. |
| A7 flags all new devices as NON_COMPLIANT because As-Built telemetry doesn't exist yet | Expected. Slice 5 doesn't collect telemetry; A7's INIT-state compliance = "configured, not yet probed". Slice 6+ adds proper monitoring. |

## Why this is "Slice 5" despite Slice 5 being originally reserved for a full HLD parser

The HLD parser extension is now naturally fed by Slice 5's work: the Device Inventory Table is the first place Slice 5 extends. If the user adds a routing section to the HLD later, FRR's template chain can consume it.

The full HLD parser remains a long-term Slice 6+ concern. Slice 5 delivers operational value today: the lab actually matches the declared network architecture.
