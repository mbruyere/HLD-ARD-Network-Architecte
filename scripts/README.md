# scripts/

## `install_x86.sh`

One-shot bootstrap for a fresh Ubuntu amd64 host. Run from any new
x86 VM with curl:

```bash
curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh | bash
```

Or with options (`--with-claude`, `--skip-images`, `--dry-run`,
`--branch <name>`):

```bash
curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh -o install_x86.sh
bash install_x86.sh --with-claude
```

### What it does

1. Preflight: arch must be `x86_64`, user must be non-root with sudo,
   25 GB+ free disk, 8 GB+ RAM.
2. Installs apt base (curl, git, build-essential, python3.12 + venv,
   jq, etc.).
3. Installs Docker CE from the official repo and adds the user to the
   `docker` group.
4. Installs containerlab via `get.containerlab.dev`.
5. Installs `gh` CLI.
6. Clones two repos under `$HOME/`:
   - `HLD-ARD-Network-Architecte` (branch: `x86-migration` by default)
   - `graph-memory` (for `ibn-graph-memory:local` build)
   The paper repo (`ibn-closed-loop-paper`) is **not** cloned — it
   lives in its own repo with its own lifecycle. Clone it separately
   if you need it on this host.
7. Creates the Python venv and `pip install -r requirements.txt`.
8. Pulls all pinned container images (`--skip-images` to skip).
9. Builds local images: `ibn-graph-memory:local` and the
   `embedding-proxy` Compose service.
10. (Optional, `--with-claude`) installs Claude Code.
11. Prints the three manual steps that only the operator can do:
    - Drop `.env` secrets into place
    - `gh auth login`
    - `claude` first-run auth

### What it does NOT do

- Does not pull or restore Neo4j / MinIO / Qdrant state. The smoke
  test starts from an empty graph by design.
- Does not run the pipeline. It prints the smoke-test commands but
  leaves execution to the operator (after `.env` is in place).
- Does not install `ibn-frr:local` (custom ARM Dockerfile) — on x86 we
  use upstream `frrouting/frr:10.3`. The clab YAML is updated as part
  of Phase 3 of `PLAN_X86_Migration.md`.
- Does not install `tonistiigi/binfmt`. No QEMU emulation on x86.

### Idempotency

Safe to re-run. Detects existing tools and re-clone-pull instead of
re-cloning. `--dry-run` prints what would happen without touching the
host.
