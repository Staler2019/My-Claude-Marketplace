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
  - `core.hooksPath` anywhere in the text (`-c`, `--config-env`, `git config`, and also an
    `echo` beside a git command);
  - `GIT_CONFIG_PARAMETERS` / `GIT_CONFIG_COUNT` / `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM`
    anywhere in the text;
  - conservatively, any single-dash word holding an `n` anywhere after a word naming `commit`
    (`git commit -n`, `-an`, `git-commit -n`, `alias.ci=commit ci -n`, and also `-m -n` or
    `commit -m x && git log -n 1`): options are not parsed and the command is not split, so no
    redirection, quoting or shell-grammar position can hide the flag.
A word glued to a redirection (`--no-verify>/dev/null`, `-n>/dev/null`) still counts. Unquoted
`2>&1`, `&>`, `>|` are blanked first so they do not cut a segment. Heredoc and here-string
bodies are judged as command lines too, since `bash <<EOF` / `bash <<<"…"` run them. A word
holding a whole command line (`sh -c '…'`, `eval "…"`) that mentions git is judged as a
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
HOOKS_PATH = re.compile(r"(?i)core\.hookspath")
ENV_INJECTION = re.compile(r"\bGIT_CONFIG_(PARAMETERS|COUNT|GLOBAL|SYSTEM)\b")
# One brace group with a comma or a `..` range and no group inside it.
_BRACE = re.compile(r"\{([^{}]*)\}")
_EXPANDING = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_SEQUENCE = re.compile(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(?:\.\.(-?\d+))?$")
MAX_VARIANTS = 256
# Conservative `-n` rule, no option parsing: after a word naming `commit` (also inside
# `alias.x=commit` or glued to a redirection), any single-dash word whose letters hold an `n`.
COMMIT_WORD = re.compile(r"(?<![\w-])(?:git-)?commit(?![\w-])")
SHORT_WITH_N = re.compile(r"-[^-\s][^\s]*")
# git takes a unique prefix of a long option; `--no-veri` is the shortest one that is not
# ambiguous with `--no-verbose`, so `--no-veri`, `--no-verif` and the full flag count, also
# glued to a redirection (`--no-verify>/dev/null`).
SKIP_GLUED = re.compile(r"--no-veri(?:f(?:y)?)?(?:\d*[<>].*)?", re.S)


def reason(naming: str) -> str:
    return (f"{PREFIX} `{naming}` would skip the dev-harness git hooks (secret scan). "
            "Fix what the hook reports instead of bypassing it.")


def commit_with_short_n(words: list) -> bool:
    after_commit = False
    for word in words:
        if after_commit and SHORT_WITH_N.match(word) and "n" in re.split(r"[<>]", word, 1)[0]:
            return True
        after_commit = after_commit or bool(COMMIT_WORD.search(word))
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


_FD_OPERATOR = re.compile(r"\d*[<>]&(?:\d+|-)|&>>?|>\|")


def without_fd_operators(text: str) -> str:
    """Unquoted `2>&1`, `&>`, `>|` blanked out, so their `&` / `|` do not cut a command in two."""
    view = unquoted_view(text)
    out = list(text)
    for found in _FD_OPERATOR.finditer(view):
        # `&>` / `>|` still redirect to the next word; `2>&1` names no file.
        keep = "" if found.group(0)[-1:].isdigit() or found.group(0).endswith("-") else ">"
        out[found.start():found.end()] = keep.rjust(found.end() - found.start())
    return "".join(out)


def segments(text: str):
    """Shell words split at operators and newlines, heredoc bodies included; with an unbalanced
    quote each line is split on its own."""
    text = without_fd_operators(text)
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


def judge(cmd: str):
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
    # Judged over the whole command, never per segment: the guard cannot then split apart what
    # the shell keeps together (quoted operators, multi-line quotes, nesting at any depth).
    if HOOKS_PATH.search(flat):
        return reason("core.hooksPath")
    if commit_with_short_n(flat.split()):
        return reason("-n")
    for words in segments(text):
        for word in words:
            if SKIP_GLUED.fullmatch(word):
                return reason(SKIP_FLAG)
            # Each nested word is shorter than its command, so this ends; a recursion error
            # crashes the guard, which denies.
            if "git" in word and re.search(r"[\s;&|]", word):
                nested = judge(word)
                if nested:
                    return nested
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
