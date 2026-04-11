# Slice 2.5 — Firewall Seed Cleanup — SKIPPED

Date: 2026-04-11
Status: **Not implemented — based on a wrong assumption.**

## Original goal

Slice 2's followup list said:
> Reseed the firewall devices with `deviceId` matching their containerlab
> container names (or add a `clabContainer` property and have A5 use it).
> This will make the VyOS push actually succeed and complete the loop for
> all 5 devices instead of just the SR Linux switch.

The assumption was that the *only* blocker for VyOS push was the
deviceId-to-container-name mismatch. Slice 2.5 was supposed to fix that
mismatch and unlock the VyOS push path.

## Why it was skipped

The assumption is wrong. The lab's VyOS image
(`ghcr.io/sysoleg/vyos-container:latest`) is not pushable in any clean
way regardless of hostname mapping:

| Push channel | Result on the running container |
|---|---|
| **SSH (paramiko, port 22)** | `Connection refused` — sshd is not running in this image |
| **`docker exec sr_cli`-style** | No equivalent CLI shell tool exists for VyOS |
| **`docker exec /usr/bin/vbash -c '...'`** with simple set + commit | Set commands accepted; `commit` fails: `bridge-nf-call-iptables: No such file or directory ... [[firewall]] failed Commit failed` — the container's network namespace lacks the bridge netfilter modules that VyOS' firewall code requires |
| **`docker exec /usr/bin/vbash -i ...`** (interactive) | `cannot set terminal process group ... no job control in this shell` then a `/opt/vyatta/share/.../vyatta-cfg-run: syntax error` |
| **Direct write to `/config/config.boot`** | Possible but requires emitting VyOS' tree-format YAML, not the `set` commands the existing templates produce, and bouncing the config daemon — invasive and lab-specific |

In other words, this image is a **dev variant** suitable for
running VyOS as a process target (so the `set` commands are valid
syntax) but **not** suitable for accepting a real config commit driven
from outside the container. It deliberately stubs out the things that
would normally activate the config (the hostname `set` even prints
`WARNING! I'm a dummy script to set the hostname inside a container!`).

The deviceId mismatch is real, but fixing it on its own gets us nowhere —
we'd just be SSHing to a container that doesn't accept SSH.

## What real fix would look like

To actually unlock VyOS push end-to-end, we need ONE of:

1. **Swap the lab firewall image** to a VyOS variant that ships with sshd
   and a working config-commit path. Candidates:
   - The official `vyos/vyos:current` from the rolling release (heavier,
     longer boot, but real CLI/SSH)
   - A custom built image based on the official VyOS ISO with cloud-init
   - A different L3 NOS (Nokia SR Linux already proved out as a working
     push target — we could replace the VyOS firewalls with SR Linux
     "firewall" instances using IP-based ACL rendering, sacrificing the
     NAT/VRRP bits we don't actually use yet)

2. **Add a `_vyos_lab_executor` that simulates the push** — runs the set
   commands in candidate mode via vbash, tolerates the commit failure,
   records the outcome as `DEPLOYED_PARTIAL`. This is honest but
   doesn't actually deliver the configuration to a working dataplane.
   Deferred — see "Recommended next moves" below.

3. **Skip VyOS push entirely** in the multi-vendor story — accept that
   the lab proves the closed loop on SR Linux only, and that adding
   real VyOS push is a separate Phase 6 lab-image task.

## Decision: skip Slice 2.5, move to Slice 3

Slice 3 (HLD-driven device provisioning) is more valuable than working
around the dev image's limitations. When Slice 3 lands, the operator
will be able to add devices via the HLD itself — at which point we can
choose to add the firewalls as Nokia SR Linux nodes (already proven to
push) instead of VyOS containers.

The seed cleanup that Slice 2.5 was going to do (`clabContainer`
property + matching device IDs) is rolled into Slice 3's provisioning
work, where it makes more sense — Slice 3 needs a clean device-to-container
mapping anyway to know which containers to spin up or tear down.

## Status of A5's behavior

After Slice 2, A5 already does the right thing for these unpushable
firewalls: it skips them with a `device-result` Live-Memory note
(`SKIPPED (empty rendered config)`) and reports them as `12 skipped`
in the orchestrator's stage summary. The pipeline keeps moving and the
SR Linux push still happens. Nothing in the closed loop is broken —
the limitation is honestly surfaced, not silently swallowed.

## Recommended next moves

1. **Slice 3** — HLD-driven device provisioning. When the HLD adds a
   new device, the loop spins up the container. As part of that work,
   add the `clabContainer` property to Device nodes and have A5 use it
   for dispatch. This subsumes the original Slice 2.5 seed cleanup.

2. **(Eventually)** — Replace the firewall image. Either the official
   VyOS rolling, or swap firewalls to Nokia SR Linux. Tracked as a
   Phase 6 lab cleanup.

## Confirmation that the existing pipeline still works

- Slice 1 acceptance test: 4/4 passing
- Slice 2 acceptance test: 5/5 passing including the live SR Linux push
  via `docker exec sr_cli`
- The `[ibn-hook]` post-commit pipeline runs end-to-end and writes the
  full audit trail to Neo4j on every HLD commit

Nothing in this finding regresses any prior work — it just clarifies
why Slice 2.5 as originally scoped is the wrong shape and where the
real fix belongs.
