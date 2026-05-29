# scripts/

## `install_x86.sh`

One-shot bootstrap for a fresh Ubuntu amd64 host. Run from any new
x86 VM with curl:

```bash
curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh | bash
```

Or with options (`--with-latex`, `--with-claude`, `--skip-images`,
`--dry-run`, `--branch <name>`):

```bash
curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh -o install_x86.sh
bash install_x86.sh --with-latex --with-claude
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
6. (Optional, `--with-latex`) installs `texlive-publishers`,
   `texlive-fonts-recommended`, `texlive-latex-extra`, `latexmk`.
7. Clones three repos under `$HOME/`:
   - `HLD-ARD-Network-Architecte` (branch: `x86-migration` by default)
   - `ibn-closed-loop-paper` (branch: `main`)
   - `graph-memory` (for `ibn-graph-memory:local` build)
8. Creates the Python venv and `pip install -r requirements.txt`.
9. Pulls all pinned container images (`--skip-images` to skip).
10. Builds local images: `ibn-graph-memory:local` and the
    `embedding-proxy` Compose service.
11. (Optional, `--with-claude`) installs Claude Code.
12. Prints the three manual steps that only the operator can do:
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
