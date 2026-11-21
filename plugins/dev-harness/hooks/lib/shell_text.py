"""Text-level views of a shell command, for hooks that inspect one before it runs."""
import re
import shlex

HEREDOC = re.compile(r"""(?<!<)<<(?!<)-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?""")


def without_heredoc_bodies(cmd: str) -> str:
    kept, pending = [], []
    for line in cmd.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending = HEREDOC.findall(line)
    return "\n".join(kept)


WRAPPERS = ("sudo", "command", "exec", "nohup", "time", "env")
OPERATORS = ";&|()`\n"


def tokens(text: str) -> list:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def split_on_operators(items: list):
    words = []
    for item in items:
        if item and all(c in OPERATORS for c in item):
            yield words
            words = []
        else:
            words.append(item)
    yield words


def raw_segments(cmd: str):
    """Shell words split at operators, heredoc bodies dropped, nothing stripped."""
    cmd = without_heredoc_bodies(cmd)
    try:
        groups = [tokens(cmd)]
    except ValueError:
        # An unbalanced quote, usually an apostrophe in prose: judge each line on its own.
        groups = []
        for line in cmd.splitlines():
            try:
                groups.append(tokens(line))
            except ValueError:
                groups.append(line.split())
    for group in groups:
        yield from split_on_operators(group)


def command_segments(cmd: str):
    for words in raw_segments(cmd):
        while words and (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS
        ):
            words = words[1:]
        if words:
            yield words


# Opt-in views for guards that must see through more wrappers and into nested commands;
# command_segments above stays as it is for the guards that already use it.
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
# Options of each wrapper that take the next word as their value.
_VALUE_OPTIONS = {
    "env": ("-u", "-C", "-S", "--unset", "--chdir", "--split-string"),
    "timeout": ("-s", "-k", "--signal", "--kill-after"),
    "nice": ("-n", "--adjustment"),
    "sudo": ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "--user", "--group"),
    "time": ("-f", "-o", "--format", "--output"),
}


def strip_wrappers(words: list) -> list:
    """`words` without leading assignments and wrapper commands (`sudo`, `env`, `timeout`,
    `nice`, `nohup`, `time`, `command`, `exec`) together with each wrapper's own options."""
    words = list(words)
    while words:
        head = words[0]
        if ASSIGNMENT.match(head):
            words = words[1:]
            continue
        name = head.rsplit("/", 1)[-1]
        if name not in WRAPPERS + ("timeout", "nice"):
            break
        words = words[1:]
        takes_value = _VALUE_OPTIONS.get(name, ())
        while words and words[0].startswith("-") and words[0] != "-":
            option = words.pop(0)
            if option == "--":
                break
            if option in takes_value:
                words = words[1:]
        if name == "timeout" and words:
            words = words[1:]  # the duration
    return words


def _heredocs(cmd: str):
    """(line that opens it, body) for each heredoc in `cmd`."""
    pending, body, opener = [], [], ""
    for line in cmd.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
                yield opener, "\n".join(body)
                body = []
            else:
                body.append(line)
            continue
        pending, opener = HEREDOC.findall(line), line
    if pending:
        yield opener, "\n".join(body)


def _runs_shell(words: list) -> bool:
    return bool(words) and words[0].rsplit("/", 1)[-1] in SHELLS


def nested_commands(text: str):
    """Command text that `text` hands to another shell: the argument of `sh -c` (any shell,
    clustered flags such as `-lc`), the words after `eval`, and heredoc bodies fed to a shell or
    to `git … --stdin`. One level deep; a caller judges each result and may look again."""
    for words in raw_segments(text):
        words = strip_wrappers(words)
        if words and words[0] == "eval" and len(words) > 1:
            yield " ".join(words[1:])
        elif _runs_shell(words):
            for i, word in enumerate(words[1:], 1):
                if not word.startswith("-") or word.startswith("--"):
                    continue
                if "c" in word[1:] and i + 1 < len(words):
                    yield words[i + 1]
                    break
    for opener, body in _heredocs(text):
        try:
            head = tokens(opener.split("<<", 1)[0])
        except ValueError:
            head = opener.split()
        words = strip_wrappers(next(split_on_operators(head), []))
        if _runs_shell(words) or (words[:1] == ["git"] and "--stdin" in words):
            yield body
