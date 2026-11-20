#!/usr/bin/env python3
"""PreToolUse(Bash): refuse git commands that would skip the native pre-commit / pre-push hooks.

The command is read the way the shell builds its words: backslash-newline continuations are
joined, `$'…'` / `$"…"` are read as quotes, empty `$()` / backtick pairs are dropped, and then
quotes and backslashes are resolved by a shell-word splitter. Refused, whenever the command
involves git:
  - any unquoted brace expansion (`{a,b}`, `{x..y}`) anywhere in the command — the shell can
    assemble a flag or the word `git` itself from braces, so paths are listed one by one;
  - a word that is the skip-verify long flag or an abbreviation git accepts for it
    (`--no-veri` and longer; shorter prefixes are ambiguous to git and rejected by it);
  - a word naming `core.hooksPath` (`-c`, `-c<value>`, `--config-env`, `git config`) in a
    segment that runs git;
  - `GIT_CONFIG_PARAMETERS` / `GIT_CONFIG_COUNT` / `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM`
    anywhere in the text;
  - `git commit -n`, alone or in a short flag cluster.
A segment runs git when any of its words is `git`, wherever it stands: after `{`, `!`, `if`,
`do`, a redirection, or a runner such as `nice`, `timeout` or `xargs`. Heredoc bodies are judged
as command lines too, since `bash <<EOF` runs them. A word holding a whole command line (`sh -c '…'`, `eval "…"`) that mentions git is judged as a
command of its own; message text that does not mention git is not, so `-m "never pass <flag>"`
passes. Registered with "onFailure": "block": a crash or timeout of this guard denies the
command.

Out of reach of a text check, and not covered: flag text the shell produces at run time —
`$'\\x..'` / `$'\\NNN'` escape sequences, variable or parameter expansion, non-empty command
substitution, pathname globbing, aliases, and commands read from script files. The native hooks
cannot catch a skipped run either; a server-side scan (e.g. GitHub push protection) is the
backstop.
"""
import json
import re
import sys

from lib.shell_text import split_on_operators, tokens

PREFIX = "Blocked by dev-harness/guard-hook-bypass:"
SKIP_FLAG = "--no-" + "verify"
# git takes a unique prefix of a long option; `--no-veri` is the shortest one that is not
# ambiguous with `--no-verbose`, so `--no-veri`, `--no-verif` and the full flag count.
SKIP_WORD = re.compile(r"--no-veri(?:f(?:y)?)?")
HOOKS_PATH = re.compile(r"(?i)core\.hookspath")
ENV_INJECTION = re.compile(r"\bGIT_CONFIG_(PARAMETERS|COUNT|GLOBAL|SYSTEM)\b")
# One brace group with a comma or a `..` range and no group inside it.
_BRACE = re.compile(r"\{([^{}]*)\}")
_EXPANDING = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_SEQUENCE = re.compile(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(?:\.\.(-?\d+))?$")
MAX_VARIANTS = 256
MAX_DEPTH = 4
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--attr-source",
                          "--config-env", "--super-prefix", "--exec-path")
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


def normalized(cmd: str) -> str:
    """Line continuations joined, `$'`/`$"` read as plain quotes, empty substitutions dropped."""
    text = cmd.replace("\\\n", "")
    text = re.sub(r"\$(?=['\"])", "", text)
    return re.sub(r"\$\(\)|``", "", text)


def unquoted_view(text: str) -> str:
    """`text` with every quoted or backslash-escaped character replaced by `_`: what is left is
    what the shell reads as syntax, braces included."""
    out, quote, i = [], None, 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
                out.append(c)
            elif c == "\\" and quote == '"' and i + 1 < len(text):
                out.append("__")
                i += 1
            else:
                out.append("_")
        elif c == "\\" and i + 1 < len(text):
            out.append("__")
            i += 1
        else:
            if c in "'\"":
                quote = c
            out.append(c)
        i += 1
    return "".join(out)


class _TooMany(Exception):
    """More brace variants than MAX_VARIANTS."""


def _alternatives(inner: str):
    sequence = _SEQUENCE.match(inner)
    if sequence:
        first, last, step = sequence.group(1), sequence.group(2), abs(int(sequence.group(3) or 1)) or 1
        numeric = first.lstrip("-").isdigit() and last.lstrip("-").isdigit()
        if not numeric and (first.lstrip("-").isdigit() or last.lstrip("-").isdigit()):
            return None
        lo, hi = (int(first), int(last)) if numeric else (ord(first), ord(last))
        values = range(lo, hi + 1, step) if lo <= hi else range(lo, hi - 1, -step)
        if len(values) > MAX_VARIANTS:
            raise _TooMany
        return [str(v) if numeric else chr(v) for v in values]
    parts = inner.split(",")
    return parts if len(parts) > 1 else None


def spells_git_by_braces(view: str) -> bool:
    """True when some brace expansion of the unquoted view contains `git`, or there are too many
    variants to tell."""
    pending, seen = [view], 0
    try:
        while pending:
            seen += 1
            if seen > MAX_VARIANTS:
                return True
            current = pending.pop()
            for group in _BRACE.finditer(current):
                options = _alternatives(group.group(1))
                if options is not None:
                    pending.extend(current[:group.start()] + o + current[group.end():] for o in options)
                    break
            else:
                if "git" in current:
                    return True
    except _TooMany:
        return True
    return False


def segments(text: str):
    """Shell words split at operators and newlines, heredoc bodies included; with an unbalanced
    quote each line is split on its own."""
    try:
        groups = [tokens(text)]
    except ValueError:
        groups = []
        for line in text.splitlines():
            try:
                groups.append(tokens(line))
            except ValueError:
                groups.append(line.split())
    for group in groups:
        yield from (words for words in split_on_operators(group) if words)


def is_git(word: str) -> bool:
    return word.rsplit("/", 1)[-1] == "git"


def judge(cmd: str, depth: int = 0):
    text = normalized(cmd)
    flat = re.sub(r"['\"\\]", "", text)
    view = unquoted_view(text)
    involves_git = "git" in flat
    if _EXPANDING.search(view) and (involves_git or spells_git_by_braces(view)):
        return reason("brace expansion")
    if not involves_git:
        return None
    found = ENV_INJECTION.search(flat)
    if found:
        return reason(found.group(0))
    for words in segments(text):
        runs_git = any(is_git(word) for word in words)
        for word in words:
            if SKIP_WORD.fullmatch(word):
                return reason(SKIP_FLAG)
            if HOOKS_PATH.search(word) and runs_git:
                return reason("core.hooksPath")
            if depth < MAX_DEPTH and "git" in word and re.search(r"[\s;&|]", word):
                nested = judge(word, depth + 1)
                if nested:
                    return nested
        for i, word in enumerate(words):
            if is_git(word):
                args = git_subcommand(words[i + 1:])
                if args and args[0] == "commit" and commit_skips_hooks(args[1:]):
                    return reason("-n")
    return None


def main() -> None:
    try:
        cmd = json.load(sys.stdin.buffer).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        return
    found = judge(cmd or "")
    if found:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": found}}))


main()
