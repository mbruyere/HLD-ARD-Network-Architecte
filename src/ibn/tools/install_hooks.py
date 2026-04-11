"""
Install the IBN closed-loop git hooks into the local repo.

Usage::

    python -m ibn.tools.install_hooks            # install (refuses to overwrite)
    python -m ibn.tools.install_hooks --force    # overwrite an existing hook
    python -m ibn.tools.install_hooks --uninstall

What it does
------------
Symlinks ``infra/hooks/post-commit`` (the canonical, version-controlled
hook script) into ``.git/hooks/post-commit``. The symlink keeps the hook
in sync with the repo — pulling updates the hook automatically.

Why a symlink and not a copy
----------------------------
Git ignores ``.git/hooks/`` (it's not part of the working tree), so a
copy would silently drift from the version-controlled source. A symlink
makes it impossible to forget to update the hook after a pull.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


HOOK_NAME = "post-commit"
SOURCE_REL = Path("infra/hooks") / HOOK_NAME
TARGET_REL = Path(".git/hooks") / HOOK_NAME


def repo_root() -> Path:
    """Walk up from the current working directory to find the git repo root."""
    cur = Path.cwd().resolve()
    for path in [cur] + list(cur.parents):
        if (path / ".git").exists():
            return path
    raise SystemExit(
        "[install_hooks] not inside a git repository — run from the IBN repo root"
    )


def install(force: bool = False) -> int:
    root = repo_root()
    source = root / SOURCE_REL
    target = root / TARGET_REL

    if not source.exists():
        print(f"[install_hooks] hook source missing: {source}", file=sys.stderr)
        return 2

    if not source.stat().st_mode & 0o100:
        print(f"[install_hooks] making {source} executable")
        source.chmod(source.stat().st_mode | 0o755)

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() or target.is_symlink():
        if not force:
            print(
                f"[install_hooks] {target} already exists — use --force to overwrite",
                file=sys.stderr,
            )
            return 1
        target.unlink()

    # Use a relative symlink so the hook keeps working if the repo moves
    rel = os.path.relpath(source, target.parent)
    target.symlink_to(rel)
    print(f"[install_hooks] installed: {target} → {rel}")
    print("[install_hooks] git commits that touch the HLD will now trigger the closed loop")
    return 0


def uninstall() -> int:
    root = repo_root()
    target = root / TARGET_REL
    if not (target.exists() or target.is_symlink()):
        print(f"[install_hooks] no hook installed at {target}")
        return 0
    target.unlink()
    print(f"[install_hooks] removed: {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ibn.tools.install_hooks",
        description="Install or remove the IBN closed-loop post-commit hook.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing hook",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Remove the hook instead of installing it",
    )
    args = parser.parse_args(argv)

    if args.uninstall:
        return uninstall()
    return install(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
