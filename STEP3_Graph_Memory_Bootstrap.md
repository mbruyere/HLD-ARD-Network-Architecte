# STEP 3 — Graph-Memory + Qdrant Bootstrap

**Prerequisites:** STEP 1 (Neo4j) and STEP 2 (Live-Memory) completed.

This guide deploys **Tier 3** of the three-tier memory architecture:

```
Tier 1: Neo4j SSoT          → WHAT the network IS
Tier 2: Live-Memory         → WHY it is in that state
Tier 3: Graph-Memory        → WHAT WAS LEARNED  ← this guide
```

Graph-Memory (Cloud-Temple, Apache 2.0) is a "Knowledge Graph as a Service" MCP
server.  It accepts Markdown content, runs LLM-driven entity/relation extraction
guided by the IBN Network Lifecycle ontology, stores the knowledge graph in Neo4j
(namespace-isolated with the `IBN_LIFECYCLE_` prefix), and creates BGE-M3 1024-dim
vector embeddings in Qdrant.

---

## 1. Prerequisites Check

```bash
# Verify Neo4j is reachable (shared with SSoT, namespace-isolated)
neo4j-admin server status   # or check http://localhost:7474

# Verify Live-Memory is running
curl -s http://localhost:8002/health | jq .

# Verify Docker is available
docker info
```

---

## 2. Add Graph-Memory and Qdrant to docker-compose.yml

Append the following services to the existing `docker-compose.yml`:

```yaml
  # ── Qdrant — Vector DB for Graph-Memory embeddings ─────────────────────
  qdrant:
    image: qdrant/qdrant:v1.16.0
    container_name: ibn-qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"   # REST API
      - "6334:6334"   # gRPC
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Graph-Memory MCP Server ─────────────────────────────────────────────
  graph-memory:
    image: cloudtemple/graph-memory:latest
    container_name: ibn-graph-memory
    restart: unless-stopped
    ports:
      - "8003:8003"
    environment:
      - NEO4J_URI=bolt://host.docker.internal:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}
      - QDRANT_URL=http://qdrant:6333
      - GRAPH_MEMORY_PORT=8003
      - GRAPH_MEMORY_TOKEN=${GRAPH_MEMORY_TOKEN}
      - EMBEDDING_MODEL=BAAI/bge-m3
      - EMBEDDING_DIM=1024
      - LOG_LEVEL=INFO
    depends_on:
      qdrant:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8003/health"]
      interval: 15s
      timeout: 5s
      retries: 5

volumes:
  redis_data:        # already exists from STEP 2
  qdrant_data:
    driver: local
```

> **Neo4j sharing:** Graph-Memory uses the same Neo4j instance as the SSoT.
> All Graph-Memory labels are prefixed `IBN_LIFECYCLE_` — they never collide
> with the 9-layer SSoT ontology labels (`Intent`, `Policy`, `Device`, etc.).

---

## 3. Configure environment variables

Add to your `.env` file (create if absent):

```bash
# Graph-Memory
GRAPH_MEMORY_URL=http://localhost:8003
GRAPH_MEMORY_TOKEN=<generate a strong token>

# Already set from STEP 1/2:
# NEO4J_URI=bolt://localhost:7687
# NEO4J_PASSWORD=...
# LIVE_MEMORY_URL=http://localhost:8002
# LIVE_MEMORY_TOKEN=...
```

Generate a token:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 4. Start services

```bash
# Pull images
docker compose pull qdrant graph-memory

# Start (Qdrant first, then Graph-Memory)
docker compose up -d qdrant
docker compose up -d graph-memory

# Verify health
docker compose ps
curl -s http://localhost:6333/healthz        # Qdrant: {"title":"qdrant - Ready"}
curl -s http://localhost:8003/health | jq .  # Graph-Memory: {"status":"ok"}
```

---

## 5. Create the `ibn-lifecycle` memory with IBN Network Lifecycle ontology

```bash
# Upload the ontology file
curl -X POST http://localhost:8003/ontologies \
  -H "Authorization: Bearer $GRAPH_MEMORY_TOKEN" \
  -H "Content-Type: application/yaml" \
  --data-binary @src/ibn/ontology/ibn_lifecycle_ontology.yaml

# Create the ibn-lifecycle memory namespace
curl -X POST http://localhost:8003/mcp \
  -H "Authorization: Bearer $GRAPH_MEMORY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "memory_create",
    "arguments": {
      "name": "ibn-lifecycle",
      "description": "IBN Closed-Loop operational knowledge graph",
      "ontology_path": "ibn_lifecycle_ontology.yaml"
    }
  }'
```

Or using the Python client:

```python
from ibn.core.graph_memory_client import GraphMemoryClient

gm = GraphMemoryClient.from_env()

result = gm.memory_create(
    name="ibn-lifecycle",
    ontology_path="src/ibn/ontology/ibn_lifecycle_ontology.yaml",
    description="IBN Closed-Loop operational knowledge graph",
)
print(result)  # {"status": "created", "memory": "ibn-lifecycle"}
```

---

## 6. Verify namespace isolation in Neo4j

After the memory is created, verify the `IBN_LIFECYCLE_` prefix is in use and
does not collide with SSoT labels:

```cypher
// Should return 0 — no namespace collision
MATCH (n)
WHERE any(label IN labels(n)
          WHERE label STARTS WITH 'IBN_LIFECYCLE_'
          AND NOT label STARTS WITH 'IBN_LIFECYCLE_')
RETURN count(n) AS collisions;

// List IBN_LIFECYCLE_ labels (should be empty until first ingestion)
CALL db.labels()
YIELD label
WHERE label STARTS WITH 'IBN_LIFECYCLE_'
RETURN label ORDER BY label;
```

---

## 7. Test graph_push and question_answer

```python
from ibn.core.graph_memory_client import GraphMemoryClient

gm = GraphMemoryClient.from_env()

# Push a test bank file
result = gm.graph_push(
    memory="ibn-lifecycle",
    content="""
# Remediation History

## REM-001 (2026-03-15)
Drift detected on usf-fw-01: firewall rule FWR-002 missing.
Caused by: manual SSH session removed rule outside the loop.
Action: Auto-remediate — re-pushed CFG-002.
Result: COMPLIANT after 45 seconds.

Lesson: Disable direct SSH access to firewall management interfaces.
""",
    source="ibn-loop-inner/remediation-history",
)
print(f"Ingested: {result['entities_extracted']} entities")

# Query the knowledge graph
answer = gm.question_answer(
    memory="ibn-lifecycle",
    question="What caused the last USF firewall drift?",
)
print(f"Answer: {answer['answer']}")
print(f"Sources: {answer['sources']}")
```

Expected output:
```
Ingested: 3 entities   # DriftEvent, RootCauseAnalysis, RemediationAction
Answer: Based on the drift event REM-001 on 2026-03-15, rule FWR-002 was
        manually removed via SSH. Root cause: out-of-band CLI access.
Sources: ['ibn-loop-inner/remediation-history']
```

---

## 8. Wire ConsolidationManager into the inner loop

Edit `src/ibn/agents/inner_loop.py` to create and start a `ConsolidationManager`:

```python
from ibn.core.consolidation_manager import ConsolidationManager
from ibn.core.graph_memory_client import GraphMemoryClient

# In InnerLoop.__init__():
self._graph_memory = GraphMemoryClient.from_env()
self._consolidation = ConsolidationManager(
    live_memory=self._live_memory,
    graph_memory=self._graph_memory,
    event_bus=self._bus,
    note_threshold=20,
    sweep_interval=3600,
    push_to_graph=True,
)
self._consolidation.start()

# After each remediation cycle, emit the inner loop complete event:
self._bus.publish("inner.loop.complete", {"intent_id": intent_id})
```

---

## 9. Validate Qdrant embeddings

After ingesting at least one document:

```bash
# List Qdrant collections (one per Graph-Memory memory)
curl -s http://localhost:6333/collections | jq '.result.collections[].name'
# Expected: "ibn-lifecycle"

# Check embedding dimension and count
curl -s http://localhost:6333/collections/ibn-lifecycle | jq '.result.config.params'
# Expected: {"vectors": {"size": 1024, "distance": "Cosine"}}

curl -s "http://localhost:6333/collections/ibn-lifecycle" | jq '.result.points_count'
# Should increment with each graph_push() call
```

---

## 10. Set up periodic storage cleanup

Add to `docker-compose.yml` or run as a cron job:

```bash
# Daily cleanup of orphaned S3 objects
0 2 * * * curl -X POST http://localhost:8003/mcp \
  -H "Authorization: Bearer $GRAPH_MEMORY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool": "storage_cleanup", "arguments": {"memory": "ibn-lifecycle"}}'
```

Or via Python:
```python
gm.storage_cleanup("ibn-lifecycle")
```

---

## 11. Verify all three memory tiers are connected

```python
from ibn.core.neo4j_client import Neo4jClient
from ibn.core.live_memory_client import LiveMemoryClient
from ibn.core.graph_memory_client import GraphMemoryClient
from ibn.core.consolidation_manager import ConsolidationManager

# Tier 1: Neo4j SSoT
neo4j = Neo4jClient.from_env()
result = neo4j.run_query("MATCH (n:Device) RETURN count(n) AS devices")
print(f"Tier 1 — Devices in SSoT: {result[0]['devices']}")

# Tier 2: Live-Memory
lm = LiveMemoryClient.from_env()
spaces = lm.space_list()
print(f"Tier 2 — Live-Memory spaces: {[s['name'] for s in spaces]}")

# Tier 3: Graph-Memory
gm = GraphMemoryClient.from_env()
memories = gm.memory_list()
print(f"Tier 3 — Graph-Memory memories: {[m['name'] for m in memories]}")

# Bridge
mgr = ConsolidationManager(lm, gm)
answer = mgr.query_knowledge("What was learned in the last inner loop iteration?")
print(f"Tier 3 RAG: {answer['answer'][:100]}")
```

---

## Architecture reference

```
 ┌─── Tier 1: Neo4j SSoT ──────────────────────────────────────────────────┐
 │   Labels: Site, Device, Interface, Intent, Policy, FirewallRule, ...    │
 │   9-layer ontology  •  5 model states  •  Bolt :7687                    │
 └────────────────────────────────────────────────────────────────────────┘
                          │ shared Neo4j instance
 ┌─── Tier 3: Graph-Memory ────────────────────────────────────────────────┐
 │   Labels: IBN_LIFECYCLE_DriftEvent, IBN_LIFECYCLE_PolicyDecision, ...   │
 │   Namespace-isolated  •  BGE-M3 1024-dim  •  Qdrant :6333              │
 │   MCP :8003  •  question_answer() → graph-guided RAG                   │
 └────────────────────────────────────────────────────────────────────────┘
                          ▲
                graph_push_batch()
                          │
 ┌─── Tier 2: Live-Memory ─────────────────────────────────────────────────┐
 │   Spaces: ibn-loop-inner, ibn-candidate-*, ibn-por-*, ibn-deploy-*, ... │
 │   S3 backend  •  bank_consolidate() (LLM)  •  MCP :8002                │
 └────────────────────────────────────────────────────────────────────────┘
                          ▲
                     live_note()
                          │
 ┌─── Agents ──────────────────────────────────────────────────────────────┐
 │   A1 A2 A3 A4 A5 A6 A7 A8 A9 A10  (write notes, query knowledge)       │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `graph_push` returns `entities_extracted: 0` | Verify ontology file was uploaded; check Graph-Memory logs for LLM errors |
| `question_answer` returns "No relevant knowledge" | Ensure `memory_create` was called with the ontology path before first `graph_push` |
| Qdrant collection missing | Check `QDRANT_URL` env var in graph-memory container; verify Qdrant health |
| `IBN_LIFECYCLE_` labels not in Neo4j | Check `NEO4J_URI` in graph-memory container; must point to same instance as SSoT |
| Memory creation fails | Verify `GRAPH_MEMORY_TOKEN` is set and matches the server config |
| BGE-M3 download slow on first start | Embedding model downloads on first use (~800MB); check graph-memory container logs |

---

## Next step

With all three tiers running, proceed to validate the full inner loop:

```
STEP 4 (TBD): End-to-end inner loop validation
  drift detected (A6) → assessment (A7) → action (A8) →
  re-orchestrate (A5) → verify → consolidate (ConsolidationManager) →
  graph_push → question_answer proves knowledge persisted
```
