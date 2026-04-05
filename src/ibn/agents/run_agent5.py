#!/usr/bin/env python3
"""
Agent 5 — Orchestration CLI runner

Pulls a pending intent from Neo4j, reads the associated Configuration nodes,
and runs Agent 5 to push configs to devices via SSH.

Environment variables:
    NEO4J_URI          bolt://localhost:7687
    NEO4J_USER         neo4j
    NEO4J_PASSWORD     ibn-closed-loop-2026
    LIVE_MEMORY_URL    http://localhost:8002
    LIVE_MEMORY_TOKEN  <agent token>
    NETLAB_SSH_USER    vyos  (default)

Usage:
    # Deploy a specific intent
    python -m ibn.agents.run_agent5 --intent-id INT-001

    # Deploy all pending intents (status=TRANSLATED)
    python -m ibn.agents.run_agent5 --all

    # Dry-run: show plan without pushing
    python -m ibn.agents.run_agent5 --intent-id INT-001 --dry-run

    # Generate NetLab topology YAML for a site
    python -m ibn.agents.run_agent5 --topology --site-id site-hq --output topology.yml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("agent5.runner")


def _make_clients():
    from ibn.core.neo4j_client import Neo4jClient
    from ibn.core.live_memory_client import LiveMemoryClient

    neo4j = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "ibn-closed-loop-2026"),
    )
    lm = LiveMemoryClient(
        base_url=os.environ.get("LIVE_MEMORY_URL", "http://localhost:8002"),
        token=os.environ.get(
            "LIVE_MEMORY_TOKEN",
            os.environ.get("LM_AGENT_TOKEN", ""),
        ),
    )
    return neo4j, lm


def _fetch_plan(neo4j, intent_id: str) -> list[dict]:
    """
    Fetch the deployment plan for an intent from Neo4j.

    Queries Configuration nodes (status=CANDIDATE) linked to the intent,
    ordered by planned sequence.
    """
    rows = neo4j.run_query(
        """
        MATCH (i:Intent {intentId: $intentId})-[:REQUIRES]->(c:Configuration)
        WHERE c.modelState IN ['CANDIDATE', 'POR']
        RETURN c.configId  AS configId,
               c.deviceId  AS deviceId,
               c.content   AS content,
               c.version   AS version
        ORDER BY c.deviceId
        """,
        intentId=intent_id,
    )

    if rows:
        return [
            {
                "deviceId": r["deviceId"],
                "configId": r["configId"],
                "content":  r.get("content", ""),
            }
            for r in rows
        ]

    # Fallback: look for any CANDIDATE Configurations for the intent's devices
    log.warning(
        "No REQUIRES relationships found for %s — "
        "falling back to direct Configuration lookup",
        intent_id,
    )
    rows = neo4j.run_query(
        """
        MATCH (c:Configuration)
        WHERE c.modelState = 'CANDIDATE'
        RETURN c.configId AS configId,
               c.deviceId AS deviceId,
               c.content  AS content
        ORDER BY c.deviceId
        LIMIT 10
        """
    )
    return [
        {
            "deviceId": r["deviceId"],
            "configId": r["configId"],
            "content":  r.get("content", ""),
        }
        for r in rows
    ]


def _get_or_create_deploy_space(lm, intent_id: str) -> str:
    """Create a per-deployment Live-Memory space and return its ID."""
    from ibn.core.live_memory_client import LiveMemoryClient

    space_id = f"ibn-deploy-{uuid.uuid4().hex[:8]}"
    try:
        lm.space_create(
            space_id=space_id,
            description=f"Deployment space for intent {intent_id}",
            owner="ibn-system",
            rules=(
                "# IBN Deployment — Memory Bank Rules\n\n"
                "## Mandatory Bank Files\n"
                "### 1. deployment-log.md\n"
                "Chronological step log. Each device: command/success/failure.\n"
                "### 2. verification-results.md\n"
                "Post-deployment verification per device: VERIFIED or FAILED.\n"
            ),
        )
        log.info("Created deploy space: %s", space_id)
    except Exception as exc:
        log.warning("Could not create deploy space %s: %s", space_id, exc)
    return space_id


def run_deploy(args):
    """Execute a deployment for one or all pending intents."""
    from ibn.agents.agent5_orchestration import Agent5Orchestration

    neo4j, lm = _make_clients()

    intent_ids: list[str] = []
    if args.intent_id:
        intent_ids = [args.intent_id]
    elif args.all:
        rows = neo4j.run_query(
            "MATCH (i:Intent {status: 'TRANSLATED', modelState: 'POR'}) "
            "RETURN i.intentId AS intentId LIMIT 20"
        )
        intent_ids = [r["intentId"] for r in rows]
        if not intent_ids:
            log.warning("No TRANSLATED intents found in Neo4j POR state.")
            return

    for intent_id in intent_ids:
        plan = _fetch_plan(neo4j, intent_id)
        if not plan:
            log.warning("No deployment plan found for %s — skipping", intent_id)
            continue

        log.info("Intent %s — %d devices in plan", intent_id, len(plan))
        for step in plan:
            log.info("  • %s  (%s)", step["deviceId"], step["configId"])

        if args.dry_run:
            print(json.dumps({"dry_run": True, "intent_id": intent_id, "plan": plan}, indent=2))
            continue

        deploy_space = _get_or_create_deploy_space(lm, intent_id)

        agent = Agent5Orchestration(neo4j=neo4j, live_memory=lm)
        try:
            result = agent.run(
                intent_id=intent_id,
                plan=plan,
                deploy_space=deploy_space,
                action="deploy",
            )
        except Exception as exc:
            log.error("Agent 5 run failed for %s: %s", intent_id, exc, exc_info=True)
            sys.exit(1)

        print(json.dumps(result, indent=2))
        log.info(
            "Intent %s — %s (%d devices, verified=%s)",
            intent_id,
            result.get("status"),
            len(result.get("devices", [])),
            result.get("verified"),
        )

    neo4j.close()


def run_topology(args):
    """Generate a NetLab topology.yml from Neo4j POR state."""
    from ibn.agents.netlab_topology import NetLabTopologyGenerator

    neo4j, _ = _make_clients()
    gen = NetLabTopologyGenerator(neo4j)
    topo = gen.generate(site_id=args.site_id)

    if args.output:
        out = gen.save(topo, args.output)
        log.info("Topology written to %s (%d nodes, %d vlans, %d links)",
                 out,
                 len(topo.get("nodes", {})),
                 len(topo.get("vlans", {})),
                 len(topo.get("links", [])))
    else:
        import yaml
        print(yaml.dump(topo, default_flow_style=False, sort_keys=False))

    neo4j.close()


def main():
    parser = argparse.ArgumentParser(
        description="Agent 5 — Orchestration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # ── deploy sub-command ─────────────────────────────────────────────
    deploy_p = sub.add_parser("deploy", help="Push configs to devices")
    group = deploy_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--intent-id", help="Deploy a specific intent ID")
    group.add_argument("--all", action="store_true", help="Deploy all TRANSLATED intents")
    deploy_p.add_argument("--dry-run", action="store_true", help="Print plan without pushing")

    # ── topology sub-command ──────────────────────────────────────────
    topo_p = sub.add_parser("topology", help="Generate NetLab topology YAML")
    topo_p.add_argument("--site-id", default="site-hq", help="Neo4j siteId (default: site-hq)")
    topo_p.add_argument("--output", "-o", help="Output file path (default: stdout)")

    # ── Legacy flat args (backwards compat) ────────────────────────────
    parser.add_argument("--intent-id", help="(legacy) Deploy a specific intent ID")
    parser.add_argument("--all", action="store_true", help="(legacy) Deploy all TRANSLATED intents")
    parser.add_argument("--dry-run", action="store_true", help="(legacy) Dry run")
    parser.add_argument("--topology", action="store_true", help="(legacy) Generate topology")
    parser.add_argument("--site-id", default="site-hq", help="(legacy) Site ID for topology")
    parser.add_argument("--output", "-o", help="(legacy) Output path for topology")

    args = parser.parse_args()

    if args.command == "deploy" or (not args.command and (args.intent_id or args.all)):
        run_deploy(args)
    elif args.command == "topology" or (not args.command and args.topology):
        run_topology(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
