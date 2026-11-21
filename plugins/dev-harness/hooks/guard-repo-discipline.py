#!/usr/bin/env python3
"""PreToolUse(Bash): refuse the commands CLAUDE.md's standing rules forbid outright.

Blocked: `git add -A|--all|.`, `git commit -a|--all`, `git checkout [<tree>] -- <path>`,
`git checkout .`, and `screencapture` without -R or -l (window-scoped).
Allowed: staging by file, branch switches, and text that is only quoted, commented or in
a heredoc body.
Not a sandbox: `bash -c "..."`, `eval` and `xargs` are not looked into.
"""
import json
import re
import sys

from lib.shell_text import command_segments

GIT_ADD = (
    "Blocked by dev-harness/guard-repo-discipline: stage by file; a blanket add can "
    "sweep untracked local files (.mcp.json, spec artifacts, credentials) into a commit."
)
GIT_COMMIT = (
    "Blocked by dev-harness/guard-repo-discipline: `git commit -a` skips staging by "
    "file. Run `git add <file>` for each file, then commit."
)
GIT_CHECKOUT = (
    "Blocked by dev-harness/guard-repo-discipline: checkout over a path discards "
    "work. Copy the file to the scratchpad before an experiment and restore from that copy."
)
SCREENCAPTURE = (
    "Blocked by dev-harness/guard-repo-discipline: a full-screen capture can catch "
    "private windows. Capture the target only, with `screencapture -R<x,y,w,h>` or `-l<id>`."
)
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")


def git_subcommand(args: list) -> list:
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in GIT_OPTIONS_WITH_VALUE else args[1:]
    return args


def short_flags(arg: str) -> str:
    return arg[1:] if re.match(r"^-[A-Za-z]", arg) else ""


def violation(words: list):
    prog = words[0].rsplit("/", 1)[-1]
    if prog == "screencapture":
        window_scoped = any(re.match(r"^-[A-Za-z]*[Rl]", a) for a in words[1:])
        return None if window_scoped else SCREENCAPTURE
    if prog != "git":
        return None
    args = git_subcommand(words[1:])
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub == "add":
        if "--all" in rest or "." in rest or any("A" in short_flags(a) for a in rest):
            return GIT_ADD
    elif sub == "commit":
        flags = (a for a in rest if not a.startswith("--"))
        if "--all" in rest or any(_commit_all(a) for a in flags):
            return GIT_COMMIT
    elif sub == "checkout":
        dashes = rest.index("--") if "--" in rest else -1
        if "." in rest or (dashes >= 0 and rest[dashes + 1 :]):
            return GIT_CHECKOUT
    return None


def _commit_all(arg: str) -> bool:
    # `-am msg` carries `a`; `-m` takes the rest of its cluster as the message.
    return "a" in short_flags(arg).split("m", 1)[0].split("F", 1)[0]


def main() -> None:
    try:
        cmd = json.load(sys.stdin.buffer).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        return
    for words in command_segments(cmd):
        reason = violation(words)
        if reason:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }
                )
            )
            return


main()
