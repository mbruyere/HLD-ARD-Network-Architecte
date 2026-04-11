# Slice 3 — HLD-Driven Device Provisioning

Date: 2026-04-11
Status: **DRAFT — about to execute (operator approved 1.2.3.)**
Predecessors: [PLAN_Slice2_Multi_Vendor.md](PLAN_Slice2_Multi_Vendor.md), [FIX_NOTES_Slice2_5_Skipped.md](FIX_NOTES_Slice2_5_Skipped.md)

## Goal of this slice

Slice 1 made HLD edits drive *config* changes through the loop. Slice 2
made the rendering and push multi-vendor. **Slice 3 makes the operator
able to introduce entirely new devices into the network by editing the
HLD.** When the HLD adds a row to the device inventory section, the
closed loop will:

1. Detect the new device in the HLD diff
2. Allocate a containerlab node for it (mutate `clab-ibnlab-switches.yml`)
3. Deploy the new container
4. Seed the corresponding `Device` node in Neo4j with the right
   `vendor`, `platform`, `clabContainer`, `deviceRole`, and `Site` link
5. Render and push initial config to the new device
6. Verify the device is reachable and the config landed
7. Write a `DeviceProvisioned` lifecycle event to L8

When the HLD removes a device row (or marks it `DECOMMISSIONED`), the
loop performs the reverse: tear down the container, mark the Neo4j
device as `RETIRED`, archive its last known good config.

This is the slice where the operator can stand up a new branch site
just by editing markdown.

## Vision alignment

The operator's stated vision:

> The full spirit is that human operator write into the HLD do and
> from T0 of the life cycle of the network. The Close loop will do
> the step by step in the spirit of the referenced documents the
> translation with the impacted agent to update the SSoT and status
> of the network and the creation of the new type of devices and
> their configurations.

**T0 of the network lifecycle** — Slice 3 is the literal day-zero
story. Before Slice 3, the closed loop assumes devices already exist.
After Slice 3, the operator can start from an empty lab and have the
loop bring it up by parsing the HLD device inventory.

## In scope for Slice 3

| # | Component | New / Modified | Description |
|---|---|---|---|
| 1 | HLD parser extension | modified | Add a `parse_device_inventory()` function for the HLD's device-list section. We need to add a structured device-inventory table to the HLD first (or pick an existing section to use) — Slice 3 will define the schema. |
| 2 | `Device` data model | modified | Add `clabContainer`, `mgmt_ipv4`, `lifecycle_state`, `provisionedAt` fields. The `clabContainer` is what A5 uses for dispatch; the lifecycle_state moves through `PLANNED → PROVISIONED → ACTIVE → RETIRED`. |
| 3 | A1 — device ingest | modified | When the HLD parser returns a device-inventory delta, A1 creates / updates / retires `Device` nodes in Neo4j. Idempotent on `deviceId`. Each device gets a `LOCATED_AT` link to its Site. |
| 4 | New agent: A11 Provisioner (or extend A5) | new | Mutates `clab-ibnlab-switches.yml`, runs `containerlab deploy --reconfigure`, polls the new container until ready, writes a `DeviceProvisioned` (L8) event. We'll house this as a sub-module of A5 (`agent5_orchestration.provisioner`) so we don't need a brand-new agent slot — A5's responsibility per RFC 9315 §5.1.3 already includes "deploy" which logically covers infrastructure deploy. |
| 5 | `clab-ibnlab-switches.yml` writer | new | A small templater that reads the live containerlab YAML, adds/removes a node block, writes it back. Idempotent: a re-run with no changes leaves the file untouched. |
| 6 | A3 — handle new devices | modified | Already iterates `firewalls + switches`. After Slice 3 the new device gets picked up automatically because A1 wrote it to Neo4j. The only change A3 needs is to also accept a `clabContainer` field passing through to the orchestrator's plan step. |
| 7 | A5 — clabContainer dispatch | modified | Already dispatches by `platform`. Slice 3 adds a preference: if `step["clabContainer"]` is present, use it directly as the docker target instead of deriving via `_srlinux_container_for()`. Cleaner and faster, and unblocks the original Slice 2.5 deviceId-mismatch concern as a side effect for any device that ships with `clabContainer`. |
| 8 | Pipeline orchestrator | modified | Add a new "Stage 3.5 — Provisioning" between A2 and A3. Detects newly-added devices in the changeset, runs the provisioner, blocks A3 until the new container is reachable. Surfaces the result in the stage summary. |
| 9 | Decommission path | new | When the HLD removes a device, the loop calls the provisioner's `retire(device_id)` which: (a) tears down the clab node, (b) marks the Neo4j device `RETIRED`, (c) preserves the last `Configuration` node for archival. |
| 10 | Acceptance test | new | `tests/integration/test_slice3_provisioning.py` — synthesizes an HLD diff that adds AND later removes a device, asserts the lab container appeared then disappeared, the Neo4j Device transitioned through states, and a fresh HLD-driven config landed on the new device when it came up. |
| 11 | Update CLAUDE.md status | modified | Mark Slice 3 in the implementation status section. |

## Out of scope for Slice 3 (deferred)

| Item | Slice |
|---|---|
| What-If state and PR-based approval gate | **4** |
| Real A4 Planning (blast radius, migration sequencing) | **4** |
| Removals **with rollback** of a faulty device addition | **4** (needs the approval gate) |
| Parsing the rest of the HLD (zones, firewall policies, routing) | **5** |
| LLM-generated dialogue prompts for unstructured HLD prose | **5** |
| Adding a SECOND device class (e.g. Cisco IOS-XE) | **6** |
| Multi-site provisioning (not just HQ) | **6** |
| Lab firewall image swap so VyOS push works | **6** (or whenever the user prioritizes it) |

## Architecture — what Slice 3 adds

```
                    Enterprise_Campus_Network_HLD (1).md
                              │  (operator adds a device row)
                              │  git commit
                              ▼
                    .git/hooks/post-commit  (Slice 1)
                              │
                              ▼
                ibn.pipeline.hld_commit  (Slice 1+2+3)
                              │
        ┌─────────────────────┴────────────────────┐
        ▼                                          ▼
   A1 Ingestion (Slice 1+2+3)             [other agents]
   ── Slice 1 ──
   • parse VLAN table → Intent
   ── Slice 2 ──
   • create L1 VLAN nodes
   ── Slice 3 ADDITIONS ──
   • parse device inventory table
   • create / update / retire Device nodes
   • emit DEVICE_ADDED / DEVICE_REMOVED events
                              │
                              ▼
                       A2 Intent→Policy
                       (unchanged)
                              │
                              ▼
                   ┌─────────────────────────────┐
                   │  Stage 3.5 — Provisioning   │  ← NEW IN SLICE 3
                   │  (A5.provisioner submodule) │
                   │                              │
                   │  For each DEVICE_ADDED:      │
                   │   1. mutate clab YAML        │
                   │   2. clab deploy             │
                   │   3. wait for container up   │
                   │   4. write DeviceProvisioned │
                   │      (L8) event              │
                   │                              │
                   │  For each DEVICE_REMOVED:    │
                   │   1. mark Neo4j device       │
                   │      lifecycle=RETIRED       │
                   │   2. archive configs         │
                   │   3. mutate clab YAML        │
                   │   4. clab destroy node       │
                   └─────────────────────────────┘
                              │
                              ▼
                       A3 Policy→Config
                       (now sees new device via the
                        switches/firewalls queries)
                              │
                              ▼
                       A5 Orchestration
                       (uses clabContainer if present)
                              │
                              ▼
                       A7 Assessment
```

## Data flow walkthrough — one concrete example

Operator wants to add a new branch access switch. They edit
`Enterprise_Campus_Network_HLD (1).md` and add a row to the (newly
created) **Device Inventory Table**:

```diff
  | acc-sw-01 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-01 |
+ | acc-sw-02 | Nokia | srlinux | ACCESS_SWITCH | HQ | clab-ibnlab-switches-acc-sw-02 |
```

Pipeline run on `git commit`:

1. **Hook fires** (Slice 1, unchanged).
2. **A1 parses the diff** → 1 added device. (No population changes,
   so A1's existing Intent path doesn't fire — only the new device path.)
3. **A1 (NEW) creates Neo4j Device node** `acc-sw-02` with
   `vendor="Nokia", platform="srlinux", deviceRole="ACCESS_SWITCH",
   clabContainer="clab-ibnlab-switches-acc-sw-02", lifecycleState="PLANNED",
   modelState="POR", origin="HLD:...:line"`. Linked to HQ Site.
4. **A1 (NEW) emits a `DEVICE_ADDED` event** with the device payload.
5. **A2 runs** — no Intent changes, nothing to translate. (Slice 5 will
   eventually wire device additions to default policy templates; for
   Slice 3 this is a no-op.)
6. **Stage 3.5 — Provisioning runs** for the first time:
   - Reads `clab-ibnlab-switches.yml`
   - Adds an `acc-sw-02` block under `topology.nodes`
   - Allocates `192.168.100.122` as the next free IP in the range
   - Writes the file back
   - Runs `sudo containerlab deploy -t /tmp/clab-ibnlab-switches.yml --reconfigure`
   - Polls `docker ps` until `clab-ibnlab-switches-acc-sw-02` is up
     (timeout 60s; SR Linux native ARM64 boots in ~17s)
   - Writes `DeviceProvisioned {deviceId, eventType: PROVISIONED,
     timestamp, lab: ibnlab-switches}` to Neo4j L8
   - Updates Device.lifecycleState to `PROVISIONED`
7. **A3 fires** with the new device in scope. The `switches` query
   returns 2 SR Linux devices now. Each gets the same VLAN/interface
   render (since they share the L1 VLAN list). 2 Configuration nodes
   for the SR Linux platform plus the existing firewall renders.
8. **A5 fires** with vendor dispatch. Both SR Linux devices get pushed
   via `docker exec sr_cli`. The new device picks up all 17 existing
   HLD VLANs immediately.
9. **A7 assesses** — the new device's running config matches the
   rendered POR config = COMPLIANT.
10. **Pipeline summary** shows: provisioning=1 added, A3=14 configs
    rendered (was 13), A5=2 devices pushed, 12 skipped.

The operator did one HLD edit and one `git commit`. Within ~30 seconds
they have a brand new running access switch, fully configured with the
HLD's VLAN topology, with the audit trail visible in Neo4j.

## Why house the Provisioner in A5 instead of creating an "A11"

RFC 9315 §5.1.3 places "Deploy / Orchestration" as Agent 5's job. The
RFC text talks about deploying *configuration* but the closed loop's
abstraction holds: A5's job is making the network reflect the model.
Spinning up a container and pushing config to it are both "make
reality match the model" actions. Splitting them across two agents
would invent a coordination problem we don't need.

Concretely: A5 gets a `provisioner` submodule with two methods —
`provision(device)` and `retire(device)`. The orchestrator calls these
explicitly between A2 and A3. The existing A5 push path stays exactly
as-is.

This is the same pattern we used for vendor dispatch in Slice 2 —
data-driven, additive, no new agent IDs to invent.

## Work breakdown — execution order

1. **Define a structured Device Inventory Table in the HLD.** Add a
   new `### Device Inventory` section under `Appendix B: Reference Tables`
   with columns: `Device ID | Vendor | Platform | Role | Site |
   Container | Mgmt IP`. Pre-populate it with the devices that already
   exist (the 4 VyOS firewalls + the SR Linux switch + maybe the seed
   Cisco devices, marked as `lifecycle: planned`). Idempotency relies
   on this being a real markdown table the parser can re-read on every
   commit.

2. **HLD parser extension** ([src/ibn/parser/hld_parser.py](src/ibn/parser/hld_parser.py))
   - `parse_device_inventory(markdown_text) → list[DeviceEntry]`
   - `DeviceEntry` dataclass: `device_id, vendor, platform, role, site,
     clab_container, mgmt_ipv4, line_number`
   - Update `parse_hld()` and `HldSnapshot` to include the device list
   - Update `diff_snapshots()` to compute `devices_added/modified/removed`
   - Unit tests for parsing + diff

3. **Data model extensions** ([src/ibn/core/models.py](src/ibn/core/models.py))
   - Add `Device` dataclass (none currently exists — devices are written
     via raw Cypher in tests/seeds). Fields: `deviceId, hostname, vendor,
     platform, deviceRole, siteId, clabContainer, mgmtIpv4, lifecycleState,
     modelState, origin, createdAt`
   - Add `LifecycleEvent` dataclass for L8: `eventId, deviceId, eventType,
     fromState, toState, timestamp, payload`
   - `DeviceLifecycleState` enum: `PLANNED, PROVISIONED, ACTIVE, DEGRADED, RETIRED`

4. **Neo4jClient writers** ([src/ibn/core/neo4j_client.py](src/ibn/core/neo4j_client.py))
   - `create_device(device)` — MERGE on deviceId, sets all fields, links
     to Site via LOCATED_AT
   - `update_device_lifecycle(device_id, new_state)`
   - `retire_device(device_id)` — sets lifecycleState=RETIRED, doesn't delete
   - `create_lifecycle_event(event)` — writes L8 LifecycleEvent node
   - `get_device_by_clab_container(name)` — used by the provisioner to
     check if a container is already known

5. **A1 — device ingest path** ([src/ibn/agents/agent1_ingestion.py](src/ibn/agents/agent1_ingestion.py))
   - New `ingest_hld_devices(changeset, source_path, ...)` method
   - For each added/modified `DeviceEntry`, calls `create_device()`
   - Emits `device.added` / `device.modified` / `device.removed` events
   - `live_note()` to `ibn-candidate-001` for each
   - **Important**: this is called from the orchestrator alongside the
     existing `ingest_hld_changeset()` (population path), not nested

6. **Provisioner** (new file `src/ibn/agents/provisioner.py`)
   - Class `Provisioner(neo4j, live_memory)` — not a BaseAgent, just a
     helper module
   - `provision(device_entry) → ProvisionResult`:
     1. Mutate the right clab YAML (router via vendor → which lab file)
     2. Run `containerlab deploy` (subprocess, captured)
     3. Poll `docker ps` until container present + healthy
     4. Write `LifecycleEvent` to L8
     5. Update `Device.lifecycleState`
   - `retire(device_id) → RetireResult` — symmetric, archives last config
   - `current_clab_topology(yaml_path)` and `write_clab_topology(yaml_path, dict)`
     helpers

7. **clab YAML mutation helper** (new module `src/ibn/core/clab_yaml.py`)
   - `add_node(yaml_dict, node_name, kind, image, mgmt_ip, **opts)`
   - `remove_node(yaml_dict, node_name)`
   - `next_free_mgmt_ip(yaml_dict, subnet)` — picks the first unused IP
     in `192.168.100.0/24` excluding the existing nodes
   - Uses `ruamel.yaml` (round-trip, comments preserved) if available,
     falls back to `yaml` (PyYAML) which loses comments
   - Unit tests with synthetic YAML strings (no real lab needed)

8. **A5 — clabContainer dispatch** ([src/ibn/agents/agent5_orchestration.py](src/ibn/agents/agent5_orchestration.py))
   - In `_execute()`, prefer `step["clabContainer"]` over `step["deviceId"]`
     when present
   - In `_srlinux_ssh_executor()`, accept either a container name passed
     directly or fall back to the existing derivation
   - No vendor dispatch changes — Slice 2's table already handles platform

9. **A3 passes clabContainer through** ([src/ibn/agents/agent3_policy_config.py](src/ibn/agents/agent3_policy_config.py))
   - Add `d.clabContainer AS clab_container` to both `firewalls` and
     `switches` queries
   - Add `clabContainer` to the per-device result dict
   - Orchestrator reads it from the result and stuffs it into the plan step

10. **Pipeline orchestrator** ([src/ibn/pipeline/hld_commit.py](src/ibn/pipeline/hld_commit.py))
    - New `_run_provisioning_stage()` between A2 and A3
    - Reads `changeset.devices_added/removed` from the parser
    - Loops through, calls `Provisioner.provision()` / `retire()` per device
    - Adds a `provisioning` stage to the StageResult list
    - Continues to A3 only after all provisioning has settled (or after a
      timeout that marks the stage as warning)

11. **Decommission path** — covered by Provisioner.retire()

12. **Acceptance test** ([tests/integration/test_slice3_provisioning.py](tests/integration/test_slice3_provisioning.py))
    - Synthesizes an HLD diff that adds `acc-sw-02`
    - Runs the pipeline directly
    - Asserts:
      - `clab-ibnlab-switches-acc-sw-02` container exists in `docker ps`
      - Neo4j Device(`acc-sw-02`) exists with lifecycleState=ACTIVE
      - L8 LifecycleEvent for the addition exists
      - SR Linux running config on the new container has all 17 HLD VLANs
    - Then a second diff that removes `acc-sw-02`
    - Asserts:
      - Container is gone
      - Neo4j Device lifecycleState=RETIRED
      - Last Configuration node still queryable
    - `@requires_real_infra` and `@requires_containerlab`

13. **Update CLAUDE.md** Implementation Status table to reflect Slice 3.

14. **Commit + write FIX_NOTES_Slice3_Device_Provisioning.md**

## Acceptance criteria

Slice 3 is **done** when:

1. The operator can edit the HLD's Device Inventory Table to add a new
   row, run `git commit`, and within 60 seconds:
   - A new containerlab node is running with the right name
   - A Neo4j Device exists with lifecycleState=ACTIVE
   - The L1 VLANs from the HLD are provisioned on the new device
   - The L8 LifecycleEvent records the addition with operator/timestamp
2. The same edit reverted (row removed) tears the container down and
   marks the Device as RETIRED
3. Re-committing the same diff is a no-op (idempotency)
4. Slice 1 and Slice 2 acceptance tests still pass (no regressions)
5. The Slice 3 acceptance test passes
6. `FIX_NOTES_Slice3_Device_Provisioning.md` is committed

## Decisions deferred to later slices

Same as Slice 2's deferred list, plus:

- **Multi-site provisioning** — Slice 3 only provisions to the HQ site
  with a single clab YAML. Branch/multi-site goes to Slice 6.
- **Per-vendor template scaffolding on first provisioning** — when a
  brand new platform is added (no existing Jinja2 templates), the
  loop should fail loudly. Slice 6 will add a "platform support
  matrix" check that surfaces the gap.
- **Approval before provisioning** — Slice 4 adds the PR-based gate.
  Slice 3 auto-provisions on commit.

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| `clab deploy` requires `sudo` and the post-commit hook runs as the operator | The hook already runs `sudo containerlab` for the firewall lab during the original Slice 2 lab bring-up. Use the same pattern. The provisioner uses `sudo -n` (non-interactive); if it fails, the operator gets a clear error in the hook log. |
| The clab YAML lives in `/tmp` (per the 9p filesystem workaround) but the source-of-truth lives in the repo | Provisioner reads from the repo, mutates a copy in `/tmp`, runs deploy from `/tmp`, then writes the mutated version back to the repo on success. Both files end up in sync. |
| Adding a device whose `platform` has no template chain in A3 silently produces empty configs | A3 already logs a warning. Slice 3 makes A1 also warn at ingestion time if `platform` is unknown. Slice 6 will fail-loud. |
| Provisioning a device with a pre-used `mgmt_ipv4` collides with the live lab | `next_free_mgmt_ip()` reads the live YAML before allocating. |
| A `clab deploy --reconfigure` rebuilds the entire topology, killing existing containers | Use `--node-filter` to deploy only the new node, not the whole topology. |
| Removing a device that's referenced by other policies / configs / events leaves dangling refs | Slice 3 only marks the Device as RETIRED, doesn't DELETE. Configs and events keep their FK strings so the audit trail stays whole. |
| The Provisioner runs in the same process as the rest of the pipeline; a `clab deploy` failure could crash everything | The orchestrator wraps the provisioning stage in try/except and marks the stage as `error`, preserving every Neo4j write made before the failure. |

## Open question for the operator

**Are we OK with `sudo` happening from the post-commit hook?** The
existing Slice 1 hook already runs Python without `sudo`. Slice 3 adds
a new pattern: the provisioner shells out to `sudo containerlab deploy`.
On most operator workstations this needs either:
- An entry in `/etc/sudoers.d/` for passwordless `containerlab` invocations
- Or a desktop sudo prompt that breaks the "background hook" UX

I'll proceed assuming the operator has passwordless sudo for `containerlab`
(or that we accept a one-time sudo prompt per session). If neither is
acceptable, the alternative is to print the `clab deploy` command to
the hook log and require the operator to run it manually — which makes
Slice 3 less seamless but works without privilege.

I'll go with passwordless sudo and document the requirement in the
FIX_NOTES.
