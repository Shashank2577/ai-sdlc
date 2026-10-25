#!/usr/bin/env python3
"""A local stand-in for `gh` during a behavioural eval.

The session under test runs real `gh` commands against a work item and a
pull request that exist only in the eval's state directory. Every call is
appended to `gh-calls.jsonl` there, with the body of any `--body-file`, so
the grader judges what the session actually did to the tracker instead of
what it says it did. Nothing reaches GitHub.

Reads EVAL_STATE (the state directory) and runs git in the current
directory, which is the eval's throwaway product repo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ["EVAL_STATE"])
FIXTURE = json.loads((STATE / "fixture.json").read_text())
LABELS = STATE / "labels.json"


def log(argv: list[str], **extra) -> None:
    with open(STATE / "gh-calls.jsonl", "a") as f:
        f.write(json.dumps({"argv": argv, **extra}) + "\n")


def opt(argv: list[str], *names: str) -> list[str]:
    """Every value given for any of `names` (`--x v` or `--x=v`)."""
    vals = []
    for i, a in enumerate(argv):
        for n in names:
            if a == n and i + 1 < len(argv):
                vals.append(argv[i + 1])
            elif a.startswith(n + "="):
                vals.append(a.split("=", 1)[1])
    return vals


def body_of(argv: list[str]) -> str | None:
    files = opt(argv, "--body-file", "-F")
    if files:
        return sys.stdin.read() if files[0] == "-" else Path(files[0]).read_text()
    bodies = opt(argv, "--body", "-b")
    return bodies[0] if bodies else None


def labels() -> list[str]:
    return json.loads(LABELS.read_text()) if LABELS.exists() else list(FIXTURE["issue"]["labels"])


def emit(obj, argv: list[str]) -> None:
    """Print JSON, through `jq -r` when the caller passed -q/--jq."""
    jq = opt(argv, "-q", "--jq")
    text = json.dumps(obj, indent=2)
    if jq and shutil.which("jq"):
        sys.stdout.write(subprocess.run(["jq", "-r", jq[0]], input=text, text=True,
                                        capture_output=True).stdout)
    else:
        print(text)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def pr_for(argv: list[str]) -> dict | None:
    prs = FIXTURE.get("prs", [])
    nums = [a.lstrip("#") for a in argv[2:] if a.lstrip("#").isdigit()]
    if nums:
        return next((p for p in prs if str(p["number"]) == nums[0]), None)
    branch = git("branch", "--show-current").strip()
    return next((p for p in prs if p["headRefName"] == branch), prs[0] if prs else None)


def issue_json() -> dict:
    issue = FIXTURE["issue"]
    comments = []
    if (STATE / "comments.jsonl").exists():
        comments = [json.loads(l) for l in (STATE / "comments.jsonl").read_text().splitlines()]
    return {"number": issue["number"], "title": issue["title"], "body": issue["body"],
            "state": "OPEN", "labels": [{"name": n} for n in labels()],
            "comments": comments, "url": f"https://github.com/{FIXTURE['control_plane']}/issues/{issue['number']}"}


def main(argv: list[str]) -> int:
    cmd = " ".join(argv[:2])
    body = body_of(argv) if cmd in ("issue comment", "issue create", "pr create", "pr edit",
                                    "pr comment", "pr review") else None
    log(argv, body=body, branch=git("branch", "--show-current").strip())

    if cmd == "issue view":
        data = issue_json()
        if opt(argv, "--json"):
            emit(data, argv)
        else:
            print(f"title:\t{data['title']}\nlabels:\t{', '.join(labels())}\n--\n{data['body']}")
            if "--comments" in argv:
                for c in data["comments"]:
                    print(f"--\n{c['body']}")
        return 0
    if cmd == "issue edit":
        current = labels()
        for spec in opt(argv, "--add-label"):
            current += [l.strip() for l in spec.split(",") if l.strip() not in current]
        for spec in opt(argv, "--remove-label"):
            drop = {l.strip() for l in spec.split(",")}
            current = [l for l in current if l not in drop]
        LABELS.write_text(json.dumps(current))
        print(issue_json()["url"])
        return 0
    if cmd == "issue comment":
        with open(STATE / "comments.jsonl", "a") as f:
            f.write(json.dumps({"body": body or ""}) + "\n")
        print(issue_json()["url"] + "#issuecomment-1")
        return 0
    if cmd == "issue create":
        print(f"https://github.com/{FIXTURE['control_plane']}/issues/900")
        return 0
    if cmd == "pr list":
        emit(FIXTURE.get("prs", []), argv)
        return 0
    if cmd in ("pr view", "pr diff", "pr checkout", "pr checks"):
        pr = pr_for(argv)
        if pr is None:
            print("no pull requests found for branch", file=sys.stderr)
            return 1
        if cmd == "pr view":
            if opt(argv, "--json"):
                emit(pr, argv)
            else:
                print(f"title:\t{pr['title']}\nstate:\t{pr['state']}\nbranch:\t{pr['headRefName']}\n"
                      f"url:\t{pr['url']}\n--\n{pr['body']}")
        elif cmd == "pr diff":
            sys.stdout.write(git("diff", f"main...{pr['headRefName']}"))
        elif cmd == "pr checkout":
            r = subprocess.run(["git", "checkout", pr["headRefName"]])
            return r.returncode
        else:
            print("test\tpass\t12s\thttps://example.invalid/checks")
        return 0
    if cmd == "pr create":
        print(f"https://github.com/{FIXTURE['product_repo']}/pull/13")
        return 0
    if cmd in ("pr edit", "pr comment", "pr review", "label list", "label create"):
        return 0
    if cmd == "auth status":
        print("Logged in to github.com (eval stub)")
        return 0
    print(f"gh {cmd}: not available in this eval", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
