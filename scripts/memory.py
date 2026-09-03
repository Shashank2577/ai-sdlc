#!/usr/bin/env python3
"""Engineering memory — the git notes store (REQ-013, #119).

Split from #54: this is the store half only. Prompt assembly at dispatch
time (reading these notes into a session's context) is #120, devops scope,
because that lives in `.github/workflows/dispatch.yml`.

Sessions are disposable; what one tried and rejected dies with the runner
unless it lands somewhere durable. Git notes on `refs/notes/foundry` are
that place: attached to a commit, versioned with the repo, and — unlike a
PR body — greppable and fetchable without hitting the tracker's API.

A note is a plain key: value block, not JSON or YAML, so `search` can grep
it with a substring match and a human can read one with `git notes show`
and no tooling at all:

    Work-Item: <owner>/<repo>#<issue>
    Requirement: REQ-0XX
    Tried: what was tried and rejected
    Gotcha: the thing worth knowing next time

Notes live on `refs/notes/foundry`, not git's default `refs/notes/commits`,
so they need `--ref` on every git-notes invocation — this module always
passes it explicitly rather than relying on git's default.

    memory.py write <commit> --work-item OWNER/REPO#N --tried TEXT --gotcha TEXT
    memory.py read (--commit <commit> | --path <path>)
    memory.py search <query>

Exit 0 in every case except a genuine usage error: a missing note is an
absence, not a failure, and an empty notes tree is a repo with no memory
yet, not a broken one.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_REF = "refs/notes/foundry"


class GitError(RuntimeError):
    """A git invocation failed for a reason other than 'note not found'."""


def _git(args: list[str], repo: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def format_note(work_item: str, tried: str, gotcha: str, requirement: str | None = None) -> str:
    lines = [f"Work-Item: {work_item}"]
    if requirement:
        lines.append(f"Requirement: {requirement}")
    lines.append(f"Tried: {tried}")
    lines.append(f"Gotcha: {gotcha}")
    return "\n".join(lines) + "\n"


def write_note(
    commit: str,
    work_item: str,
    tried: str,
    gotcha: str,
    requirement: str | None = None,
    ref: str = DEFAULT_REF,
    repo: str | None = None,
) -> str:
    """Attach a note to `commit` under `ref`, overwriting any prior note.

    `-f` is deliberate: a session that revisits a commit (rare, but the
    dispatcher's session-end step could retry) should replace the note,
    not fail with "a note already exists".
    """
    body = format_note(work_item, tried, gotcha, requirement)
    _git(["notes", f"--ref={ref}", "add", "-f", "-m", body, commit], repo=repo)
    return body


def read_note(commit: str, ref: str = DEFAULT_REF, repo: str | None = None) -> str | None:
    """Return the note body for `commit`, or None if it has no note.

    `git notes show` exits 1 for "no note found" — that is absence, not an
    error, so it is swallowed here rather than raised.
    """
    result = _git(["notes", f"--ref={ref}", "show", commit], repo=repo, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def read_path(path: str, ref: str = DEFAULT_REF, repo: str | None = None) -> list[tuple[str, str]]:
    """Return (commit, note) pairs for every commit touching `path` that has one."""
    log = _git(["log", "--format=%H", "--", path], repo=repo, check=False)
    notes = []
    for commit in log.stdout.split():
        note = read_note(commit, ref=ref, repo=repo)
        if note is not None:
            notes.append((commit, note))
    return notes


def search_notes(query: str, ref: str = DEFAULT_REF, repo: str | None = None) -> list[tuple[str, str]]:
    """Return (commit, note) pairs whose note body contains `query`.

    `git notes list` on a ref that has never been written to still exits 0
    with empty output — verified against a real repo, not assumed — so an
    empty notes tree needs no special-casing here.
    """
    result = _git(["notes", f"--ref={ref}", "list"], repo=repo, check=False)
    matches = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        _note_blob, commit = parts
        note = read_note(commit, ref=ref, repo=repo)
        if note and query.lower() in note.lower():
            matches.append((commit, note))
    return matches


def _cmd_write(args: argparse.Namespace) -> int:
    write_note(
        args.commit,
        work_item=args.work_item,
        tried=args.tried,
        gotcha=args.gotcha,
        requirement=args.requirement,
        ref=args.ref,
        repo=args.repo,
    )
    print(f"noted {args.commit} on {args.ref}")
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    if args.commit:
        note = read_note(args.commit, ref=args.ref, repo=args.repo)
        if note is not None:
            print(note, end="")
        return 0
    notes = read_path(args.path, ref=args.ref, repo=args.repo)
    for commit, note in notes:
        print(f"# {commit}")
        print(note)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    matches = search_notes(args.query, ref=args.ref, repo=args.repo)
    for commit, note in matches:
        print(f"# {commit}")
        print(note)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory.py",
        description="Engineering memory store on refs/notes/foundry.",
    )
    parser.add_argument("--repo", default=None, help="repo path (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="attach a note to a commit")
    p_write.add_argument("commit")
    p_write.add_argument("--work-item", required=True, help="owner/repo#issue")
    p_write.add_argument("--tried", required=True, help="what was tried and rejected")
    p_write.add_argument("--gotcha", required=True, help="the thing worth knowing next time")
    p_write.add_argument("--requirement", default=None, help="REQ-0XX, comma-separated if several")
    p_write.add_argument("--ref", default=DEFAULT_REF)
    p_write.set_defaults(func=_cmd_write)

    p_read = sub.add_parser("read", help="retrieve notes for a commit or a path")
    target = p_read.add_mutually_exclusive_group(required=True)
    target.add_argument("--commit")
    target.add_argument("--path")
    p_read.add_argument("--ref", default=DEFAULT_REF)
    p_read.set_defaults(func=_cmd_read)

    p_search = sub.add_parser("search", help="grep the notes tree")
    p_search.add_argument("query")
    p_search.add_argument("--ref", default=DEFAULT_REF)
    p_search.set_defaults(func=_cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GitError as exc:
        print(f"memory.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
