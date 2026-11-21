"""dev-harness secret guard shared by the pre-commit, pre-merge-commit, commit-msg and pre-push hooks.

Installed as a self-contained copy next to `secret_scan.py` in a repo's hooks dir; in the
plugin source tree (and only there) it finds the scanner in `hooks/lib/`. Any error exits 1: a guard that
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
ALLOW_FILE = ".dev-harness-allow"
BLOB_MODES = ("100644", "100755")


def _scanner():
    directories = [HERE]
    # Only the plugin source tree may use its hooks/lib copy; an installed hook (in .git/hooks)
    # must never load a scanner from the repo's work tree.
    if HERE.name == "git-hooks" and (HERE.parent.parent / ".claude-plugin" / "plugin.json").is_file():
        directories.append(HERE.parent.parent / "hooks" / "lib")
    for directory in directories:
        if (directory / "secret_scan.py").is_file():
            sys.path.insert(0, str(directory))
            import secret_scan
            return secret_scan
    raise RuntimeError(f"secret_scan.py not found next to {HERE}")


def _git(*args: str, stdin: str = "") -> str:
    return subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, errors="replace",
                          check=True).stdout


def _remote_commits(remote: str) -> str:
    """Commits the remote really holds (asked with ls-remote, not read from local tracking refs,
    which can be stale), limited to the ones present here, as `git rev-list --stdin` input."""
    held = {line.split()[0] for line in _git("ls-remote", remote).splitlines() if line.strip()}
    known = [sha for sha in sorted(held)
             if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0]
    return "--not\n" + "".join(f"{sha}\n" for sha in known)


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


def _allow_list(scan, entries: str) -> frozenset:
    """The allow list from `ls-files -s` / `ls-tree` output for ALLOW_FILE: absent → empty; a
    regular blob → its entries; anything else (a directory, a symlink) → error, refusing."""
    rows = [line for line in entries.splitlines() if line.strip()]
    if not rows:
        return frozenset()
    meta, _, path = rows[0].partition("\t")
    fields = meta.split()
    if len(rows) != 1 or path != ALLOW_FILE or fields[0] not in BLOB_MODES:
        raise RuntimeError(f"{ALLOW_FILE} is not a regular file")
    # `ls-tree`: <mode> blob <oid>; `ls-files -s`: <mode> <oid> <stage>.
    oid = fields[2] if fields[1] == "blob" else fields[1]
    return scan.parse_allow(_git("cat-file", "blob", oid))


def _commit_findings(scan, personal, allowed: List) -> List:
    names = [n for n in _git("diff", "--cached", *NAME_FLAGS).split("\0") if n]
    patch = _git("diff", "--cached", *DIFF_FLAGS)
    allow = _allow_list(scan, _git("ls-files", "-s", "--", ALLOW_FILE))
    kept, passed = scan.split_allowed(scan.scan_lines(scan.added_lines(patch), personal, fingerprint=True), allow)
    allowed.extend(str(finding) for finding in passed)
    return scan.scan_names(names) + kept


def _verbose_diff_lines() -> set:
    """Lines `git commit -v` may show below the scissors: the staged diff against HEAD and, for
    --amend, against HEAD^; with -v -v also the unstaged diff, minus its `+` lines, which no hook
    has scanned yet."""
    shown = set(_git("diff", "--cached").split("\n"))
    parent = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD^"], capture_output=True, text=True)
    if parent.returncode == 0:
        shown |= set(_git("diff", "--cached", "HEAD^").split("\n"))
    shown |= {line for line in _git("diff").split("\n") if not line.startswith("+") or line.startswith("+++ ")}
    return shown


def _message_findings(scan, personal, message_file: str) -> List:
    """Every line of the message file: `git commit -m` keeps `#` lines, so they are scanned too.
    Below a scissors line a line is skipped only when it is a line of a diff `git commit -v`
    shows there; a forged diff-shaped tail (which `-m` would store) is scanned."""
    with open(message_file, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    staged = _verbose_diff_lines() if SCISSORS in lines else set()
    below, kept = False, []
    for line in lines:
        if line == SCISSORS:
            below = True
        skip = below and (line == SCISSORS or (line != "" and line in staged))
        kept.append("" if skip else line)
    return scan.scan_text("commit-msg", "\n".join(kept), personal)


def _tag_message(sha: str) -> str:
    if _git("cat-file", "-t", sha).strip() != "tag":
        return ""
    return _git("cat-file", "tag", sha).split("\n\n", 1)[-1]


def _push_findings(scan, personal, remote: str, updates: str, allowed: List) -> List:
    findings, exclude = [], None
    for line in updates.splitlines():
        fields = line.split()
        if len(fields) != 4 or fields[1] == ZERO:
            continue
        for finding in scan.scan_text("tag-message", _tag_message(fields[1]), personal):
            findings.append(f"{fields[1][:8]} {finding}")
        if exclude is None:
            exclude = _remote_commits(remote)
        for commit in _git("rev-list", fields[1], "--stdin", stdin=exclude).split():
            # Each commit is judged by the allow list in its own tree, never a later one.
            allow = _allow_list(scan, _git("ls-tree", commit, "--", ALLOW_FILE))
            parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:] or [EMPTY_TREE]
            for parent in parents:
                names = [n for n in _git("diff-tree", "-r", *NAME_FLAGS, parent, commit).split("\0") if n]
                patch = _git("diff-tree", "-r", "-p", *DIFF_FLAGS, parent, commit)
                kept, passed = scan.split_allowed(
                    scan.scan_lines(scan.added_lines(patch), personal, fingerprint=True), allow)
                allowed.extend(f"{commit[:8]} {finding}" for finding in passed)
                for finding in scan.scan_names(names) + kept:
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
    allowed: List[str] = []
    try:
        scan = _scanner()
        personal = _personal(scan)
        if mode == "commit":
            findings = _commit_findings(scan, personal, allowed)
        elif mode == "message":
            findings = _message_findings(scan, personal, sys.argv[1])
        else:
            # argv: remote name, remote URL; the URL also works for a push to a bare URL.
            remote = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
            findings = _push_findings(scan, personal, remote, sys.stdin.read(), allowed)
    except Exception as error:  # fail closed on anything, including a missing scanner
        _say(f"dev-harness {mode} guard failed ({type(error).__name__}: {error}); refusing.")
        return 1
    for finding in allowed:
        _say(f"dev-harness: allowed by {ALLOW_FILE}: {finding}")
    if not findings:
        return 0
    _say(f"dev-harness: {mode} refused, {len(findings)} finding(s):")
    for finding in findings:
        _say(f"  {finding}")
    if any(" fp:" in finding for finding in map(str, findings)):
        _say(f"dev-harness: open each path:line first. A false positive (test data, placeholder) can be "
             f"listed by the user as `<fp>  <path>:<line> <kind>` in {ALLOW_FILE}, committed with that line; "
             "personal and file-name findings cannot be listed.")
    return 1
