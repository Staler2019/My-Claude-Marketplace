#!/usr/bin/env python3
"""PreToolUse(Bash): refuse git commands that would skip the native pre-commit / pre-push hooks.

Blocked when the raw command mentions `git` and any of: the long skip-verify flag or any
prefix git would expand to it (quotes removed first, so split spellings are joined), a
`core.hooksPath` override, or `GIT_CONFIG_PARAMETERS` / `GIT_CONFIG_COUNT` injection. The raw
text is checked, so `sh -c '...'` wrappers are caught too. `git commit -n` (alone or in a short
flag cluster) is judged per segment, so `git commit -m -n` and `git log -n 3` pass.
Registered with "onFailure": "block": a crash or timeout of this guard denies the command.
"""
import json
import re
import sys

from lib.shell_text import command_segments

PREFIX = "Blocked by dev-harness/guard-hook-bypass:"
SKIP_FLAG = "--no-" + "verify"
# git takes any unique prefix of a long option, so `--no-v` … the full flag all count.
_SKIP_PREFIXES = "".join(f"(?:{re.escape(c)}" for c in SKIP_FLAG[len("--no-v"):]) + ")?" * (
    len(SKIP_FLAG) - len("--no-v"))
RAW_MARKERS = (
    (re.compile(re.escape("--no-v") + _SKIP_PREFIXES + r"(?![\w-])"), SKIP_FLAG),
    (re.compile(r"(?i)core\.hookspath"), "core.hooksPath"),
    (re.compile(r"\bGIT_CONFIG_PARAMETERS\b"), "GIT_CONFIG_PARAMETERS"),
    (re.compile(r"\bGIT_CONFIG_COUNT\b"), "GIT_CONFIG_COUNT"),
)
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
# Short commit options whose value is the rest of the cluster or the next word.
COMMIT_SHORT_WITH_VALUE = "mFcCt"
COMMIT_LONG_WITH_VALUE = ("--message", "--file", "--reuse-message", "--reedit-message",
                          "--template", "--author", "--date", "--fixup", "--squash", "--cleanup")


def reason(naming: str) -> str:
    return (f"{PREFIX} `{naming}` would skip the dev-harness git hooks (secret scan). "
            "Fix what the hook reports instead of bypassing it.")


def git_subcommand(args: list) -> list:
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in GIT_OPTIONS_WITH_VALUE else args[1:]
    return args


def commit_skips_hooks(rest: list) -> bool:
    skip_next = False
    for arg in rest:
        if skip_next:
            skip_next = False
        elif arg == "--":
            return False
        elif arg.startswith("--"):
            skip_next = arg in COMMIT_LONG_WITH_VALUE
        elif re.match(r"^-[A-Za-z]", arg):
            cluster = arg[1:]
            cut = next((i for i, c in enumerate(cluster) if c in COMMIT_SHORT_WITH_VALUE), None)
            if "n" in (cluster if cut is None else cluster[:cut]):
                return True
            skip_next = cut is not None and cut == len(cluster) - 1
    return False


def violation(cmd: str):
    if "git" not in cmd:
        return None
    # The shell joins `'--no-'"verify"` into one word; judge the text with quotes taken out.
    joined = re.sub(r"""['"\\]""", "", cmd)
    for pattern, naming in RAW_MARKERS:
        if pattern.search(joined):
            return reason(naming)
    for words in command_segments(cmd):
        if words[0].rsplit("/", 1)[-1] != "git":
            continue
        args = git_subcommand(words[1:])
        if args and args[0] == "commit" and commit_skips_hooks(args[1:]):
            return reason("-n")
    return None


def main() -> None:
    try:
        cmd = json.load(sys.stdin.buffer).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        return
    found = violation(cmd or "")
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": found}}))


main()
