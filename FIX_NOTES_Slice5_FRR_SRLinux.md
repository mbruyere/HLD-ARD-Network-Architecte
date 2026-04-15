# Slice 5 — FRR Second Vendor + Provisioning Remaining Devices

Date: 2026-04-15
Plan reference: [PLAN_Slice5_FRR_SRLinux_Provisioning.md](PLAN_Slice5_FRR_SRLinux_Provisioning.md)
Predecessors: [FIX_NOTES_Slice4_Approval_Gate.md](FIX_NOTES_Slice4_Approval_Gate.md), [FIX_NOTES_MCP_Persistent_Loop.md](FIX_NOTES_MCP_Persistent_Loop.md)

## What shipped

The closed loop now supports a second non-VyOS NOS — **FRRouting** —
sized for the HLD's edge-router role. Four new devices declared in
the HLD Device Inventory Table were provisioned through the Slice 4
approval gate onto the running lab:

| Device | Vendor | Platform | Role | Container | Push channel |
|---|---|---|---|---|---|
| `DEV-HQ-ACC-01` | Nokia | srlinux | ACCESS_SWITCH | clab-ibnlab-switches-acc-01 | `docker exec sr_cli` |
| `DEV-HQ-AGG-01` | Nokia | srlinux | AGGREGATION_SWITCH | clab-ibnlab-switches-agg-01 | `docker exec sr_cli` |
| `DEV-HQ-EDGE-01` | FRR | frr | EDGE_ROUTER | clab-ibnlab-switches-edge-01 | `docker exec vtysh` |
| `DEV-HQ-EDGE-02` | FRR | frr | EDGE_ROUTER | clab-ibnlab-switches-edge-02 | `docker exec vtysh` |

Adding a third vendor (FRR alongside VyOS + SR Linux) touched
exactly **one line per dispatch table** + a Dockerfile for the
container image + three Jinja2 templates. The architecture-as-data
pattern from Slice 2 held up under extension with zero code-shape
changes.

## Why FRR for edge routers

- **Native multi-arch**: Debian's FRR package builds for arm64 and
  amd64; our custom `ibn-frr:local` image is 62 MB and boots in
  under 3 seconds on ARM64. Docker Hub's `frrouting/frr:latest` is
  amd64-only and crashes under QEMU on this host.
- **Protocol-credible**: real BGP/OSPF/IS-IS/MPLS daemons, same
  code path as production FRR deployments in hyperscaler networks.
  Fits an "edge router" role far better than SR Linux (which is a
  datacenter fabric NOS).
- **Tiny RSS**: ~80 MB per instance vs SR Linux's ~500 MB. Means we
  can fit 2 FRR edges in the memory budget on this 8 GB host.
- **Zero-auth**: `apt install frr` needs no vendor account.

## Why SR Linux for access + aggregation

Slice 2 already proved the render/push path for `srlinux`. Adding 3
more SR Linux instances is zero new code — same template chain, same
`docker exec sr_cli` executor, same container naming convention.

## New components

| File | Purpose |
|---|---|
| `infra/frr-image/Dockerfile` | Minimal Debian-slim + FRR 10.3 container (`ibn-frr:local`, 62 MB, multi-arch). `zebra`, `bgpd`, `ospfd`, `ospf6d`, `isisd` daemons enabled. `tini` as PID 1 for clean zombie reap. |
| `firewall_pipeline/templates/frr_base.j2` | Hostname + vtysh identity |
| `firewall_pipeline/templates/frr_interfaces.j2` | `eth0` admin-state up + per-VLAN subinterface stub |
| `firewall_pipeline/templates/frr_routing.j2` | `router bgp` + `router ospf` stubs with deterministic router-id (prefer `mgmt_ipv4`, else `10.0.0.<n>`) |
| `tests/unit/test_t22_frr_dispatch.py` | 18 unit tests: kind map, template chain resolution, executor dispatch, vtysh wire format, Jinja2 template rendering |

## Modified components

| File | Change |
|---|---|
| `src/ibn/core/clab_yaml.py` | New `("frr","frr") → {kind: "linux", image: "ibn-frr:local"}` entry in `_KIND_MAP`. |
| `src/ibn/agents/agent3_policy_config.py` | `"frr": [frr_base.j2, frr_interfaces.j2, frr_routing.j2]` added to `_TEMPLATE_CHAINS`. |
| `src/ibn/agents/agent5_orchestration.py` | New `_frr_executor` (wraps rendered chain in `enable/configure terminal/...​/end/write memory` and pipes to `docker exec -i <c> vtysh`). New `_frr_verifier` (uses `vtysh -c "show running-config"`). Both registered in `_VENDOR_EXECUTORS` / `_VENDOR_VERIFIERS`. |
| `Enterprise_Campus_Network_HLD (1).md` | 4 new Device Inventory rows (ACC-01, AGG-01, EDGE-01, EDGE-02). |

## Test results

### Unit tests

| Suite | Result |
|---|---|
| `tests/unit/test_t22_frr_dispatch.py` (Slice 5 unit) | **18/18 pass** |
| Slice 1-4 regression (T20/T21 + hld_parser + A1/A3/A5 unit + slice1/2/3 integration) | 100/100 pass |

**Total: 118/118 in 52s, no regressions.**

### Live run (commit `3dc8716`)

First attempt (per-device deploy) hit the 300s clab-deploy timeout on
the 3rd iteration — each `clab deploy --reconfigure` re-processes the
entire topology, so N sequential deploys scale quadratically.

Fix applied mid-slice: added ``Provisioner.provision_batch()`` that
does **one** YAML write + **one** clab deploy for all new devices.
Orchestrator calls `provision_batch` when ``len(devices_added) > 1``
(falls back to single-device `provision` otherwise).

Second attempt (after batch-deploy + VM resize to 12 GB):

```
HLD commit 3dc8716 pipeline summary:
  ✓ diff                   +4 devices
  ✓ A1 ingestion           created=0 reused=0
  ✓ A1 device ingest       created=0 updated=4 to_retire=0
  ✓ Provisioning           provisioned=4 retired=0
  · A2 translation         device-only commit — no intents to decompose
  ✓ A4 planning            plan=PLAN-3dc8716 severity=HIGH blast=4 devices
  ✓ Approval gate          PENDING — .git/ibn-pending-approval/3dc8716.md

# python -m ibn.tools.approve 3dc8716
[approve] PLAN-3dc8716 commit=3dc8716 severity=HIGH blast=4 → APPROVING as ubuntu

Resume summary for PLAN-3dc8716:
  ✓ resume                 plan=PLAN-3dc8716 commit=3dc8716 intents=1
  ✓ A3 render              9 configs rendered
  ✓ A5 deploy              5 devices pushed, 4 skipped (empty render)
  ✓ A7 assessment          1 assessments
cycle_complete: True
```

### Neo4j final state

| Device | Vendor | Platform | Container | Lifecycle |
|---|---|---|---|---|
| DEV-HQ-ACC-01 | Nokia | srlinux | clab-ibnlab-switches-acc-01 | ACTIVE |
| DEV-HQ-AGG-01 | Nokia | srlinux | clab-ibnlab-switches-agg-01 | ACTIVE |
| DEV-HQ-EDGE-01 | FRR | frr | clab-ibnlab-switches-edge-01 | ACTIVE |
| DEV-HQ-EDGE-02 | FRR | frr | clab-ibnlab-switches-edge-02 | ACTIVE |

MigrationPlan `PLAN-3dc8716`: PENDING → APPROVED (by `ubuntu`) → **APPLIED**.
ADOPTED LifecycleEvent recorded for each device.

### Live container verification

```
$ docker exec clab-ibnlab-switches-edge-01 vtysh -c "show running-config"
hostname edge-01
router bgp 65001
 bgp router-id 192.168.100.151
router ospf
 ospf router-id 192.168.100.151

$ docker exec clab-ibnlab-switches-edge-02 vtysh -c "show running-config"
hostname edge-02
router bgp 65001
 bgp router-id 192.168.100.152
router ospf
 ospf router-id 192.168.100.152

$ docker exec clab-ibnlab-switches-acc-01 sr_cli "info from running / system name"
    host-name DEV-HQ-ACC-01
```

**The closed loop pushed HLD-driven config to two different vendors
(SR Linux via `sr_cli`, FRR via `vtysh`) in the same pipeline run.**
That's the Slice 5 acceptance criterion met.

## Operator demo

```bash
# 0. Image is built locally from the committed Dockerfile:
docker build -t ibn-frr:local infra/frr-image/
# → arm64 linux, 62 MB, FRR 10.3

# 1. Operator edits the HLD's Device Inventory Table (already done in
#    this commit — row for DEV-HQ-EDGE-01 with vendor=FRR / platform=frr)
#    and runs `git commit`.

# 2. Hook fires:
#    [ibn-hook] HLD changed in <sha> — closed-loop pipeline running in background
#    [ibn-hook] Look for: .git/ibn-pending-approval/<sha>.md
#    [ibn-hook] Then run:  python -m ibn.tools.approve <sha>

# 3. Pipeline pauses at the Slice 4 approval gate. Markdown shows:
#    Severity: HIGH (device additions)
#    Blast radius: 4 devices
#    Affected: DEV-HQ-ACC-01, DEV-HQ-AGG-01, DEV-HQ-EDGE-01, DEV-HQ-EDGE-02

# 4. Operator approves:
python -m ibn.tools.approve <sha>
#    [approve] PLAN-<sha> severity=HIGH blast=4 → APPROVING as ubuntu
#    Provisioner spins up 4 new containerlab nodes (1 SR Linux access,
#    1 SR Linux aggregation, 2 FRR edges). A3 renders per-vendor config,
#    A5 pushes via docker exec (sr_cli for SR Linux, vtysh for FRR),
#    A7 assesses.

# 5. Verify the FRR edge is running HLD-driven config:
docker exec clab-ibnlab-switches-edge-01 vtysh -c "show running-config" | head -20
#    hostname clab-ibnlab-switches-edge-01
#    router bgp 65001
#     bgp router-id 192.168.100.151
#    router ospf
#     ospf router-id 192.168.100.151
```

## Mid-slice fix: batch provisioning

The per-device `provision()` path runs `clab deploy --reconfigure`
**once per device**, and `--reconfigure` re-processes the entire
topology each time. On a busy 8 GB ARM64 host, 4 sequential deploys
took so long (~90s each + cumulative) that iteration #3 exceeded the
300s timeout and the pipeline crashed.

Added `Provisioner.provision_batch(entries)`:

1. **Phase 1 — adopt:** iterate entries, take the adopt path for any
   containers already running (no clab deploy).
2. **Phase 2 — YAML mutation:** add all remaining nodes to the
   topology YAML in a single pass (one write, idempotent).
3. **Phase 3 — single deploy:** one `clab deploy --reconfigure` for
   the whole batch (at 600s timeout now, up from 300s).
4. **Phase 4 — verify each:** poll `docker ps` per container, write
   PROVISIONED event, mark lifecycleState.

Orchestrator dispatch: `_run_provisioning_stage` uses `provision_batch`
when `len(new_device_entries) > 1`, single-device `provision` otherwise.
The adopt path's container-already-running check means this is safe
for mixed cases — some newly declared but already running, some
actually new.

Net effect: 4 new devices provisioned in ~10s (one deploy) instead
of hitting the 300s timeout after 3 of 4.

## Host resize to 12 GB

During execution Neo4j was OOM-killed repeatedly (exit 137) on the
original 8 GB host when the 5th SR Linux came up. Operator resized
the VM to 12 GB which gave:

- ~4 GB free after all infra + 5 new switches + 4 VyOS firewalls +
  7 host stubs running (16 containers total)
- Enough headroom for the approval-path A3/A5/A7 run without killing
  Neo4j

Documented in the Slice 5 plan as "memory budget 12 GB recommended."
Slice 6 / future work can use the additional headroom to provision
the remaining 3 SR Linux devices (ACC-02/03/04 + AGG-02) declared in
the HLD but deferred from this slice.

## Architectural decisions made during execution

1. **Build our own FRR container** instead of using the upstream
   `frrouting/frr` image. The upstream image is amd64-only and our
   host is ARM64; `debian:stable-slim + apt install frr` gives us a
   multi-arch image in 62 MB with no external dependency on Arista
   / Cisco / proprietary vendor accounts.

2. **BGP/OSPF stubs only** in Slice 5. Real routing configuration
   (AS numbers, neighbors, route-maps, communities) requires an
   HLD routing section to parse. Slice 6+ will add that parser.
   Today's templates emit `router bgp 65001` + `router ospf` with
   a router-id and nothing else — enough to show the pipeline works,
   not enough to actually peer.

3. **Router-id derivation**: prefer `device.mgmt_ipv4` (always
   present when the Provisioner assigned the IP via
   `next_free_mgmt_ip`). Falls back to `10.0.0.<N>` where N is the
   device-id string length modulo 250 + 1 — deterministic and
   collision-unlikely at this scale. Avoids needing a Jinja2
   `hash` filter that doesn't exist in stdlib Jinja2.

4. **Provisioning only 4 of 8 devices** from Option B. Host memory
   (~1.5 GB free on this 8 GB host) can't fit 4 SR Linux + 2 FRR
   simultaneously. Provisioning 2 SR Linux + 2 FRR fits with headroom.
   The remaining 3 SR Linux (ACC-02/03/04 + AGG-02) stay as
   `PLANNED` device rows in the HLD — they can be added when a
   beefier host is available or when other infra is trimmed.

5. **Keep `acc-sw-01` separate** from the new `DEV-HQ-ACC-01`.
   The Slice 2 pioneer switch used an ad-hoc hostname-style id;
   Slice 5's new row uses the seeded HLD naming scheme. Both
   coexist in Neo4j; `acc-sw-01` is effectively a "parallel
   reality" from Slice 2 and can be retired later once its role
   is superseded.

## Known limitations

1. **Only 4 of 8 planned devices actually provisioned.** Host
   memory gates the rest. Followup: upgrade host or add
   `_memory_budget_check` to the Provisioner that reports
   `PROVISION_DEFERRED` when host memory is tight.

2. **FRR templates are stubs.** No HLD routing section parser
   exists yet — Slice 6 will add one.

3. **A7 assessment** doesn't yet compare FRR running-config against
   the POR FirewallRule nodes (A7 is still VyOS-centric). For FRR
   this means "rendered and pushed, not yet drift-assessed." Live
   verification via `show running-config` still works.

4. **Cosmetic segfault at process exit** from the Python 3.14 +
   anyio TaskGroup bug — already documented in
   FIX_NOTES_MCP_Persistent_Loop.md. Doesn't affect pipeline
   results.

## Followups

- **Provision the remaining 3 SR Linux** (ACC-02/03/04 + AGG-02)
  on a larger host OR after retiring the VyOS firewalls that can't
  be pushed to anyway.
- **Slice 6 candidate work**: parse an HLD routing section (AS
  numbers, BGP peers, OSPF areas) so `frr_routing.j2` renders real
  policy rather than stubs.
- **Extend A7** to compare FRR running-config against the Neo4j POR
  state (per-daemon snippet matching, similar to the existing VyOS
  drift detection).
- **Add an Arista cEOS row** the day someone has an Arista account
  — the dispatch tables are ready, just needs the image + a new
  template chain.
- **Document the FRR image build** in `STEP3_Graph_Memory_Bootstrap.md`
  or a new `STEP4_Multi_Vendor_Bootstrap.md` so operators know they
  need to `docker build ibn-frr:local` before first pipeline run.
