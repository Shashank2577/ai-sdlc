"""The control plane's identity, read from `foundry.yaml` (#324).

    from foundry_config import control_plane
    control_plane()          # control_plane.repo from foundry.yaml, e.g. "owner/repo"

Every default that used to be a literal owner/repo reads from here, so a
fork edits one file. Parsed without PyYAML when it is missing: several
workflows that read a default here never install it, and the file is
three flat keys.
"""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "foundry.yaml"


@functools.lru_cache(maxsize=None)
def load(path: Path = CONFIG_PATH) -> dict:
    text = path.read_text()
    try:
        import yaml
        data = yaml.safe_load(text) or {}
    except ImportError:
        section = text.split("control_plane:", 1)[1] if "control_plane:" in text else ""
        data = {"control_plane": {k: v for k, v in
                                  re.findall(r"^\s+(repo|product|owner_kind):\s*(\S+)", section, re.M)}}
    cp = data.get("control_plane") or {}
    if "/" not in str(cp.get("repo", "")):
        raise SystemExit(f"{path.name}: control_plane.repo must be `owner/name`")
    return {"repo": cp["repo"], "product": cp.get("product") or cp["repo"].split("/")[1],
            "owner_kind": cp.get("owner_kind") or "users"}


def control_plane() -> str:
    return os.environ.get("FOUNDRY_CONTROL_PLANE") or load()["repo"]


def owner() -> str:
    return control_plane().split("/")[0]


def control_plane_product() -> str:
    return load()["product"]


def repo_url() -> str:
    return f"https://github.com/{control_plane()}"


def pages_url() -> str:
    name = control_plane().split("/")[1]
    return f"https://{owner().lower()}.github.io/{name}"


def board_url(number: int) -> str:
    return f"https://github.com/{load()['owner_kind']}/{owner()}/projects/{number}"
