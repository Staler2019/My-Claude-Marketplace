"""dev-harness secret guard shared by the pre-commit, commit-msg and pre-push hooks.

Installed as a self-contained copy next to `secret_scan.py` in a repo's hooks dir; in the
plugin source tree it finds the scanner in `hooks/lib/`. Any error exits 1: a guard that
cannot scan does not let the commit or push through.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

HERE = Path(__file__).resolve().parent
DIFF_FLAGS = ("--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "--text",
              "--src-prefix=a/", "--dst-prefix=b/", "-U0")
NAME_FLAGS = ("--name-only", "-z", "--no-renames", "--diff-filter=ACMR")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ZERO = "0" * 40
PATTERNS_FILE = "~/.config/dev-harness/personal-patterns.txt"
SCISSORS = "# ------------------------ >8 ------------------------"
DIFF_LINE_STARTS = ("-", " ", "@@", "diff --git ", "index ", "new file mode", "deleted file mode",
                    "similarity index", "rename from", "rename to", "Binary files")


def _scanner():
    for directory in (HERE, HERE.parent.parent / "hooks" / "lib"):
        if (directory / "secret_scan.py").is_file():
            sys.path.insert(0, str(directory))
            import secret_scan
            return secret_scan
    raise RuntimeError(f"secret_scan.py not found next to {HERE}")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace",
                          check=True).stdout


def _personal(scan) -> Sequence[str]:
    conf = HERE / "dev-harness.conf"
    if conf.is_file() and "personal=off" in conf.read_text().split():
        return ()
    emails = [subprocess.run(["git", "config", *scope, "user.email"], capture_output=True,
                             text=True).stdout.strip() for scope in ([], ["--global"])]
    patterns = os.path.expanduser(PATTERNS_FILE)
    if not os.path.isfile(patterns):
        print(f"dev-harness: no {PATTERNS_FILE}; checking home path and git emails only", file=sys.stderr)
    return scan.personal_literals(os.path.expanduser("~"), emails, patterns)


def _commit_findings(scan, personal) -> List:
    names = [n for n in _git("diff", "--cached", *NAME_FLAGS).split("\0") if n]
    patch = _git("diff", "--cached", *DIFF_FLAGS)
    return scan.scan_names(names) + scan.scan_lines(scan.added_lines(patch), personal)


def _message_findings(scan, personal, message_file: str) -> List:
    """Every line of the message file: `git commit -m` keeps `#` lines, so they are scanned too.
    Below a scissors line only the `git commit -v` diff's removed, context and header lines are
    skipped; its added lines were already scanned by pre-commit."""
    with open(message_file, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    below, kept = False, []
    for line in lines:
        if line == SCISSORS:
            below = True
        skip = below and (line == SCISSORS or line.startswith(DIFF_LINE_STARTS))
        kept.append("" if skip else line)
    return scan.scan_text("commit-msg", "\n".join(kept), personal)


def _tag_message(sha: str) -> str:
    if _git("cat-file", "-t", sha).strip() != "tag":
        return ""
    return _git("cat-file", "tag", sha).split("\n\n", 1)[-1]


def _push_findings(scan, personal, remote: str, updates: str) -> List:
    findings = []
    for line in updates.splitlines():
        fields = line.split()
        if len(fields) != 4 or fields[1] == ZERO:
            continue
        for finding in scan.scan_text("tag-message", _tag_message(fields[1]), personal):
            findings.append(f"{fields[1][:8]} {finding}")
        for commit in _git("rev-list", fields[1], "--not", f"--remotes={remote}").split():
            parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:] or [EMPTY_TREE]
            for parent in parents:
                names = [n for n in _git("diff-tree", "-r", *NAME_FLAGS, parent, commit).split("\0") if n]
                patch = _git("diff-tree", "-r", "-p", *DIFF_FLAGS, parent, commit)
                for finding in scan.scan_names(names) + scan.scan_lines(scan.added_lines(patch), personal):
                    findings.append(f"{commit[:8]} {finding}")
            message = _git("log", "-1", "--format=%B", commit)
            for finding in scan.scan_text("message", message, personal):
                findings.append(f"{commit[:8]} {finding}")
    return findings


def _say(text: str) -> None:
    encoding = sys.stderr.encoding or "ascii"
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        text = text.replace("••••", "****")
    print(text, file=sys.stderr)


def main(mode: str) -> int:
    try:
        scan = _scanner()
        personal = _personal(scan)
        if mode == "commit":
            findings = _commit_findings(scan, personal)
        elif mode == "message":
            findings = _message_findings(scan, personal, sys.argv[1])
        else:
            findings = _push_findings(scan, personal, sys.argv[1] if len(sys.argv) > 1 else "", sys.stdin.read())
    except Exception as error:  # fail closed on anything, including a missing scanner
        _say(f"dev-harness {mode} guard failed ({type(error).__name__}: {error}); refusing.")
        return 1
    if not findings:
        return 0
    _say(f"dev-harness: {mode} refused, {len(findings)} finding(s):")
    for finding in findings:
        _say(f"  {finding}")
    return 1
