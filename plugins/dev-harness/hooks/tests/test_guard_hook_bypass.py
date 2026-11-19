"""Tests for guard-hook-bypass.py: stdin JSON in, a deny decision (or nothing) out."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
HOOK = Path(os.environ.get("HOOK_UNDER_TEST", HOOKS / "guard-hook-bypass.py"))
SKIP = "--no-" + "verify"


def decide(command):
    proc = subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"tool_input": {"command": command}}),
                          text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


class Denied(unittest.TestCase):
    def assert_denied(self, naming, *commands):
        for command in commands:
            with self.subTest(command=command):
                decision, reason = decide(command)
                self.assertEqual(decision, "deny")
                self.assertTrue(reason.startswith("Blocked by dev-harness/guard-hook-bypass:"))
                self.assertIn(naming, reason)

    def test_long_flag_on_any_git_command_even_wrapped(self):
        self.assert_denied(SKIP, f"git commit {SKIP} -m x", f"git push {SKIP}",
                           f"sh -c 'git commit {SKIP} -m x'", f"git merge {SKIP} side")

    def test_abbreviated_or_quote_split_long_flag(self):
        # git accepts any unique prefix of a long option, and the shell joins quoted pieces.
        self.assert_denied(SKIP, f"git commit {SKIP[:-1]} -m x",
                           "git commit --no-\\\nverify -m x", 'git commit "--no-\\\nverify" -m x',
                           "git commit --no-{verify,verify} -m x", f"g'i't commit {SKIP} -m x",
                           f"gi\\t commit {SKIP} -m x",
                           f"git push {SKIP[:-2]} origin main", f"git commit '{SKIP[:-1]}''y' -m x",
                           'git commit "--no-"verify -m x', "git commit -m x --no-$'verify'",
                           "git commit --no-$'ver'ify -m x", 'git commit --no-$"verify" -m x',
                           "git push origin main --no-$'verif'")

    def test_short_n_on_commit(self):
        self.assert_denied("-n", "git commit -n -m x", "git commit -nm x", "git commit -m x -n",
                           "git -C repo commit -an")

    def test_hooks_path_override_any_spelling(self):
        self.assert_denied("core.hooksPath", 'sh -c "git -c core.hooksPath=/dev/null commit"',
                           "git -c core.hookspath= push", "git config core.hooksPath /tmp/x")

    def test_config_injection_through_environment(self):
        self.assert_denied("GIT_CONFIG_COUNT", "GIT_CONFIG_COUNT=1 git commit -m x")
        self.assert_denied("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_PARAMETERS=x git push")


class Allowed(unittest.TestCase):
    def test_ordinary_commands(self):
        for command in ('git commit -m "no verify"', "git commit --no-edit", "git log --no-walk",
                        "git fetch --no-verbose", "git commit -mnope", "git commit -m -n",
                        "git log -n 3", "git commit -F notes.txt", "echo hello", ""):
            with self.subTest(command=command):
                self.assertIsNone(decide(command))

    def test_flag_text_without_git_is_not_judged(self):
        self.assertIsNone(decide(f"echo {SKIP}"))


class Registration(unittest.TestCase):
    def test_hooks_json_blocks_when_the_guard_itself_fails(self):
        config = json.loads((HOOKS / "hooks.json").read_text())
        entries = [h for group in config["hooks"]["PreToolUse"] if group.get("matcher") == "Bash"
                   for h in group["hooks"] if "guard-hook-bypass.py" in h["command"]]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get("onFailure"), "block")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard-hook-bypass.py", entries[0]["command"])


if __name__ == "__main__":
    unittest.main()
