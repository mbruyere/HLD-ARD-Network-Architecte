# Slice 2 — Multi-Vendor Rendering & First Switch Device

Date: 2026-04-11
Status: **DRAFT — awaiting operator approval before execution**
Plan reference: builds on [PLAN_Slice1_HLD_Pipeline.md](PLAN_Slice1_HLD_Pipeline.md)
Predecessor: [FIX_NOTES_Slice1_HLD_Pipeline.md](FIX_NOTES_Slice1_HLD_Pipeline.md)

## Goal of this slice

Slice 1 proved the **plumbing** of the HLD-driven loop on a single
device class (VyOS firewalls). Slice 2 proves the **multi-vendor**
plumbing by adding one switch OS to the running lab and showing that
**a single HLD edit propagates to both vendor classes**.

By the end of Slice 2 the operator can:

1. Edit the population VLAN table in `Enterprise_Campus_Network_HLD (1).md`
2. `git commit`
3. The post-commit hook fires the closed-loop pipeline (as in Slice 1)
4. Within ~30 seconds **both** the existing 4 VyOS firewalls **and** the
   newly-added Arista cEOS switch receive a config delta — the firewalls
   get a new firewall rule set, the switch gets the new VLAN provisioned
   on its access/trunk ports.
5. Neo4j shows a queryable audit trail across both vendor classes.

This is the slice where "multi-vendor closed loop" becomes a real claim,
not just an architecture statement.

## Vision alignment

The full operator vision is *"edit HLD, commit, the closed loop
reconciles reality."* Slice 1 made that real for one vendor; Slice 2
makes it real across vendors. Without Slice 2, the loop is technically
working but artificially scoped — any real network has multiple OS
families, and the proof of multi-vendor is a discrete capability that
the architecture either has or doesn't.

The HLD itself is already vendor-neutral (per the earlier audit, it
prescribes firewall behavior but names no specific OS). Slice 2 doesn't
require any HLD edits — the vendor choice happens at the rendering
layer, driven by Neo4j device properties, not by the HLD document.

## In scope for Slice 2

| # | Component | New / Modified | Description |
|---|---|---|---|
| 1 | New switch OS in the lab | new | One Arista cEOS node added to `topology_ibn_lab.yml` and `clab.yml`. Boots under containerlab on the existing ARM64+QEMU stack. |
| 2 | Neo4j seed extension | new | Re-seed adds an `acc-sw-01` Device node with `vendor="Arista"` and `platform="cEOS"`, linked to the existing HQ Site (not a FirewallPair). |
| 3 | A1 — L1 VLAN writer | modified | Agent 1's HLD ingestion phase now also creates `VLAN` (L1) nodes from population table rows, not just `Intent` (L4). VLANs land in CANDIDATE state alongside the Intents. Idempotent on `vlanId`. |
| 4 | A3 — non-firewall device query | modified | New Cypher query `_QUERIES["switches"]` returns devices with `deviceRole IN ['ACCESS_SWITCH','AGGREGATION_SWITCH']` joined to their site (not via `FirewallPair`). The existing `firewalls` query is unchanged. |
| 5 | A3 — vendor dispatch | modified | `_render_device(device, ctx)` selects a template chain by `device.platform`: `vyos` → existing `vyos_*.j2` chain; `cEOS` → new `eos_*.j2` chain. Dispatch table is data-driven (`_TEMPLATE_CHAINS` dict) so future vendors plug in without code changes. |
| 6 | New cEOS template chain | new | `firewall_pipeline/templates/eos_base.j2`, `eos_vlans.j2`, `eos_interfaces.j2`. Renders hostname, VLAN database from L1 VLAN nodes, trunk port config. No firewall rules — switches don't enforce L4 policy in this HLD. |
| 7 | A5 — vendor dispatch | modified | `Agent5Orchestration` gains a `VENDOR_EXECUTORS` map keyed on `device.platform`. Looks up the correct executor at deploy time. Existing VyOS executor stays as the default. |
| 8 | New cEOS SSH executor | new | `_eos_ssh_executor()` and `_eos_ssh_verifier()` in `agent5_orchestration.py`. Sends `enable\nconfigure terminal\n{config}\nend\nwrite memory` and verifies via `show running-config`. |
| 9 | Acceptance test | new | `tests/integration/test_slice2_multi_vendor.py` — synthesizes an HLD diff, runs the pipeline, asserts both VyOS Configuration nodes and the cEOS Configuration node landed in Neo4j with the right per-vendor content. |
| 10 | Lab startup script update | modified | `~/start-ibn-lab.sh` (or a sibling) needs to ensure the cEOS image is available on first run. |

## Out of scope for Slice 2 (deferred)

| Item | Slice |
|---|---|
| Provisioning new containerlab nodes from HLD edits (e.g. "add acc-sw-05") | **3** |
| What-If state and PR-based approval gate (real A4 Planning) | **4** |
| Removals from the HLD (population/device deletion path) | **4** |
| Parsing more of the HLD beyond the population table (zones, firewall rules in HLD §9, routing) | **5** |
| LLM-generated dialogue prompts (vs. the current hand-built multi-choice) | **5** |
| A second non-VyOS device class (e.g. Cisco IOS-XE for edge routers) | **6** |
| 802.1X / MAB / port-security from HLD §6 port-config sections | **6** |

## Architecture — what Slice 2 adds on top of Slice 1

```
                    Enterprise_Campus_Network_HLD (1).md
                              │  (operator edits VLAN table)
                              │  git commit
                              ▼
                    .git/hooks/post-commit  (Slice 1)
                              │
                              ▼
                ibn.pipeline.hld_commit  (Slice 1, unchanged)
                              │
        ┌─────────────────────┴────────────────────┐
        ▼                                          ▼
   A1 Ingestion (Slice 1+2)              [other agents unchanged]
   ── Slice 1 ──                                   │
   • parse VLAN table                              │
   • dialogue → Intent                             │
   ── Slice 2 ADDITIONS ──                         │
   • create L1 VLAN nodes                          │
     from population entries                       │
                              │                    │
                              ▼                    │
                       A2 Intent→Policy            │
                       (Slice 1, unchanged)        │
                              │                    │
                              ▼                    │
                       A3 Policy→Config            │
                       ── Slice 1 ──               │
                       • _QUERIES["firewalls"]     │
                       • VyOS template chain       │
                       ── Slice 2 ADDITIONS ──     │
                       • _QUERIES["switches"]      │
                       • vendor dispatch:          │
                         vyos → vyos_*.j2          │
                         cEOS → eos_*.j2           │
                              │                    │
                              ▼                    │
                       A5 Orchestration            │
                       ── Slice 2 ADDITIONS ──     │
                       • VENDOR_EXECUTORS map      │
                       • dispatch by platform      │
                              │                    │
                              ▼                    │
                       SSH push to:                │
                         clab-ibnlab-usf{1,2}      │  (VyOS, Slice 1)
                         clab-ibnlab-dmzfw{1,2}    │  (VyOS, Slice 1)
                         clab-ibnlab-acc-sw-01     │  (cEOS, Slice 2 NEW)
                              │                    │
                              ▼                    │
                       A7 Assessment ──────────────┘
                       (Slice 1, query already platform-agnostic)
```

## Data flow walkthrough — one concrete example

Operator adds a new population row to the HLD:

```diff
  | Operational Tech | 160 | 100-1000 | 20-200 | Med-High | AF32, EF | 0.1-0.5 Mbps |
+ | Lab Test Pop     | 191 | 5-20     | 2-10   | Standard | AF21      | 1-2 Mbps    |
```

Pipeline run:

1. **Hook fires** (Slice 1, unchanged).
2. **A1 parses the diff** → 1 added population (VLAN 191, "Lab Test Pop").
3. **A1 dialogue** → operator picks template (a) standard-corporate.
4. **A1 writes Intent** `INT-HLD-191` to L4 (as Slice 1).
5. **A1 (NEW) writes VLAN node** `VLAN-191 {vlanId: 191, name: "Lab Test Pop", modelState: CANDIDATE, origin: "HLD:..."}` to L1.
6. **A2 writes Policy + 5 FirewallRules** for INT-HLD-191 (as Slice 1).
7. **A3 fires** with the new dispatch logic:
   - Loads firewalls via `_QUERIES["firewalls"]` → 4 VyOS devices
   - Loads switches via the new `_QUERIES["switches"]` → 1 Arista cEOS device
   - For each firewall: vendor=`vyos` → renders the existing 4-template VyOS chain → 4 Configuration nodes (these now include VLAN 191 in the zone-pair rules — no behavioral change, just new rules)
   - For the cEOS switch: vendor=`cEOS` → renders the new 3-template eos_* chain → 1 Configuration node containing `vlan 191 / name LAB-TEST-POP / interface Ethernet1 / switchport mode trunk / switchport trunk allowed vlan add 191`
   - **Total: 5 Configuration nodes, 2 vendor classes.**
8. **A5 fires** with the new dispatch logic:
   - For each Configuration node, looks up `device.platform` → finds the right executor
   - VyOS configs go through `_default_ssh_executor` (existing)
   - cEOS config goes through `_eos_ssh_executor` (new)
   - SSH push happens against the live containerlab containers
9. **A7 assesses** all 5 deployments (existing code, no platform-specific logic needed for the assessment itself in this slice).
10. **Pipeline complete.** Operator sees one summary block in the hook log.

## Why Arista cEOS

| Option | Pros | Cons |
|---|---|---|
| **Arista cEOS** (chosen) | (a) Already in the seed schema as `Arista EOS 7050`. (b) Real enterprise relevance. (c) Native containerlab `kind: ceos`. (d) Same QEMU+amd64 emulation pattern the operator already uses for VyOS. (e) Single-container, no extra infra. | (a) Image is ~1.5 GB. (b) Boot under QEMU on ARM64 is slow (~2 min). (c) Requires Arista account to download the image (one-time per host). |
| Nokia SR Linux | (a) Native ARM64 image, fast boot. (b) Modern NOS. | (a) Doesn't match the seed (`Arista EOS`). (b) Less common in legacy enterprise — feels like a step away from the HLD. (c) Would force a re-seed of device.platform values. |
| FRR on Alpine | (a) Instant boot. (b) Tiny image. | (a) Not a real enterprise NOS. (b) No L2 switching (VLAN provisioning awkward). (c) Doesn't honor the HLD intent that says "Arista" or "Cisco". |

**Recommendation: Arista cEOS.** It matches the HLD design, the
operator already has a working ARM64+QEMU pipeline for VyOS, and the
slow boot is a one-time cost that doesn't affect day-2 operations
(the container persists across HLD commits). If the operator wants a
faster iteration cycle, **SR Linux** is the second-best option — say
so before approval and I'll swap.

## Work breakdown — execution order

The order matters because some tasks depend on others. Tasks 1–2 are
infrastructure prerequisites that can run while we build the code.

1. **Pull cEOS image and validate boot**
   - Pull `ceos:latest` (or whatever tag the operator has access to) into local Docker
   - Add the image to a one-line Compose snippet so it's reproducible
   - Boot a single throwaway cEOS node via `containerlab` to confirm it runs on this host
   - Time-box: if the image isn't available or won't boot in ~5 min, swap to SR Linux without further ceremony

2. **Extend topology_ibn_lab.yml + clab.yml**
   - Add `acc_sw_01` node to `topology_ibn_lab.yml` under a new group `access_pair`
   - Add the corresponding clab block (kind=ceos, image, mgmt-ipv4)
   - Re-deploy the lab via `~/start-ibn-lab.sh` and verify all 11+1 containers are up

3. **Extend Neo4j seed**
   - Add `DEV-HQ-ACC-01` to the seed script with `vendor="Arista"`, `platform="cEOS"`, `deviceRole="ACCESS_SWITCH"`, `modelState="POR"`, linked to HQ site (not via FirewallPair)
   - Re-run the seed; verify the new device shows up

4. **A1 — write L1 VLAN nodes from HLD**
   - Add a `_create_vlan_node()` helper that writes a `VLAN {vlanId, name, modelState, origin}` node alongside each Intent
   - Idempotent on `vlanId` (MERGE)
   - Live-Memory note added so the audit trail captures the L1 write

5. **A3 — new switches query**
   - Add `_QUERIES["switches"]` returning devices with `deviceRole IN ['ACCESS_SWITCH','AGGREGATION_SWITCH']` joined to their site
   - Returns the same column shape as the firewalls query (`device_id`, `hostname`, `vendor`, `platform`, `device_role`, `site_id`, `site_name`) so downstream rendering can treat both lists uniformly

6. **A3 — vendor dispatch**
   - Replace `_DEFAULT_TEMPLATE_CHAIN` with a `_TEMPLATE_CHAINS = {"vyos": [...], "cEOS": [...]}` dict
   - `_render_device()` looks up the chain by `device.get("platform")` (case-insensitive)
   - Falls back to a stub if the platform is unknown (logged + live_noted)
   - The `_build_context()` method now returns both `firewalls` and `switches` lists; `_execute()` iterates the union

7. **cEOS template chain — new files**
   - `eos_base.j2`: hostname, mgmt interface, NTP, AAA stubs
   - `eos_vlans.j2`: iterate L1 VLAN nodes, render `vlan <id> / name <name>`
   - `eos_interfaces.j2`: trunk port stub on Ethernet1 carrying all populations + the management VLAN
   - All three are deliberately minimal — Slice 2 proves the rendering path; Slice 5 will add 802.1X, port-security, etc.

8. **A5 — vendor dispatch**
   - Add `_VENDOR_EXECUTORS = {"vyos": _default_ssh_executor, "cEOS": _eos_ssh_executor}` and matching `_VENDOR_VERIFIERS`
   - Resolve at push time from `device.platform` (or from a `platform` field passed in the plan step)
   - Constructor still accepts the `ssh_executor` / `ssh_verifier` overrides for tests

9. **cEOS SSH executor**
   - Sends: `enable`, `configure terminal`, `<config block>`, `end`, `write memory`
   - Username: `admin` (default for cEOS, configurable via env var)
   - Verifier: runs `show running-config` and computes a hash
   - On-failure rollback: same pattern as VyOS — reapply previous Configuration node content

10. **Acceptance test**
    - `tests/integration/test_slice2_multi_vendor.py`
    - Synthesizes an HLD diff (one new population), runs the pipeline directly (mocking the dialogue)
    - Asserts:
      - Both `firewalls` and `switches` Configuration nodes were written
      - The cEOS Configuration content contains `vlan <new_vlan>`
      - At least one VyOS Configuration content contains the new firewall rule
      - The L1 VLAN node was created and linked to the Intent's origin
    - Marked `@requires_real_infra` (Neo4j + Live-Memory + lab)

11. **Update CLAUDE.md status table** — Phase 1 / Phase 2 checkboxes that this slice unblocks (multi-vendor A3, A5)

12. **Commit + write FIX_NOTES_Slice2_Multi_Vendor.md** following the convention

## Acceptance criteria

Slice 2 is **done** when all of these are true:

1. The cEOS container is running in the lab alongside the 4 VyOS firewalls
2. The Slice 2 acceptance test passes against real infrastructure
3. Editing the HLD population table, committing, and watching the hook log shows the pipeline rendering configs for **both** vendor classes (5 Configuration nodes per HLD edit, not 4)
4. The cEOS-rendered Configuration content actually appears on the live cEOS container after `show running-config` (queried via SSH or `docker exec`)
5. Idempotency holds: re-committing the same HLD produces no new Configuration nodes for either vendor
6. The Slice 1 acceptance test still passes (no regressions)
7. Slice 2 is documented in `FIX_NOTES_Slice2_Multi_Vendor.md`

## Decisions deferred to later slices

Same as Slice 1's deferred list, plus:

- **A second non-firewall device class** (Cisco IOS-XE for the edge routers in the seed) → Slice 6
- **L2 access port-by-port assignment** (which physical ports belong to which population VLAN) → Slice 5
- **802.1X / MAB / port security on switches** (HLD §6.x sections) → Slice 6

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| **cEOS image not available on this host / requires Arista account** | Detected in Task 1. If pulling fails, swap to SR Linux without rewriting Slices 2+. The vendor dispatch architecture is OS-agnostic. |
| **cEOS QEMU boot is too slow for the inner-loop cycle time** | Container persists across HLD commits — boot is a one-time cost. If boot exceeds 5 min, document and accept it for now (the inner loop is async). |
| **A3's existing `firewalls` query depends on `FirewallPair` joins; switches need a different query path** | Explicit Slice 2 task. The new `switches` query is additive — the existing query path is untouched, so VyOS rendering stays exactly as it works today. |
| **Operator forgets to re-seed Neo4j after extending the lab** | Add a one-line check in `hld_commit.py` that warns if a lab device exists in clab but not in Neo4j (deferred — Slice 3 covers device provisioning properly). |
| **A2's hand-coded access matrix produces firewall rules but switches need VLAN provisioning, not rules** | Confirmed in the audit: switch templates render from L1 VLAN nodes, not from L4 FirewallRule nodes. The two artifact paths coexist in A3's render step. |
| **Neo4j seed migration may break existing data** | Use MERGE everywhere; the seed extension is additive, not destructive. Existing devices keep their properties. |
| **The new switch may not have any populated interfaces, so the rendered config is just hostname + VLANs** | That is exactly the goal of Slice 2 — prove the *path*. Slice 5 adds the per-port policy assignment. |
| **A real cEOS device pushes config via eAPI/JSON-RPC, not raw SSH like VyOS** | Slice 2 ships the SSH path (matches the existing A5 pattern). eAPI is a Slice 6 enhancement. SSH on cEOS is supported and correct, just less idiomatic. |

## Open questions for the operator before execution starts

Three decisions to confirm before I start Task 1:

1. **Switch OS choice.**
   - **(a) Arista cEOS** (recommended; matches the HLD seed)
   - **(b) Nokia SR Linux** (faster boot, doesn't match the seed, would force a re-seed of `device.platform` values)
   - **(c) Other** — name it and I'll adapt

2. **Lab scope.**
   - **(a)** Add **one** access switch (smallest footprint, fastest to boot, proves the multi-vendor path)
   - **(b)** Add **two** access switches as an HA pair (matches the HLD's HA pattern but doubles the boot time and the seed work)
   - I recommend (a) for Slice 2 and adding HA in Slice 6 alongside other enrichment.

3. **Vendor authentication on the new image.**
   - cEOS requires an Arista account to download. **Do you have one?** If not, I can either (i) check if there's a free `ceos-lab` image we can use (Arista does publish lab variants), or (ii) swap to SR Linux which is freely available.

Once you answer those, I'll set Task 1 to in_progress and start.
