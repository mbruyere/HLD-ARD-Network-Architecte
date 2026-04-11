# Slice 1 — HLD-Driven Closed-Loop Pipeline

Date: 2026-04-11
Status: **DRAFT — awaiting operator approval before execution**
Author: IBN Lab + Claude

## Goal of this slice

Prove the full HLD → NetLab pipeline end-to-end on the smallest possible
surface. By the end of Slice 1 the operator can:

1. Edit one section of `Enterprise_Campus_Network_HLD (1).md` (the
   population VLAN table at lines 3172–3180).
2. `git commit` the change.
3. A post-commit hook automatically runs the closed-loop pipeline.
4. Within ~30 seconds the change has flowed through Agents 1 → 2 → 3 → 5 → 7,
   updated Neo4j SSoT at every step (Intent → Policy → FirewallRule →
   Configuration → DeploymentEvent → ComplianceAssessment), and pushed a
   real config delta to the VyOS firewalls in containerlab.

This slice does **not** add multi-vendor rendering, device provisioning,
or human approval gates — those are Slices 2, 3, 4 respectively. Slice 1
exists to make the *plumbing* real so all subsequent slices have a
working track to build on.

## Vision alignment

The full vision (as articulated by the operator):

> The HLD markdown is the source of intent. T0 = day zero of the network
> lifecycle. A git commit is the trigger. The closed loop reconciles
> reality to the HLD step by step, updating SSoT and state at each
> agent boundary. Operators only edit and commit the HLD; the loop
> handles translation, planning, rendering, deployment, and verification.

This is **GitOps for the network, with the closed loop as the
reconciliation controller and the HLD document as the desired state**.

Slice 1 honors that spirit by:

- Treating the HLD file as the input (not a form, not a JSON intent)
- Using a real git commit as the real trigger
- Walking through every agent boundary (not skipping any)
- Updating Neo4j model state at every transition
- Producing a real config delta on real containerlab devices

It does **not** honor the spirit by (yet):

- Only parsing one section of the HLD
- Only supporting VyOS as a target
- Skipping the human approval gate (Slice 4)
- Stubbing A4 Planning (Slice 4)

## In scope for Slice 1

| # | Component | New / Modified | Description |
|---|---|---|---|
| 1 | `src/ibn/core/models.py` | modified | Add `Intent.origin` field; add `Policy` and `FirewallRule` dataclasses |
| 2 | `src/ibn/parser/hld_parser.py` | new | Parse the population VLAN table from HLD markdown into draft Intent records (rule-based, not LLM) |
| 3 | `src/ibn/agents/agent1_ingestion.py` | modified | Add an HLD-ingestion phase: takes parsed table → produces draft Intents → conducts an LLM dialogue with the operator to confirm/refine → commits confirmed Intents to Neo4j |
| 4 | `src/ibn/agents/agent2_intent_policy.py` | new | Minimal A2: maps confirmed Intents into `Policy` and `FirewallRule` (L4) nodes using the HLD's population × DMZ access matrix as the rulebook |
| 5 | `src/ibn/pipeline/hld_commit.py` | new | Pipeline orchestrator: detects HLD diff, runs A1 → A2 → A3 → A4 (stub) → A5 → A7, writes a single audit trail to Live-Memory `ibn-loop-outer` |
| 6 | `infra/hooks/post-commit` + installer | new | A git post-commit hook that detects an HLD change in the just-made commit and invokes `python -m ibn.pipeline.hld_commit` |
| 7 | `tests/integration/test_slice1_hld_pipeline.py` | new | End-to-end acceptance test that programmatically edits the HLD, commits, and asserts the full chain landed in Neo4j + on the VyOS containers |

## Out of scope for Slice 1 (deferred)

- Multi-vendor rendering and SSH dispatch in A3 / A5 → **Slice 2**
- New switch device added to topology (Arista cEOS or similar) → **Slice 2**
- Provisioning new containerlab devices from HLD edits → **Slice 3**
- A4 Planning real implementation, blast radius analysis → **Slice 4**
- PR-based human approval gate (What-If → POR transition) → **Slice 4**
- Parsing the rest of the HLD (zones, firewall rules, HA, routing) → **Slice 5**
- LLM-driven parsing of unstructured HLD prose → **Slice 5**

## Architecture — what Slice 1 looks like

```
                          ┌──────────────────────────────────┐
                          │  Enterprise_Campus_Network_HLD.md│
                          │  (operator edits VLAN table)     │
                          └────────────────┬─────────────────┘
                                           │ git commit
                                           ▼
                          ┌──────────────────────────────────┐
                          │ .git/hooks/post-commit            │
                          │ detects HLD in commit             │
                          │ → python -m ibn.pipeline.hld_commit│
                          └────────────────┬─────────────────┘
                                           ▼
              ┌────────────────────────────────────────────────┐
              │           ibn.pipeline.hld_commit              │
              │  (single orchestrator, writes to ibn-loop-outer)│
              └────────────────────────────────────────────────┘
                       │
                       ├──► A1 Ingestion (upgraded)
                       │       1. parse HLD VLAN table (rule-based)
                       │       2. diff vs existing Neo4j Intents
                       │       3. LLM dialogue: confirm/refine drafts
                       │       4. write confirmed Intent (L4) nodes
                       │          (modelState=CANDIDATE, origin=HLD:line)
                       │
                       ├──► A2 Intent→Policy (new, minimal)
                       │       1. read CANDIDATE Intents
                       │       2. apply HLD pop×DMZ access matrix
                       │       3. write Policy + FirewallRule (L4)
                       │
                       ├──► A4 Planning (stub)
                       │       log "blast radius: N firewalls" — no gating
                       │
                       ├──► A3 Policy→Config (existing, VyOS-only)
                       │       1. read FirewallRule + Device + Zone
                       │       2. render VyOS Jinja2 templates
                       │       3. write Configuration (L5, CANDIDATE)
                       │
                       ├──► A5 Orchestration (existing, VyOS-only)
                       │       1. SSH push to clab-ibnlab-usf{1,2}/dmzfw{1,2}
                       │       2. write DeploymentEvent (L5, DEPLOYED)
                       │
                       └──► A7 Assessment (existing)
                               1. compare POR vs As-Built
                               2. write ComplianceAssessment (L6)
                               3. publish event for inner loop to pick up
```

Every arrow is a real Neo4j write + a `live_note()` to `ibn-loop-outer`
+ a Redis event bus publication. The audit trail is queryable end-to-end
after one commit.

## Data flow walkthrough — one concrete example

Suppose the operator changes line 3176 of the HLD from:

```
| Guest Access | 140 | 50-300 | 10-100 | Scavenger | CS1 | 5-10 Mbps |
```

to:

```
| Contractor Access | 141 | 20-80 | 5-20 | Standard | AF21 | 2-5 Mbps |
```

(adds a brand new "Contractor" population on a new VLAN 141.)

1. **Operator runs `git commit -am "Add Contractor population on VLAN 141"`.**
2. **Post-commit hook fires.** It runs `git show HEAD --name-only` and sees
   `Enterprise_Campus_Network_HLD (1).md` in the commit. It invokes
   `python -m ibn.pipeline.hld_commit --commit HEAD`.
3. **`hld_commit.py` reads the diff.** Computes that VLAN 141 is new,
   VLAN 140 is unchanged. Produces a *change set*.
4. **A1 Ingestion (HLD phase) runs.** Parser produces a draft Intent:
   ```
   Intent(intentId="INT-HLD-141", type="population-access",
          subject="Contractor", action="permit", target="Internet",
          origin="HLD:Enterprise_Campus_Network_HLD.md:3176",
          modelState=CANDIDATE)
   ```
5. **A1 dialogue phase runs.** The LLM-backed dialogue agent looks at the
   draft and asks the operator (CLI prompt for now):
   > "I see VLAN 141 is a new 'Contractor' population. The HLD pattern
   > suggests Contractors should also be denied lateral access to other
   > populations except DNS (VLAN 200). Should I:
   > (a) apply the standard 'restricted-user' template (deny lateral,
   >     allow Internet+DNS only)
   > (b) apply the 'guest-equivalent' template (deny lateral, Internet only)
   > (c) something else — describe it"
6. **Operator answers `(a)`.** A1 commits the confirmed Intent to Neo4j.
   Emits `live_note()` to `ibn-loop-outer` with the dialogue transcript.
7. **A2 runs.** Sees the new CANDIDATE Intent, applies the access matrix,
   creates `Policy(POL-CONTRACTOR-001)` and three `FirewallRule` nodes:
   - permit Contractor → Internet
   - permit Contractor → DNS DMZ (VLAN 200)
   - deny Contractor → all other populations (catch-all)
8. **A4 stub runs.** Logs "blast radius: 4 devices (usf1, usf2, dmzfw1, dmzfw2)".
9. **A3 runs (existing code).** Renders updated VyOS configs for the 4
   firewalls. Writes 4 Configuration (CANDIDATE) nodes.
10. **A5 runs (existing code).** SSH-pushes to all 4 firewalls. Writes 4
    DeploymentEvent (DEPLOYED) nodes.
11. **A7 runs (existing code).** Polls running configs, computes drift,
    writes 4 ComplianceAssessment (AS_BUILT) nodes — all COMPLIANT.
12. **Pipeline emits `outer.loop.complete` event** to Redis. Inner loop
    picks it up for ongoing monitoring.

The operator sees a single CLI dialogue (the A1 refinement step) plus
a final summary printed to the terminal. Total wall-clock budget: ~30s
excluding the LLM dialogue round-trip.

## Why upgrade Agent 1 instead of creating a new "translator agent"

Per **RFC 9315 §4.2** ("interactive refinement dialog"), the role of the
ingestion stage is to take a raw, possibly ambiguous intent and refine
it through dialogue with the operator until it is unambiguous and
verifiable. The current `Agent1Ingestion` only does the trivial case
(operator hands it a fully-structured dict). Slice 1 adds the harder
case — operator hands it a markdown document — by giving A1 two phases:

- **Phase A: Parse (rule-based).** Extracts deterministic structure
  from the HLD markdown table. No ambiguity.
- **Phase B: Refine (LLM-backed dialogue).** For each draft Intent,
  surfaces what the parser couldn't infer (zone membership, access
  policy template, lateral movement rules), asks the operator, and
  produces the confirmed Intent.

This is the same agent doing the same job (intent ingestion), just
extended to handle a richer input format. It also matches what
CLAUDE.md already says about Phase 3:

> Upgrade Agent 1 (Ingestion) — natural language intent parsing
> (beyond structured templates), semantic validation, interactive
> refinement dialog per RFC 9315 §4.2

Slice 1 brings that Phase 3 work forward because it's the critical
piece that makes the HLD-driven loop possible.

The LLM dialogue uses the same `LLMAAS_API_URL` / `LLMAAS_MODEL`
configuration that Graph-Memory already uses (Anthropic Haiku via the
embedding-proxy `/v1/chat/completions` route fixed in
[FIX_NOTES_GraphMemory_Tier3.md](FIX_NOTES_GraphMemory_Tier3.md)).

## Work breakdown — execution order

1. **Data model extensions** ([src/ibn/core/models.py](src/ibn/core/models.py))
   - Add `Intent.origin: Optional[str] = None` for HLD lineage
   - Add `@dataclass class Policy` (policyId, name, type, intentId, modelState, createdAt)
   - Add `@dataclass class FirewallRule` (ruleId, policyId, sourceZone, destZone, sourceVlan, destVlan, action, protocol, modelState, createdAt)

2. **HLD parser** ([src/ibn/parser/hld_parser.py](src/ibn/parser/hld_parser.py))
   - `parse_population_table(markdown_text) → list[PopulationEntry]`
   - `parse_dmz_table(markdown_text) → list[DmzEntry]`
   - `extract_changes(old_md, new_md) → ChangeSet`
   - Pure functions, no Neo4j or Live-Memory dependencies. Unit-tested.

3. **Agent 1 upgrade** ([src/ibn/agents/agent1_ingestion.py](src/ibn/agents/agent1_ingestion.py))
   - Add `ingest_hld_changeset(changeset) → list[Intent]` method
   - Add `_refine_via_dialogue(draft_intent) → Intent` method that calls
     the LLM with a structured prompt and reads operator answers from stdin
     (or from a passed-in dialogue function — mockable for tests)
   - Preserve existing `_execute()` for backward compat with structured input

4. **Agent 2 (new, minimal)** ([src/ibn/agents/agent2_intent_policy.py](src/ibn/agents/agent2_intent_policy.py))
   - `Agent2IntentPolicy.run(intent_id) → dict`
   - Loads the Intent, looks up the corresponding population/zone in Neo4j,
     applies a hand-coded access matrix derived from HLD §9, writes
     `Policy` + `FirewallRule` nodes
   - Writes `live_note()` to `ibn-candidate-001`
   - Publishes `policy.translated` event to Redis

5. **Pipeline orchestrator** ([src/ibn/pipeline/hld_commit.py](src/ibn/pipeline/hld_commit.py))
   - `main(commit_sha)` — entry point
   - Reads diff for the HLD file at the given commit
   - Calls A1 → A2 → A3 → A4(stub) → A5 → A7 in sequence
   - Each step gates on the previous; failure → escalate via live_note + exit
   - Final summary printed to stdout

6. **Git post-commit hook** ([infra/hooks/post-commit](infra/hooks/post-commit) + installer script)
   - Bash script: detect HLD file in `git show HEAD --name-only`, exec the
     pipeline orchestrator in background (operator's terminal stays free)
   - Installer: `python -m ibn.tools.install_hooks` — symlinks the hook
     into `.git/hooks/post-commit`, never overwrites existing hooks

7. **Acceptance test** ([tests/integration/test_slice1_hld_pipeline.py](tests/integration/test_slice1_hld_pipeline.py))
   - Uses a temporary git worktree of the repo
   - Programmatically edits the HLD VLAN table
   - Runs the orchestrator directly (bypasses the hook for test isolation)
   - Asserts the full chain in Neo4j: Intent → Policy → FirewallRule →
     Configuration → DeploymentEvent → ComplianceAssessment
   - Asserts the dialogue function is called and its answers are recorded
   - Marked `@requires_real_infra` — skipped in mock-only runs

## Acceptance criteria

Slice 1 is **done** when all of these are true:

1. The acceptance test passes against real Neo4j + Live-Memory + the running
   containerlab VyOS firewalls.
2. Manually editing one cell in the HLD VLAN table, running `git commit`,
   and watching the terminal produces:
   - One LLM dialogue prompt (visible to the operator)
   - A printed summary showing the agents that ran and the Neo4j IDs
     created at each step
   - A queryable audit trail in Neo4j (one Cypher query traces the change
     from HLD line number → ComplianceAssessment)
3. Reverting the commit and re-committing produces a no-op (idempotency).
4. `live_note()` entries in `ibn-loop-outer` form a complete narrative of
   the change for the consolidation pipeline to ingest later.
5. The slice is documented in `FIX_NOTES_Slice1_HLD_Pipeline.md` after merge.

## Decisions deferred to later slices

| Decision | Slice | Rationale |
|---|---|---|
| Which switch OS (Arista cEOS / SR Linux / FRR) | 2 | Only relevant once we have multi-vendor rendering |
| Vendor dispatch architecture in A3 / A5 | 2 | Tight coupling to OS choice above |
| Containerlab node creation API for new devices | 3 | Requires A5 to know how to mutate `clab.yml` |
| What-If state and PR-based approval | 4 | Requires A4 Planning to have real output |
| LLM-based parsing of unstructured HLD prose | 5 | Population table is the easy case; doing the rest needs real LLM extraction with hallucination guards |
| Auto-generation of NetLab topology YAML from HLD | 3 or 5 | Conflict-prone — needs Slice 4's approval gate first |

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM dialogue hangs or hallucinates a policy that doesn't match HLD intent | Slice 1 dialogue is multiple-choice, not free-form. Operator picks (a)/(b)/(c)/(d). LLM only generates the *prompt*, not the chosen answer |
| Post-commit hook makes commits feel slow | Hook backgrounds the pipeline (`nohup … &`) and prints a job ID. Operator's `git commit` returns instantly |
| Idempotency breaks if A1 creates duplicate Intents on re-run | A1 keys Intents by `origin` (HLD file:line). Re-parsing the same line returns the existing Intent ID |
| Hook fires on unrelated commits and wastes cycles | Hook checks `git show HEAD --name-only` for the HLD filename. Only HLD-touching commits trigger the pipeline |
| The operator's terminal is the wrong UX for the dialogue | Slice 1 ships with stdin/stdout dialogue. Slice 4's PR-based gate replaces it with a PR comment workflow |
| Existing tests break because of the new `Intent.origin` field | The field is `Optional[str] = None`, so all existing `Intent(...)` constructions remain valid |

## Estimated execution shape

(Not time estimates — execution order and dependency chain.)

```
1. models.py extensions ──┬─► 2. hld_parser.py ──┐
                          │                       │
                          └─► (no other deps)     │
                                                  ▼
                                       3. agent1 upgrade ──┐
                                                            │
                                       4. agent2 new ───────┤
                                                            ▼
                                                  5. hld_commit.py
                                                            │
                                                            ├─► 6. post-commit hook
                                                            │
                                                            └─► 7. acceptance test
```

Tasks 1, 2 can be built and unit-tested with zero infra.
Tasks 3, 4 need Live-Memory + Neo4j + LLM proxy (all already up).
Tasks 5, 6 need git working tree (always available).
Task 7 needs everything plus the running containerlab.

## Open questions for the operator before execution starts

None — all four decisions from the previous round have been answered:

- **(1)** Slicing approach: confirmed
- **(2)** First HLD section: population VLAN table; A1 upgraded with dialogue
  (not a new agent)
- **(3)** Trigger mechanism: git post-commit hook
- **(4)** A4 Planning scope in Slice 1: stubbed; built properly in Slice 4

Awaiting only the explicit "go" before starting task 1.
