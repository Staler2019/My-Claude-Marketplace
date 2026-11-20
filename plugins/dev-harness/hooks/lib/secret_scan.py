"""Find secrets and personal values in what a commit adds: pure, stdlib only, no I/O but one file read.

Token rules are the gitleaks default-config regexes (github.com/gitleaks/gitleaks,
config/gitleaks.toml), copied verbatim except `private-key-header`: the gitleaks
`private-key` rule needs header, body and footer in one string, and lines are scanned one at a
time, so here the header line alone is the finding. Every rule needs a body after its prefix,
which keeps this file's own regex text from matching itself.
"""
import fnmatch
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

_END = r"""(?:[\x60'"\s;]|\\[nr]|$)"""
TOKEN_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    (rule_id, re.compile(pattern)) for rule_id, pattern in (
        ("anthropic-api-key", r"\b(sk-ant-api03-[a-zA-Z0-9_\-]{93}AA)" + _END),
        ("openai-api-key", r"\b(sk-(?:proj|svcacct|admin)-(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})T3BlbkFJ"
                           r"(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})\b|sk-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20})" + _END),
        ("npm-access-token", r"(?i)\b(npm_[a-z0-9]{36})" + _END),
        ("huggingface-access-token", r"\b(hf_(?i:[a-z]{34}))" + _END),
        ("gitlab-pat", r"glpat-[\w-]{20}"),
        ("pypi-upload-token", r"pypi-AgEIcHlwaS5vcmc[\w-]{50,1000}"),
        ("stripe-access-token", r"\b((?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99})" + _END),
        ("github-fine-grained-pat", r"github_pat_\w{82}"),
        ("github-pat", r"ghp_[0-9a-zA-Z]{36}"),
        ("github-oauth", r"gho_[0-9a-zA-Z]{36}"),
        ("github-app-token", r"(?:ghu|ghs)_[0-9a-zA-Z]{36}"),
        ("github-refresh-token", r"ghr_[0-9a-zA-Z]{36}"),
        ("private-key-header", r"(?i)-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----"),
        ("aws-access-token", r"\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b"),
        ("gcp-api-key", r"\b(AIza[\w-]{35})" + _END),
        ("slack-bot-token", r"xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*"),
        ("slack-user-token", r"xox[pe](?:-[0-9]{10,13}){3}-[a-zA-Z0-9-]{28,34}"),
        ("slack-webhook-url", r"(?:https?://)?hooks.slack.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]{43,56}"),
        ("jwt", r"\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9\/\\_-]{17,}\.(?:[a-zA-Z0-9\/\\_-]{10,}={0,2})?)" + _END),
    ))
# A key word, then `:` or `=`, then 8+ characters that are not a `$VAR` / `${{ … }}` reference.
GENERIC_RULE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential)s?\s*[:=]\s*[\"']?([^\s\"'$]{8,})")
NAME_RULES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
              "id_rsa*", "id_ed25519*", "id_ecdsa*", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
              "*credentials*", ".mcp.json", ".claude.json", "settings.local.json", "*.jsonl")
MIN_PERSONAL = 4
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

Line = Tuple[str, int, str]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    masked: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.kind} {self.masked}"


def added_lines(patch: str) -> List[Line]:
    """(path, new line number, text) for each `+` line of a unified diff; lines holding NUL (binary content) are scanned as they are."""
    found, path, number = [], None, 0
    for raw in patch.split("\n"):
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
        elif raw.startswith("@@"):
            hunk = _HUNK.match(raw)
            number = int(hunk.group(1)) if hunk else 0
        elif raw.startswith("+") and path is not None:
            found.append((path, number, raw[1:]))
            number += 1
        elif raw.startswith(" ") and path is not None:
            number += 1
    return found


def scan_lines(lines: Iterable[Line], personal: Sequence[str]) -> List[Finding]:
    findings = []
    for path, number, text in lines:
        for rule_id, pattern in TOKEN_RULES:
            match = pattern.search(text)
            if match:
                value = next((g for g in match.groups() if g), match.group(0))
                findings.append(Finding(path, number, rule_id, value[:4] + "••••"))
        generic = GENERIC_RULE.search(text)
        if generic:
            masked = f"{generic.group(1).lower()}=<{len(generic.group(2))} chars>"
            findings.append(Finding(path, number, "generic-secret", masked))
        lowered = text.lower()
        if any(literal.lower() in lowered for literal in personal):
            findings.append(Finding(path, number, "personal", "••••"))
    return findings


def scan_text(path: str, text: str, personal: Sequence[str]) -> List[Finding]:
    return scan_lines(((path, i + 1, line) for i, line in enumerate(text.split("\n"))),
                      personal)


def scan_names(paths: Iterable[str]) -> List[Finding]:
    findings = []
    for path in paths:
        name = path.rsplit("/", 1)[-1].lower()
        if any(fnmatch.fnmatchcase(name, rule) for rule in NAME_RULES):
            findings.append(Finding(path, 0, "file-name", name))
    return findings


def personal_literals(home: str, emails: Iterable[str], patterns_file: Optional[str]) -> Tuple[str, ...]:
    """$HOME, the git emails, then the patterns file (`#` and blank lines skipped, short ones dropped)."""
    candidates = [home, *emails]
    try:
        with open(patterns_file or "", encoding="utf-8") as fh:
            candidates += [line.strip() for line in fh if not line.lstrip().startswith("#")]
    except OSError:
        pass
    seen: List[str] = []
    for value in candidates:
        if value and len(value) >= MIN_PERSONAL and value not in seen:
            seen.append(value)
    return tuple(seen)
