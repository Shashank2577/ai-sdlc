#!/usr/bin/env python3
"""Mirror a built site into a persistent branch, for the parts of the
dashboards Pages pipeline that a plain `actions/deploy-pages` call can't do
by itself: giving `staging` a URL distinct from `prod`'s, and giving `prod`
a real previous artifact to roll back to.

Used by `.github/workflows/dashboards.yml` (`staging`, `prod`) and
`.github/workflows/pages-rollback.yml`. Two subcommands:

    deploy-pages.py publish --branch pages-staging --source site \\
        --message "staging candidate -- run 123, source abc1234"

        Replace <branch>'s tracked tree with the contents of --source and
        commit, creating <branch> as an orphan if it does not exist yet.
        No-op (prints `changed=False`, exits 0) if the tree already
        matches -- e.g. a rebuild of an unchanged site.

    deploy-pages.py rollback --branch pages-live --commits-back 1

        Reconstruct the tree as it was `--commits-back` release commits
        ago, as a *new* commit on <branch> -- never a history rewrite, so
        the run being rolled back from stays in the log. Fails loudly if
        <branch> doesn't have enough history to roll back that far.

Neither subcommand pushes; the calling workflow does that (and then runs
the actual Pages deploy) once this exits 0, so a failed mirror never
leaves a half-pushed branch.

This operates via a separate `git worktree`, not the checkout the caller
is already standing in -- swapping the calling job's own branch out from
under it would delete the very scripts/workflow files driving the run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def ensure_worktree(branch: str, worktree_dir: Path) -> bool:
    """Set up `worktree_dir` as a checkout of `branch`. Returns whether the
    branch already existed on origin (False means it was created here, as
    an orphan)."""
    if worktree_dir.exists():
        run(["git", "worktree", "remove", "--force", str(worktree_dir)], check=False)
        shutil.rmtree(worktree_dir, ignore_errors=True)
    run(["git", "worktree", "prune"])

    fetch = run(["git", "fetch", "origin", branch], check=False)
    branch_exists = fetch.returncode == 0
    if branch_exists:
        run(["git", "branch", "-f", branch, f"origin/{branch}"])
        run(["git", "worktree", "add", str(worktree_dir), branch])
    else:
        run(["git", "worktree", "add", "--orphan", "-b", branch, str(worktree_dir)])
    return branch_exists


def mirror_tree(worktree_dir: Path, source_dir: Path) -> None:
    for item in worktree_dir.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for item in source_dir.iterdir():
        dest = worktree_dir / item.name
        shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)


def commit_if_changed(worktree_dir: Path, message: str) -> bool:
    run(["git", "add", "-A"], cwd=worktree_dir)
    status = run(["git", "status", "--porcelain"], cwd=worktree_dir)
    if not status.stdout.strip():
        return False
    run(["git", "commit", "--quiet", "-m", message], cwd=worktree_dir)
    return True


def cmd_publish(args: argparse.Namespace) -> int:
    ensure_worktree(args.branch, args.worktree_dir)
    mirror_tree(args.worktree_dir, args.source)
    changed = commit_if_changed(args.worktree_dir, args.message)
    print(f"branch={args.branch} changed={changed}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    exists = ensure_worktree(args.branch, args.worktree_dir)
    if not exists:
        sys.exit(f"rollback: {args.branch!r} does not exist on origin -- nothing to roll back")

    log = run(["git", "log", "--format=%H", "-n", str(args.commits_back + 1)], cwd=args.worktree_dir)
    commits = log.stdout.split()
    if len(commits) <= args.commits_back:
        sys.exit(
            f"rollback: {args.branch!r} has only {len(commits)} release commit(s) -- "
            f"cannot go back {args.commits_back}"
        )
    current, target = commits[0], commits[args.commits_back]

    current_files = set(run(["git", "ls-tree", "-r", "--name-only", current], cwd=args.worktree_dir).stdout.split())
    target_files = set(run(["git", "ls-tree", "-r", "--name-only", target], cwd=args.worktree_dir).stdout.split())
    to_remove = sorted(current_files - target_files)
    if to_remove:
        run(["git", "rm", "-q", "--"] + to_remove, cwd=args.worktree_dir)
    if target_files:
        run(["git", "checkout", target, "--", "."], cwd=args.worktree_dir)

    message = args.message or f"rollback: restore release {target[:12]}, undoing {current[:12]}"
    changed = commit_if_changed(args.worktree_dir, message)
    print(f"branch={args.branch} restored={target} from={current} changed={changed}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--branch", required=True, help="persistent branch to mirror into")
    common.add_argument("--worktree-dir", type=Path, default=Path(".worktree-deploy-pages"))

    pub = sub.add_parser("publish", parents=[common])
    pub.add_argument("--source", type=Path, required=True, help="directory whose contents become the branch's tree")
    pub.add_argument("--message", required=True)
    pub.set_defaults(func=cmd_publish)

    roll = sub.add_parser("rollback", parents=[common])
    roll.add_argument("--commits-back", type=int, default=1)
    roll.add_argument("--message", default=None)
    roll.set_defaults(func=cmd_rollback)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
