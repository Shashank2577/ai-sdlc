#!/usr/bin/env python3
"""Report which role pack(s), if any, may write to each top-level directory
that has committed code.

`portal/**` and `adapters/**` existed, were written by developer sessions
(#162, #135, #166), and were in no pack's `write_scope.allow` at all
(#190) — nothing objected while they were written, and every future story
naming a path in either would have been flagged as out-of-scope by
`check-story-scope.py` (#168) for whichever role actually did the work.
That gap was found by accident; this is the check that finds the next one
on purpose.

Reuses `check-story-scope.py`'s `capable_roles`, which already asks each
pack's own policy whether it could write a given path — a second matcher
that can disagree with the first is worse than none.

    check-pack-coverage.py                        # `git ls-files`, exit 1
                                                    # if any directory has
                                                    # no capable role
    check-pack-coverage.py --paths a/b.py c/d.py   # explicit file list,
                                                    # no git call — the test
                                                    # seam

Deliberately silent on directories claimed by *more than one* pack
(`ceremonies/**` is currently both delivery-lead's and orchestrator's,
`scripts/**` is both developer's and, narrowly, devops's) — that is a
different, pre-existing question this script was not asked to answer, and
flagging it here would bury the zero-owner case this exists to catch.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO_ROOT / "role-packs"

_spec = importlib.util.spec_from_file_location(
    "check_story_scope", Path(__file__).resolve().parent / "check-story-scope.py")
check_story_scope = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("check_story_scope", check_story_scope)
_spec.loader.exec_module(check_story_scope)


def top_level_dirs(paths: list[str]) -> list[str]:
    """The first path segment of every committed file that has one — a
    file at the repo root (README.md) names no directory and is dropped.
    """
    return sorted({p.split("/", 1)[0] for p in paths if "/" in p})


def analyze(paths: list[str], packs_dir: Path = PACKS_DIR) -> dict[str, list[str]]:
    """Every top-level directory with committed code, mapped to the roles
    whose own pack could write it (checked as `<dir>/`, the directory
    itself). An empty list means no pack claims it.
    """
    return {d: check_story_scope.capable_roles(f"{d}/", packs_dir)
            for d in top_level_dirs(paths)}


def render_report(coverage: dict[str, list[str]]) -> str:
    lines = ["### Pack coverage", ""]
    for d in sorted(coverage):
        roles = coverage[d]
        who = ", ".join(f"`{r}`" for r in roles) if roles else "**no pack**"
        lines.append(f"- `{d}/` — {who}")

    unclaimed = sorted(d for d, roles in coverage.items() if not roles)
    if unclaimed:
        lines.append("")
        lines.append(
            "Unclaimed: " + ", ".join(f"`{d}/`" for d in unclaimed) + ". "
            "Either add it to a pack's `write_scope.allow`, or state on the "
            "PR why it is deliberately claimed by none.")
    return "\n".join(lines) + "\n"


def git_tracked_paths() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, check=True,
                         capture_output=True, text=True).stdout
    return out.splitlines()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paths", nargs="*",
                    help="file list to check instead of `git ls-files` (tests only)")
    args = ap.parse_args()

    paths = args.paths if args.paths is not None else git_tracked_paths()
    coverage = analyze(paths)
    print(render_report(coverage))
    return 1 if any(not roles for roles in coverage.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
