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


def command_segments(cmd: str):
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
        for words in split_on_operators(group):
            while words and (
                re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS
            ):
                words = words[1:]
            if words:
                yield words
