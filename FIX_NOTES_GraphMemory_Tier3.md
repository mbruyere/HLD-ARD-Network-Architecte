# Graph-Memory Tier-3 Pipeline Fix Notes

Date: 2026-04-11

## Context

While validating the closed loop end-to-end, the Tier-3 knowledge pipeline
(`bank_consolidate()` → `graph_push()` → entity extraction → `question_answer()`)
was silently failing with `entities_extracted: 0` on every ingest. Two
independent bugs were masking the problem.

## Bugs

### 1. Infra — `LLMAAS_API_URL` missing `/v1` prefix

Graph-Memory's LLM extractor was configured with
`LLMAAS_API_URL=http://host.docker.internal:8004` and hit
`/chat/completions` → **404** because the embedding-proxy serves
`/v1/chat/completions`. Every LLM-based entity extraction failed silently
for the entire Tier-3 pipeline.

**Fix** — [docker-compose.yml](docker-compose.yml#L93):

```yaml
- LLMAAS_API_URL=http://host.docker.internal:8004/v1
```

### 2. Client — wrong MCP parameter schema + silent error-swallowing

`GraphMemoryClient` was sending entirely the wrong MCP parameter schema to
Graph-Memory and then defaulting the response to
`{status: "ingested", entities_extracted: 0}` whenever the server rejected
the request.

Real Graph-Memory MCP schema vs what we were sending:

| Method | Old (wrong) | New (correct) |
|---|---|---|
| `memory_create` | `{name, ontology_path}` | `{memory_id, name, ontology}` |
| `memory_delete` | `{name}` | `{memory_id}` |
| `memory_ingest` | `{memory, content, source}` | `{memory_id, content_base64, filename}` |
| `question_answer` | `{memory, max_results}` | `{memory_id, limit}` |
| `storage_cleanup` | `{memory}` | `{memory_id}` |
| `graph_stats` | tool=`graph_stats` | tool=`memory_stats` |

**Fixes in [src/ibn/core/graph_memory_client.py](src/ibn/core/graph_memory_client.py):**

- Rewrote all six methods to use the correct MCP args.
- `graph_push()` now base64-encodes content and derives `filename` from
  the `source` path (last segment, `.md` appended if no extension).
- Response parsing sums the server's `entity_types` / `relation_types`
  dicts into the flat `entities_extracted` / `relations_extracted` keys
  the rest of the codebase expects.
- `_call_mcp_tool` now surfaces server error strings as
  `{status: "error", message: ...}` dicts instead of returning them as
  raw strings that get silently discarded.
- Added `DEFAULT_ONTOLOGY = "general"` fallback — the `ibn-lifecycle`
  custom YAML ontology is not installed inside the Graph-Memory container
  yet (see Followup below).

### 3. `bank_read_all` response shape

`LiveMemoryClient.bank_read_all()` was passing the raw server response
`{status, space_id, files: [...], ...}` straight through, but tests and
`graph_push_batch` expect a flat `{filename: content}` mapping.

**Fix** — [src/ibn/core/live_memory_client.py](src/ibn/core/live_memory_client.py#L205):
unwrap the `files` list into a `{filename: content}` dict.

### 4. Unit tests — T17 mocked the old (broken) schema

9 tests in [tests/unit/test_t17_graph_memory_client.py](tests/unit/test_t17_graph_memory_client.py)
asserted the pre-fix MCP parameter names. Updated them to the real schema
and to the new honest error behaviour (empty response → `status: error`
instead of pretending success).

## Test results

| Suite | Before | After |
|---|---|---|
| Phase 2 inner loop integration | 33/33 | 33/33 |
| T11 consolidation integration | 7/11 (4 failing — 401s, entities=0) | 12/12 |
| T3 live-memory integration | 8/8 | 8/8 |
| T17 graph-memory client unit | 20/29 (9 failing on old schema) | 29/29 |

Final regression run: **53/53 integration tests passed** end-to-end against
real Neo4j + Live-Memory + Graph-Memory (~35 min runtime, dominated by
real LLM extraction on each ingest).

## Followup (not blocking)

The project ships a custom IBN-specific ontology at
`src/ibn/ontology/ibn_lifecycle_ontology.yaml` (Decisions, Incidents,
Operations, Knowledge entity families — see §10.2.2 of the architecture
doc). It is **not** installed inside the Graph-Memory container image.

Current behaviour: `GraphMemoryClient` falls back to
`DEFAULT_ONTOLOGY = "general"`, which extracts generic business entities
(Company, Technology, Product) instead of IBN-specific ones
(Drift, Remediation, FirewallRule, Incident).

To get domain-specific entity types in Graph-Memory, the `ibn_lifecycle`
ontology YAML needs to be baked into the Graph-Memory container build so
the server recognises `"ibn-lifecycle"` as a valid ontology name in
`memory_create`. That is a separate piece of work against the
Graph-Memory container image.
