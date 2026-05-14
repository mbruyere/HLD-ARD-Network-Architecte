# Plan — Migrate from ARM64 Multipass VM to x86_64 / AMD

Branch: `x86-migration`
Status: **Phase 1 — awaiting answers below before scaffolding starts**
Predecessors: Slice 5 (FRR + 4 new devices), Slice 7a (gNMI for SR Linux)

---

## Why

The current lab runs on an ARM64 Multipass VM, which forces several
workarounds that hurt reproducibility:

| Workaround | Cost | Root cause |
|---|---|---|
| `tonistiigi/binfmt --install all` on every boot | 30-60 s, requires `--privileged` | VyOS image is amd64-only |
| `DOCKER_DEFAULT_PLATFORM=linux/amd64` for clab deploy | QEMU emulation for VyOS | same |
| VyOS boot takes 15-30 min under QEMU | Slow iteration cycle | same |
| Custom `infra/frr-image/Dockerfile` (62 MB ibn-frr:local) | Extra build step | `frrouting/frr` upstream is amd64-only |
| `/tmp/ibn-lab/` working dir | Lab can't write to multipass home | `chown` not permitted on mp-mounted home |
| Neo4j OOM at 8 GB | VM had to be resized to 12 GB | QEMU overhead per emulated container |

Moving to x86_64 eliminates **all six** workarounds. The native-amd64
host runs VyOS in seconds (not minutes), drops the custom FRR
Dockerfile, removes the binfmt + platform-override scaffolding, and
shrinks the memory budget back to ~8 GB.

This branch will also use the migration as an opportunity to **pin
everything** for reproducibility (exact Python versions, container
digests instead of `:latest`, a deterministic bootstrap script).

---

## Open questions — please answer below before I start Phase 1

These five answers determine the shape of the rest of the plan. Edit
this file directly to fill them in (or reply in chat).

### Q1. Do you have an x86 host ready for Phase 5 (validation)?

> **Your answer:**

Options:
- **(a)** Yes, I have an Ubuntu 24.04 amd64 host / Multipass amd64 VM /
  cloud instance ready. Phases 3 and 5 will run end-to-end on it
  before merge.
- **(b)** No host yet. The branch lands as "code complete, untested
  on x86" with `FIX_NOTES_X86_Migration.md` marked TODO. We merge
  only after the validation pass.
- **(c)** I'll provision one as part of this work (cloud, lab box,
  spare laptop, etc.). Please tell me what spec is recommended.

---

### Q2. VyOS image choice

> **Your answer:**

Today we use `ghcr.io/sysoleg/vyos-container:latest` (a community-built
container of VyOS rolling). On amd64 this runs natively, no QEMU.

Options:
- **(a)** **Keep `sysoleg/vyos-container`** but pin to a specific tag/digest.
  Pro: zero behavioural change, same VyOS version we already use.
  Con: third-party image, no guaranteed release cadence.
- **(b)** Switch to **official `vyos/vyos:1.5-rolling`** (or 1.4-stable).
  Pro: upstream support, predictable releases, signed images.
  Con: behavioural differences possible; existing VyOS templates may
  need small adjustments; need to test commit-script path.
- **(c)** Evaluate both during Phase 3 and pick the one that boots
  cleanly first.

---

### Q3. Memory budget target on x86

> **Your answer:**

On ARM with QEMU, the lab needs 12 GB (8 GB causes Neo4j OOM when 5
SR Linux containers run concurrently). On x86 with native
virtualisation, the same workload fits in much less.

Options:
- **(a)** **Target 8 GB minimum**, validate the 16-container topology
  fits. Lowest barrier to entry for new operators.
- **(b)** **Keep 12 GB recommendation** for headroom, document 8 GB as
  "works but tight".
- **(c)** **Aim lower — 6 GB** by adding a "lite" topology that runs
  only the minimum needed for the test suite (Neo4j + Live-Memory +
  2 containers + Redis), and a "full" topology for end-to-end.

---

### Q4. Python dependency pinning approach

> **Your answer:**

Today `requirements.txt` uses `>=` ranges (e.g.\ `pygnmi>=0.8,<1`).
This is fine for development but allows drift between hosts.

Options:
- **(a)** **Plain `==` pins in `requirements.txt`.** Simple, no new
  tooling, single source of truth. Operators run `pip install -r
  requirements.txt`.
- **(b)** **`pip-tools`**: keep `requirements.in` with `>=` ranges
  for human edits, generate `requirements.txt` (locked) with
  `pip-compile`. Two files but more maintainable.
- **(c)** **`uv`** (the new Astral tool, fast Rust resolver):
  `uv pip compile` produces a `uv.lock` equivalent. Fastest, most
  modern, but adds a tooling dependency.

---

### Q5. Pioneer switch `acc-sw-01`

> **Your answer:**

Today the lab has both `acc-sw-01` (the Slice-2 pioneer, ad-hoc name)
and `DEV-HQ-ACC-01` (the Slice-5 HLD-driven name), running side by
side as a "parallel reality" documented in Slice 5 FIX_NOTES §5.

Options:
- **(a)** **Retire `acc-sw-01`** during the migration. Clean slate, only
  HLD-driven device IDs survive. Requires a one-time Neo4j cleanup and
  removal from `clab-ibnlab-switches.yml`.
- **(b)** **Keep `acc-sw-01`** to preserve historical continuity and
  the Slice-2 demo flow. It costs $\sim$500 MB RAM and is harmless.
- **(c)** Defer this decision — handle it in a separate post-migration
  cleanup commit.

---

## Phase summary (post-Q&A)

Once the five answers are in, the migration runs as seven phases:

| Phase | Risk-free on ARM? | Goal |
|---|---|---|
| 1 — Plan + branch scaffolding | yes | This document, finalised |
| 2 — Pin Python deps + image digests | yes | `requirements.lock`, digests in compose / clab |
| 3 — Swap to x86 image variants | partial | FRR upstream image, VyOS choice (Q2) |
| 4 — Strip ARM scaffolding from startup | yes | New `scripts/bootstrap.sh`, `Makefile` |
| 5 — Verify on x86 host | **no** | End-to-end run + measurements |
| 6 — Reproducible-deploy docs | yes | `STEP0_Host_Bootstrap.md` |
| 7 — Squash-merge + tag `v1.0-x86` | n/a | After Phase 5 passes |

---

## Inventory of ARM-specific items (Phase 1 deliverable)

This will be expanded once the questions are answered. Initial scan:

| File | ARM-specific content |
|---|---|
| `start-ibn-lab.sh` (in `$HOME`) | binfmt install, `DOCKER_DEFAULT_PLATFORM=linux/amd64`, `/tmp/ibn-lab` workaround |
| `infra/frr-image/Dockerfile` | Built because `frrouting/frr` is amd64-only — DELETE on x86 |
| `topology_ibn_lab.yml:2` | Comment "ARM64 / containerlab" |
| `clab-ibnlab-switches.yml` | `image: ibn-frr:local` → `frrouting/frr:10.3` |
| `src/ibn/core/clab_yaml.py` `_KIND_MAP` | FRR image string |
| `src/ibn/agents/provisioner.py` `_clab_deploy` | "busy ARM64 host" comment + 600s timeout (may shrink) |
| `CLAUDE.md` user-memory file | ARM-specific lab-startup procedure |
| Multiple `PLAN_Slice*.md` / `FIX_NOTES_Slice*.md` | Historical mentions — leave untouched |

**Do not edit** the FIX_NOTES — they are historical records and must
stay accurate to the ARM-era reality.
