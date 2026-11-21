#!/usr/bin/env python3
"""PreToolUse(Bash): refuse process kills that can hit the wrong process.

Blocked: pkill, killall (any form -- name/pattern matching, e.g. `pkill -f cat`
matched "/Applications/..." and killed a user app), and `kill` aimed at
anything but plain positive PIDs (negative = process group, -1 = everything,
`%job`, `$(pgrep ...)`).
Allowed: `kill [-SIG] <pid> [<pid> ...]` with numeric PIDs only.
"""
import json
import re
import shlex
import sys

from lib.shell_text import without_heredoc_bodies

REASON = (
    "Blocked by dev-harness/block-fuzzy-kill: pkill/killall and kill "
    "with non-PID targets match by name or group and can kill unrelated "
    "apps. Stop your own background task with TaskStop; otherwise find the "
    "exact PID first (`pgrep -lf <pattern>` or `ps -p <pid> -o pid,command`), "
    "show it, and run `kill <PID>`."
)


def segments(cmd: str):
    # Split on shell control operators; good enough for a guard.
    for part in re.split(r"\|\||&&|[;|&\n()`]|\$\(", cmd):
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            words = part.split()
        # Skip env assignments and wrappers like sudo/command/exec.
        while words and (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])
            or words[0] in ("sudo", "command", "exec", "nohup", "time", "env")
        ):
            words = words[1:]
        if words:
            yield words


def bad(words) -> bool:
    prog = words[0].rsplit("/", 1)[-1]
    if prog in ("pkill", "killall"):
        return True
    if prog != "kill":
        return False
    args = words[1:]
    if args and args[0] in ("-l", "-L"):
        return False  # listing signals
    if args and re.match(r"^-(s|n)$", args[0]):
        args = args[2:]
    elif args and re.match(r"^-[A-Za-z0-9]+$", args[0]):
        args = args[1:]  # one signal option, e.g. -9 / -TERM
    if not args:
        return False
    return not all(re.fullmatch(r"[1-9][0-9]*", a) for a in args)


def main() -> None:
    try:
        cmd = json.load(sys.stdin.buffer).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        return
    cmd = without_heredoc_bodies(cmd)
    # `kill $(pgrep ...)` / `kill \`...\``: the targets come from a match.
    subst = re.search(r"(^|[\s;&|(])kill\b[^;&|\n]*(\$\(|`)", cmd)
    if subst or any(bad(w) for w in segments(cmd)):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": REASON,
                    }
                }
            )
        )


main()
