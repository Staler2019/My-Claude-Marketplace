#!/usr/bin/env python3
"""PreToolUse(Bash): refuse git commands that would skip the native pre-commit / pre-push hooks.

The command text is first expanded and flattened the way the shell would build its words:
backslash-newline continuations are joined, brace groups (`{a,b}`, `{x..y}`) are expanded into
every variant (capped at MAX_VARIANTS), and in each variant quotes, `$'`/`$"` openers,
backslashes and empty `$()` / backtick pairs are removed. Blocked when a flattened variant
mentions `git` and any of: the long skip-verify flag or an abbreviation git
accepts for it (`--no-veri` and longer; shorter prefixes are ambiguous to git and rejected by
it), a `core.hooksPath` override, or `GIT_CONFIG_PARAMETERS` / `GIT_CONFIG_COUNT` injection.
The whole text is checked, so `sh -c '...'` wrappers are caught too. `git commit -n` (alone or
in a short flag cluster) is judged per segment, so `git commit -m -n` and `git log -n 3` pass.
Registered with "onFailure": "block": a crash or timeout of this guard denies the command.

Out of reach of a text check, and not covered: flag text the shell produces at run time —
`$'\\x..'` / `$'\\NNN'` escape sequences, variable or parameter expansion, non-empty command
substitution, pathname globbing, eval, aliases, and commands read from script files. The
`-n` check reads shell words without brace expansion or line joining. The native hooks cannot
catch a skipped run either; a server-side scan (e.g. GitHub push protection) is the backstop.
"""
import json
import re
import sys

from lib.shell_text import command_segments

PREFIX = "Blocked by dev-harness/guard-hook-bypass:"
SKIP_FLAG = "--no-" + "verify"
# git takes a unique prefix of a long option; `--no-veri` is the shortest one that is not
# ambiguous with `--no-verbose`, so `--no-veri`, `--no-verif` and the full flag count.
SKIP_SPELLINGS = r"--no-veri(?:f(?:y)?)?(?![\w-])"
# Marks that only join pieces of one word: a quote (with a `$` opener), a backslash, an empty
# command substitution.
_JOIN_MARKS = re.compile(r"""\$\(\)|``|\$(?=['"])|['"\\]""")
# One brace group with no group inside it: `{a,b}` or `{x..y}` / `{x..y..step}`.
_BRACE = re.compile(r"\{([^{}]*)\}")
_SEQUENCE = re.compile(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(?:\.\.(-?\d+))?$")
MAX_VARIANTS = 256
RAW_MARKERS = (
    (re.compile(SKIP_SPELLINGS), SKIP_FLAG),
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


def _alternatives(inner: str):
    """The words bash makes of one brace group, or None when the group is literal text."""
    sequence = _SEQUENCE.match(inner)
    if sequence:
        first, last, step = sequence.group(1), sequence.group(2), abs(int(sequence.group(3) or 1)) or 1
        numeric = first.lstrip("-").isdigit() and last.lstrip("-").isdigit()
        if not numeric and (first.lstrip("-").isdigit() or last.lstrip("-").isdigit()):
            return None
        lo, hi = (int(first), int(last)) if numeric else (ord(first), ord(last))
        values = range(lo, hi + 1, step) if lo <= hi else range(lo, hi - 1, -step)
        return [str(v) if numeric else chr(v) for v in values][:MAX_VARIANTS]
    parts = inner.split(",")
    return parts if len(parts) > 1 else None


def brace_variants(text: str):
    """Every text bash brace expansion could make of `text`; None past MAX_VARIANTS."""
    done, pending = [], [text]
    while pending:
        if len(done) + len(pending) > MAX_VARIANTS:
            return None
        current = pending.pop()
        for group in _BRACE.finditer(current):
            options = _alternatives(group.group(1))
            if options is not None:
                head, tail = current[:group.start()], current[group.end():]
                pending.extend(head + option + tail for option in options)
                break
        else:
            done.append(current)
    return done


def violation(cmd: str):
    variants = brace_variants(cmd.replace("\\\n", ""))
    if variants is None:
        # Not every variant was checked, and braces can spell `git` itself: fail closed.
        return reason("brace expansion")
    for variant in variants:
        joined = _JOIN_MARKS.sub("", variant)
        if "git" not in joined:
            continue
        for pattern, naming in RAW_MARKERS:
            if pattern.search(joined):
                return reason(naming)
    if "git" not in cmd:
        return None
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
