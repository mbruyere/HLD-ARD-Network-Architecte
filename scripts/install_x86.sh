#!/usr/bin/env bash
#
# IBN Closed-Loop — fresh Ubuntu amd64 bootstrap
# ==============================================
#
# One-shot installer for the x86 VM migration. Idempotent, safe to
# re-run. Takes an empty Ubuntu 24.04/26.04 amd64 host to a working
# state with all dependencies, both repos cloned, and a Python venv
# ready for `claude` to take over.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh | bash
#
# Or with options (download first, do not pipe):
#   curl -fsSL https://raw.githubusercontent.com/mbruyere/HLD-ARD-Network-Architecte/x86-migration/scripts/install_x86.sh -o install_x86.sh
#   bash install_x86.sh --with-latex --with-claude
#
# Flags (all optional):
#   --with-latex     Install texlive for paper builds (~1 GB).
#   --with-claude    Run the Claude Code installer at the end.
#   --skip-images    Do not pull container images (saves ~15 GB but
#                    smoke test will fail until you pull manually).
#   --dry-run        Print what would be done, do nothing.
#   --branch <name>  Project branch to check out (default: x86-migration).
#
# Inputs the script CANNOT generate for you:
#   - /home/$USER/HLD-ARD-Network-Architecte/.env  (your secrets)
#   - GitHub auth                                  (`gh auth login`)
#   - Claude Code auth                             (`claude` first run)
#
# Each of these will be flagged at the end of the run.
#

set -Eeuo pipefail

# ---------- config ----------------------------------------------------------
PROJECT_REPO="https://github.com/mbruyere/HLD-ARD-Network-Architecte.git"
PAPER_REPO="https://github.com/mbruyere/ibn-closed-loop-paper.git"
GRAPH_MEMORY_REPO="https://github.com/Cloud-Temple/graph-memory.git"

PROJECT_DIR_NAME="HLD-ARD-Network-Architecte"
PAPER_DIR_NAME="ibn-closed-loop-paper"
GM_DIR_NAME="graph-memory"

PYTHON_BIN="python3"                  # use whatever the distro ships (3.12+ supported)
DEFAULT_BRANCH="x86-migration"

# Container images we pre-pull. ibn-frr is intentionally NOT in this
# list — on x86 we use upstream frrouting/frr (Phase 3 of the plan).
IMAGES_TO_PULL=(
  "ghcr.io/nokia/srlinux:latest"
  "ghcr.io/sysoleg/vyos-container:latest"
  "ghcr.io/cloud-temple/live-memory:latest"
  "frrouting/frr:10.3"
  "neo4j:5-community"
  "qdrant/qdrant:v1.16.0"
  "redis:7-alpine"
  "minio/minio:latest"
  "minio/mc:latest"
  "python:3.13-alpine"
)

# ---------- flags ----------------------------------------------------------
WITH_LATEX=0
WITH_CLAUDE=0
SKIP_IMAGES=0
DRY_RUN=0
BRANCH="$DEFAULT_BRANCH"

while [ "${1:-}" != "" ]; do
  case "$1" in
    --with-latex)   WITH_LATEX=1 ;;
    --with-claude)  WITH_CLAUDE=1 ;;
    --skip-images)  SKIP_IMAGES=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    --branch)       shift; BRANCH="${1:-$DEFAULT_BRANCH}" ;;
    -h|--help)
      sed -n '/^# Usage:/,/^# Inputs/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

# ---------- helpers --------------------------------------------------------
BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; RST=$'\e[0m'

step() { printf '%s==> %s%s\n' "$BOLD" "$*" "$RST"; }
info() { printf '    %s%s%s\n' "$DIM" "$*" "$RST"; }
warn() { printf '    %s%s%s\n' "$YEL" "$*" "$RST"; }
ok()   { printf '    %s%s%s\n' "$GRN" "$*" "$RST"; }
fail() { printf '%s!!  %s%s\n' "$RED" "$*" "$RST" >&2; exit 1; }

run() {
  if [ "$DRY_RUN" = 1 ]; then
    info "DRY: $*"
  else
    info "+ $*"
    eval "$@"
  fi
}

need_sudo() {
  if ! sudo -n true 2>/dev/null; then
    warn "sudo will prompt for your password"
    sudo true
  fi
}

# ---------- preflight ------------------------------------------------------
step "Preflight checks"

[ "$(uname -m)" = "x86_64" ] || \
  fail "this host is $(uname -m); install_x86.sh is for x86_64 only"
ok "architecture: x86_64"

if ! command -v lsb_release >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq lsb-release
fi
OS="$(lsb_release -is 2>/dev/null || echo unknown)"
[ "$OS" = "Ubuntu" ] || warn "OS is $OS; this script was tested only on Ubuntu"
ok "OS: $(lsb_release -ds 2>/dev/null || echo unknown)"

[ "$(id -u)" -ne 0 ] || \
  fail "do not run as root — use a normal user with sudo access"
ok "user: $USER (non-root)"

need_sudo

FREE_GB=$(df -BG / | tail -1 | awk '{gsub("G",""); print $4}')
[ "$FREE_GB" -ge 25 ] || warn "only ${FREE_GB}G free on /; 25G+ recommended"
ok "disk free: ${FREE_GB}G on /"

MEM_GB=$(free -g | awk 'NR==2{print $2}')
[ "$MEM_GB" -ge 8 ] || warn "only ${MEM_GB}G RAM; 8G+ recommended"
ok "memory: ${MEM_GB}G"

# ---------- system packages ------------------------------------------------
step "System packages (apt)"

APT_BASE=(
  curl ca-certificates gnupg lsb-release software-properties-common
  git build-essential jq tree htop iputils-ping unzip rsync
  python3 python3-venv python3-dev python3-pip
)

run "sudo apt-get update -qq"
run "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ${APT_BASE[*]}"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN still missing after apt install"

PY_VER=$($PYTHON_BIN -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ok "python: $($PYTHON_BIN --version 2>&1) (= $PY_VER)"

# Project requires >= 3.12 (pygnmi, BaseAgent dual-sink helpers, asyncio
# patterns). Ubuntu 24.04 ships 3.12; 26.04 ships 3.14 — both supported.
PY_MAJOR=${PY_VER%%.*}; PY_MINOR=${PY_VER##*.}
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
  fail "python3 is $PY_VER; project requires >= 3.12"
fi

# ---------- Docker CE ------------------------------------------------------
step "Docker CE"

if command -v docker >/dev/null 2>&1; then
  ok "docker present: $(docker --version)"
else
  info "installing Docker CE from the official repo"

  # Source /etc/os-release in *this* shell to populate VERSION_CODENAME.
  # We accept whatever the host advertises; if Docker doesn't yet
  # publish for that codename we fall back to "noble" (24.04 LTS),
  # which is binary-compatible with later Ubuntu releases.
  # shellcheck disable=SC1091
  . /etc/os-release
  CODENAME="${VERSION_CODENAME:-noble}"
  info "Ubuntu codename: $CODENAME"

  if ! curl -fsSI "https://download.docker.com/linux/ubuntu/dists/$CODENAME/Release" >/dev/null 2>&1; then
    warn "Docker has no apt release for '$CODENAME' yet — falling back to 'noble'"
    CODENAME="noble"
  fi

  run "sudo install -m 0755 -d /etc/apt/keyrings"
  run "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg"
  run "sudo chmod a+r /etc/apt/keyrings/docker.gpg"
  run "echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODENAME stable' | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null"
  run "sudo apt-get update -qq"
  run "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
fi

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  run "sudo usermod -aG docker $USER"
  warn "added $USER to docker group — you must log out + back in (or 'newgrp docker') for it to take effect"
fi

# ---------- containerlab ---------------------------------------------------
step "containerlab"
if command -v containerlab >/dev/null 2>&1; then
  ok "containerlab present: $(containerlab version 2>&1 | head -1)"
else
  run "bash -c 'curl -sL https://get.containerlab.dev | sudo -E bash'"
fi

# ---------- GitHub CLI -----------------------------------------------------
step "GitHub CLI (gh)"
if command -v gh >/dev/null 2>&1; then
  ok "gh present: $(gh --version | head -1)"
else
  run "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gh"
fi

# ---------- LaTeX (optional) -----------------------------------------------
if [ "$WITH_LATEX" = 1 ]; then
  step "LaTeX (for paper builds)"
  run "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
       texlive-publishers texlive-fonts-recommended texlive-latex-extra latexmk"
fi

# ---------- clone repos ----------------------------------------------------
step "Clone repositories under \$HOME"

clone_or_pull() {
  local repo="$1" dir="$2" branch="${3:-}"
  cd "$HOME"
  if [ -d "$dir/.git" ]; then
    info "$dir exists — fetching latest"
    run "git -C '$HOME/$dir' fetch --all --quiet"
    [ -n "$branch" ] && run "git -C '$HOME/$dir' checkout '$branch'"
    run "git -C '$HOME/$dir' pull --ff-only --quiet || true"
  else
    run "git clone --quiet '$repo' '$HOME/$dir'"
    [ -n "$branch" ] && run "git -C '$HOME/$dir' checkout '$branch'"
  fi
}

clone_or_pull "$PROJECT_REPO"      "$PROJECT_DIR_NAME"      "$BRANCH"
clone_or_pull "$PAPER_REPO"        "$PAPER_DIR_NAME"        "main"
clone_or_pull "$GRAPH_MEMORY_REPO" "$GM_DIR_NAME"           ""

ok "all three repos under $HOME/"

# ---------- Python venv ----------------------------------------------------
step "Python venv + requirements"

cd "$HOME/$PROJECT_DIR_NAME"
if [ ! -d .venv ]; then
  run "$PYTHON_BIN -m venv .venv"
fi
run ". .venv/bin/activate && pip install --quiet --upgrade pip"
run ". .venv/bin/activate && pip install --quiet -r requirements.txt"
ok "venv ready: $HOME/$PROJECT_DIR_NAME/.venv"

# ---------- container images -----------------------------------------------
if [ "$SKIP_IMAGES" = 1 ]; then
  step "Container images — skipped (--skip-images)"
else
  step "Pull container images"
  for img in "${IMAGES_TO_PULL[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      info "already present: $img"
    else
      run "docker pull --quiet '$img'"
    fi
  done

  step "Build local images"
  cd "$HOME/$GM_DIR_NAME"
  if docker image inspect ibn-graph-memory:local >/dev/null 2>&1; then
    info "ibn-graph-memory:local already built"
  else
    run "docker build --quiet -t ibn-graph-memory:local ."
  fi

  cd "$HOME/$PROJECT_DIR_NAME"
  run "docker compose build --quiet embedding-proxy"
fi

# ---------- Claude Code (optional) -----------------------------------------
if [ "$WITH_CLAUDE" = 1 ]; then
  step "Claude Code"
  if command -v claude >/dev/null 2>&1; then
    ok "claude present: $(claude --version 2>/dev/null || echo installed)"
  else
    info "installing Claude Code"
    run "curl -fsSL https://claude.ai/install.sh | bash"
  fi
fi

# ---------- next-step instructions -----------------------------------------
step "Bootstrap complete — manual follow-up needed"
cat <<EOF

  ${BOLD}Three things only you can do:${RST}

  1. ${BOLD}.env${RST}    Drop your secrets into
        ${HOME}/${PROJECT_DIR_NAME}/.env
     A template is in .env.example. Required keys: NEO4J_PASSWORD,
     LLMAAS_API_KEY, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD,
     GITHUB_TOKEN (if used by tooling). Capture these from the
     ARM VM's existing .env before you decommission it.

  2. ${BOLD}gh auth login${RST}    Authenticate gh CLI so you can push:
        gh auth login

  3. ${BOLD}claude${RST}           First-run authentication for Claude Code:
        claude
     (skipped here unless you re-ran with --with-claude)

  ${BOLD}Then run the smoke test:${RST}
        cd ${HOME}/${PROJECT_DIR_NAME}
        source .venv/bin/activate
        docker compose up -d
        PYTHONPATH=src python -m pytest tests/unit/ -q
        sudo clab deploy --reconfigure -t clab-ibnlab-switches.yml
        PYTHONPATH=src python -m ibn.pipeline.hld_commit \\
            --commit \$(git rev-parse HEAD) \\
            --hld tests/fixtures/sample_hlds/hld_03_small_campus.md

  Branch checked out: ${BOLD}${BRANCH}${RST}
  Repo:               ${HOME}/${PROJECT_DIR_NAME}
  Paper:              ${HOME}/${PAPER_DIR_NAME}
  Graph-Memory src:   ${HOME}/${GM_DIR_NAME}

EOF

ok "DONE"
