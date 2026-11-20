"""Tests for lib/secret_scan.py: added lines and file names in, masked findings out.

Every token, key and personal value below is assembled at run time, so this file never holds
a literal the scanner would report (the self-scan test checks exactly that).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
PLUGIN = HOOKS.parent
sys.path.insert(0, str(HOOKS))

from lib.secret_scan import (  # noqa: E402
    Finding, added_lines, parse_allow, personal_literals, scan_lines, scan_names, scan_text,
    split_allowed)

UPPER, LOWER, DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", "0123456789"


def body(n, alphabet=UPPER + LOWER + DIGITS):
    return "".join(alphabet[i % len(alphabet)] for i in range(n))


def tokens():
    """One real-shaped value per token rule id, built from pieces."""
    dash = "-" * 5
    return {
        "anthropic-api-key": "sk-" + "ant-api03-" + body(93) + "AA",
        "openai-api-key": "sk-" + "proj-" + body(74) + "T3Blbk" + "FJ" + body(74),
        "npm-access-token": "npm" + "_" + body(36, LOWER + DIGITS),
        "huggingface-access-token": "hf" + "_" + body(34, LOWER),
        "gitlab-pat": "glpat" + "-" + body(20),
        "pypi-upload-token": "pypi-" + "AgEIcHlwaS5vcmc" + body(60),
        "stripe-access-token": "sk" + "_live_" + body(24),
        "github-fine-grained-pat": "github" + "_pat_" + body(82),
        "github-pat": "gh" + "p_" + body(36),
        "github-oauth": "gh" + "o_" + body(36),
        "github-app-token": "gh" + "s_" + body(36),
        "github-refresh-token": "gh" + "r_" + body(36),
        "private-key-header": dash + "BEGIN RSA PRIV" + "ATE KEY" + dash,
        "aws-access-token": "AK" + "IA" + body(16, UPPER + "234567"),
        "gcp-api-key": "AI" + "za" + body(35),
        "slack-bot-token": "xo" + "xb-" + body(12, DIGITS) + "-" + body(12, DIGITS) + "-" + body(24),
        "slack-user-token": "xo" + "xp-" + "-".join(body(11, DIGITS) for _ in range(3)) + "-" + body(30),
        "slack-webhook-url": "https://hooks." + "slack.com/services/" + body(44),
        "jwt": "ey" + body(20) + ".ey" + body(20) + "." + body(20),
    }


def lines(*texts, path="f.txt"):
    return [(path, i + 1, text) for i, text in enumerate(texts)]


class AddedLines(unittest.TestCase):
    PATCH = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -3,0 +4,2 @@\n"
        "+first\n"
        "+second\n"
        "@@ -10 +12 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/gone.txt b/gone.txt\n"
        "--- a/gone.txt\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-bye\n"
    )

    def test_yields_path_line_and_text_of_added_lines_only(self):
        self.assertEqual(added_lines(self.PATCH),
                         [("x.py", 4, "first"), ("x.py", 5, "second"), ("x.py", 12, "new")])

    def test_lines_holding_nul_are_kept(self):
        patch = "+++ b/bin\n@@ -0,0 +1,2 @@\n+ok\n+a\x00b\n"
        self.assertEqual(added_lines(patch), [("bin", 1, "ok"), ("bin", 2, "a\x00b")])

    def test_token_next_to_nul_is_found(self):
        value = tokens()["github-pat"]
        found = scan_lines(added_lines(f"+++ b/bin\n@@ -0,0 +1 @@\n+{value}\x00\n"), ())
        self.assertEqual([f.kind for f in found], ["github-pat"])
        self.assertEqual([f.kind for f in scan_text("bin", f"\x00{value}\x00", ())], ["github-pat"])
        # NUL splits nothing: a value running across it still counts toward the generic rule.
        self.assertEqual([f.kind for f in scan_text("bin", "pass" + "word=abcdefg\x00h", ())], ["generic-secret"])

    def test_counts_context_lines(self):
        patch = "+++ b/c\n@@ -1,3 +1,4 @@\n keep\n+added\n keep\n"
        self.assertEqual(added_lines(patch), [("c", 2, "added")])


class TokenRules(unittest.TestCase):
    def test_every_rule_id_reports_its_token(self):
        for rule, value in tokens().items():
            with self.subTest(rule=rule):
                found = scan_lines(lines(f"key = '{value}'"), ())
                self.assertIn(rule, [f.kind for f in found])

    def test_mask_shows_four_chars_never_the_value(self):
        value = tokens()["github-pat"]
        (finding,) = scan_lines(lines(value), ())
        self.assertEqual(finding.masked, value[:4] + "••••")
        self.assertNotIn(value[4:], str(finding))

    def test_private_key_header_alone_on_its_line(self):
        pem = [tokens()["private-key-header"], body(64), body(64),
               "-" * 5 + "END RSA PRIV" + "ATE KEY" + "-" * 5]
        found = scan_lines(lines(*pem, path="notes.txt"), ())
        self.assertEqual([(f.kind, f.line) for f in found], [("private-key-header", 1)])

    def test_prefix_without_body_is_not_a_token(self):
        self.assertEqual(scan_lines(lines("gh" + "p_" + "short", "AK" + "IA" + "[A-Z]{16}"), ()), [])


class GenericRule(unittest.TestCase):
    def test_assignment_with_long_value(self):
        (finding,) = scan_lines(lines("pass" + "word = " + "'hunter2hunter2'"), ())
        self.assertEqual((finding.kind, finding.masked), ("generic-secret", "password=<14 chars>"))

    def test_word_alone_or_short_value_or_variable_is_ignored(self):
        texts = ["keep secrets out of logs", "tok" + "en = 'abc'", "api_key = $API_KEY",
                 "tok" + "en: ${{ secrets.X }}"]
        self.assertEqual(scan_lines(lines(*texts), ()), [])


class Personal(unittest.TestCase):
    def test_literal_reported_case_insensitively_with_kind_only(self):
        home = "/" + "Users/" + "someone"
        (finding,) = scan_lines(lines("path: " + home.upper() + "/x"), (home,))
        self.assertEqual((finding.kind, finding.masked), ("personal", "••••"))

    def test_literals_from_home_emails_and_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("# comment\n\nabc\nsome-handle\n")
        try:
            got = personal_literals("/h/me", ["me" + "@example.org", ""], fh.name)
        finally:
            os.unlink(fh.name)
        self.assertEqual(got, ("/h/me", "me" + "@example.org", "some-handle"))

    def test_github_noreply_email_is_not_personal(self):
        domain = "@users." + "noreply.github.com"
        noreply = "12345+octocat" + domain
        kept = ["me" + "@example.org", "noreply" + "@example.org", "real@example.com.users." + "noreply.github.com",
                "x" + domain + ".evil", "x@sub.users." + "noreply.github.com", "a@b.com" + domain]
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write(noreply + "\n")
        try:
            got = personal_literals("/h/me", [noreply, noreply.upper(), *kept], fh.name)
        finally:
            os.unlink(fh.name)
        # Only the email candidates are exempt; the same value written in the patterns file counts.
        self.assertEqual(got, ("/h/me", *kept, noreply))

    def test_missing_file_keeps_home_and_emails(self):
        self.assertEqual(personal_literals("/h/me", [], "/nonexistent/x"), ("/h/me",))


class Names(unittest.TestCase):
    def test_key_and_credential_file_names(self):
        bad = [".env", "app/.env.local", "a.pem", "k.key", "c.p12", "id_rsa", "id_ed25519.pub",
               ".netrc", ".npmrc", ".git-credentials", "aws_credentials.json", ".mcp.json",
               ".claude.json", "settings.local.json", "s.jsonl"]
        found = scan_names(bad)
        self.assertEqual(sorted(f.path for f in found), sorted(bad))
        self.assertTrue(all(f.kind == "file-name" for f in found))

    def test_ordinary_names_pass(self):
        self.assertEqual(scan_names(["README.md", "src/env.py", "keys.md"]), [])


class SelfScan(unittest.TestCase):
    def test_plugin_sources_hold_no_findings(self):
        personal = personal_literals(os.path.expanduser("~"), [], "/nonexistent")
        findings = []
        for path in sorted(PLUGIN.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                rel = str(path.relative_to(PLUGIN))
                findings += scan_names([rel])
                findings += scan_text(rel, path.read_text(errors="replace"), personal)
        self.assertEqual(findings, [])


class FindingText(unittest.TestCase):
    def test_str_names_path_line_kind_mask(self):
        self.assertEqual(str(Finding("a.py", 3, "github-pat", "ghp_••••")),
                         "a.py:3 github-pat ghp_••••")

    def test_str_appends_the_fingerprint_when_set(self):
        self.assertEqual(str(Finding("a.py", 3, "github-pat", "ghp_••••", "0123456789abcdef")),
                         "a.py:3 github-pat ghp_•••• fp:0123456789abcdef")


class Allow(unittest.TestCase):
    PLACEHOLDER = "api" + "Key = 'sk-live-xxxx'"

    def fp(self, path="a.md", text=PLACEHOLDER, personal=()):
        (finding,) = scan_lines([(path, 1, text)], personal, fingerprint=True)
        return finding.fingerprint

    def test_fingerprint_is_16_hex_and_stable(self):
        value = self.fp()
        self.assertRegex(value, r"^[0-9a-f]{16}$")
        self.assertEqual(value, self.fp())

    def test_fingerprint_changes_with_path_kind_or_text(self):
        value = self.fp()
        self.assertNotEqual(value, self.fp(path="b.md"))
        self.assertNotEqual(value, self.fp(text=self.PLACEHOLDER + " "))
        pat = tokens()["github-pat"]
        found = scan_lines([("a.md", 1, "tok" + "en = " + pat)], (), fingerprint=True)
        by_kind = {f.kind: f.fingerprint for f in found}
        self.assertEqual(set(by_kind), {"github-pat", "generic-secret"})
        self.assertNotEqual(by_kind["github-pat"], by_kind["generic-secret"])

    def test_no_fingerprint_without_the_flag_or_for_personal_names_and_text(self):
        self.assertEqual(scan_lines([("a.md", 1, self.PLACEHOLDER)], ())[0].fingerprint, "")
        home = "/" + "Users/" + "someone"
        (finding,) = scan_lines([("a.md", 1, home)], (home,), fingerprint=True)
        self.assertEqual(finding.fingerprint, "")
        self.assertEqual(scan_names([".env"])[0].fingerprint, "")
        self.assertEqual(scan_text("commit-msg", self.PLACEHOLDER, ())[0].fingerprint, "")

    def test_parse_allow_keeps_only_16_hex_first_tokens(self):
        text = ("# comment\n\n0123456789ABCDEF  rules/a.md:3 generic-secret\n"
                "0123456789abcde\nzz23456789abcdef\n0123456789abcdef0\nfedcba9876543210\n")
        self.assertEqual(parse_allow(text), frozenset({"0123456789abcdef", "fedcba9876543210"}))

    def test_split_allowed_judges_each_finding_on_its_own(self):
        pat = tokens()["github-pat"]
        found = scan_lines([("a.md", 1, "tok" + "en = " + pat)], (), fingerprint=True)
        generic = next(f for f in found if f.kind == "generic-secret")
        kept, allowed = split_allowed(found, frozenset({generic.fingerprint}))
        self.assertEqual([f.kind for f in kept], ["github-pat"])
        self.assertEqual(allowed, [generic])

    def test_findings_without_fingerprint_are_never_allowed(self):
        found = scan_names([".env"])
        self.assertEqual(split_allowed(found, frozenset({""})), (found, []))


if __name__ == "__main__":
    unittest.main()
