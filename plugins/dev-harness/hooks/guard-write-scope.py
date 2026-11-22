#!/usr/bin/env python3
"""PreToolUse guard on Write/Edit/MultiEdit/NotebookEdit, every session: no write into git hooks,
`.git/config`, the profile's settings or plugins, or the plugin this hook is loaded from.

Bash writes to the same places are out of reach (README Limits).
"""
import json
import os
import re
import sys
from pathlib import Path

PREFIX = "Blocked by dev-harness/guard-write-scope:"
SETTINGS = re.compile(r"settings.*\.json")
PLUGIN_ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def folded_parts(path: str) -> tuple:
    return tuple(part.casefold() for part in Path(path).parts)


def under(parts: tuple, root: str):
    """`parts` below `root`, or None when `parts` is not inside it."""
    base = folded_parts(root)
    return parts[len(base):] if parts[:len(base)] == base else None


def profile_dir() -> str:
    profile = os.environ.get("CLAUDE_CONFIG_DIR", "")
    return os.path.realpath(profile if os.path.isabs(profile) else os.path.expanduser("~/.claude"))


def violation(target: str):
    parts = folded_parts(target)
    for i, part in enumerate(parts):
        # `.git/hooks` and `.git/modules/<sub>/hooks` alike.
        if part == "hooks" and ".git" in parts[:i]:
            return "git hooks"
    if parts[-2:] == (".git", "config"):
        return "git config"
    inside = under(parts, profile_dir())
    if inside and (inside[0] == "plugins" or (len(inside) == 1 and SETTINGS.fullmatch(inside[0]))):
        return "the profile's settings or plugins"
    if under(parts, PLUGIN_ROOT) is not None:
        return "the loaded dev-harness plugin"
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin.buffer)
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return
    cwd = payload.get("cwd") or os.getcwd()
    target = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    reason = violation(target)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{PREFIX} writes to {reason} are not allowed ({path})",
        }}))


main()
