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
                           f"sh -c 'git commit {SKIP} -m x'", f"git merge {SKIP} side",
                           f'bash -lc "cd r && git commit {SKIP} -m x"', f'eval "git push {SKIP}"')

    def test_abbreviated_or_quote_split_long_flag(self):
        # git accepts a unique prefix of a long option, and the shell joins quoted pieces.
        self.assert_denied(SKIP, f"git commit {SKIP[:-1]} -m x", f"git push {SKIP[:-2]} origin main",
                           "git commit --no-\\\nverify -m x", 'git commit "--no-\\\nverify" -m x',
                           f"g'i't commit {SKIP} -m x", f"gi\\t commit {SKIP} -m x",
                           "git commit --no-ver``ify -m x", "git commit --no-ver$()ify -m x",
                           f"git commit '{SKIP[:-1]}''y' -m x", 'git commit "--no-"verify -m x',
                           "git commit -m x --no-$'verify'", "git commit --no-$'ver'ify -m x",
                           'git commit --no-$"verify" -m x', "git push origin main --no-$'verif'",
                           f"git commit -m x \\{SKIP}")

    def test_brace_expansion_in_a_git_command(self):
        # Any unquoted brace expansion in a git command is refused: list paths one by one.
        self.assert_denied("brace", "git commit --no-{verify,verify} -m x", "git commit --no-ve{r..r}ify -m x",
                           "git commit --n{o,o}-verify -m x", "g{i..i}t commit -m x",
                           f'echo {{; git commit -m a, {SKIP}; echo }}', 'git commit {-m"x}",--no-ve}rify',
                           "git commit {-m'x}',--no-ve}rify", 'git commit {-m"x{y}",--no-ve}rify',
                           "git commit {-m\\},--no-ve}rify", "git add src/{a,b}.py",
                           "git commit " + "{a,b}" * 9 + " -m x", "git commit {1..1000000000000} -m x")

    def test_short_n_on_commit(self):
        self.assert_denied("-n", "git commit -n -m x", "git commit -nm x", "git commit -m x -n",
                           "git -C repo commit -an", "git commit -m x -\\\nn",
                           "git --attr-source HEAD commit -n -m x", "git --config-env a=B commit -n",
                           "{ git commit -n; }", "if git commit -n -m y; then :; fi", "! git commit -n",
                           "for i in 1; do git commit -n -m x; done", "until git commit -n; do :; done",
                           ">/dev/null git commit -n", "2>/dev/null git commit -n", "nice git commit -n",
                           "timeout 5 git commit -n", "xargs git commit -n", 'echo "<<EOF"\ngit commit -n -m x\nEOF',
                           "bash <<EOF\ngit commit -n -m x\nEOF",
                           "git 2>/dev/null commit -n -m x", "git </dev/null commit -n -m x",
                           "git>/dev/null commit -n -m x", "git commit>/dev/null -n -m x",
                           "git &>/dev/null commit -n", "git >| out commit -n", "git 2> err commit -n",
                           'bash <<<"git commit -n -m x"', "bash<<<'git commit -n -m x'",
                           'git commit -m ">" -n', "git commit -m 'x>' -n", 'git commit -m "a>" -n x',
                           "git -c 'a.b=>' commit -n", "git 2>|out commit -n", "git 1>| out commit -n",
                           "git >! out commit -n", "git >>! out commit -n", "git &>! out commit -n",
                           "git >&! out commit -n", "git {fd}>/dev/null commit -n", "git -c alias.ci=commit ci -n",
                           "git commit -n>/dev/null")

    def test_any_short_cluster_with_n_after_commit_is_refused(self):
        # Conservative: no option parsing, so a message such as `-m -n` is refused too.
        self.assert_denied("-n", "git commit -m -n", "git commit -mnope", 'git commit -m "-n"')

    def test_long_flag_glued_to_a_redirection(self):
        self.assert_denied(SKIP, f"git commit {SKIP}>/dev/null -m x", f"git push {SKIP[:-1]}2>&1")

    def test_hooks_path_override_any_spelling(self):
        self.assert_denied("core.hooksPath", 'sh -c "git -c core.hooksPath=/dev/null commit"',
                           "git -c core.hookspath= push", "git config core.hooksPath /tmp/x",
                           "git -ccore.hooksPath=/dev/null commit", "git --config-env=core.hooksPath=V commit",
                           "git -c core.hooks'Path'= push", "{ git -c core.hooksPath=/dev/null push origin main; }",
                           "! git -c core.hooksPath=/dev/null push", "2>/dev/null git -c core.hooksPath=/dev/null push",
                           "echo '<<X'\ngit -c core.hooksPath=/dev/null push\nX", "! git config core.hooksPath /dev/null",
                           "git>/dev/null -c core.hooksPath=/dev/null commit -m x",
                           "git 2>&1 -c core.hooksPath=/dev/null commit -m x",
                           'bash <<<"git -c core.hooksPath=/dev/null commit -m x"')

    def test_config_injection_through_environment(self):
        self.assert_denied("GIT_CONFIG_COUNT", "GIT_CONFIG_COUNT=1 git commit -m x")
        self.assert_denied("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_PARAMETERS=x git push")
        self.assert_denied("GIT_CONFIG_GLOBAL", "GIT_CONFIG_GLOBAL=/tmp/c git commit -m x")
        self.assert_denied("GIT_CONFIG_SYSTEM", "GIT_CONFIG_SYSTEM=/tmp/c git push")


class Allowed(unittest.TestCase):
    def test_ordinary_commands(self):
        for command in ('git commit -m "no verify"', "git commit --no-edit", "git log --no-walk",
                        "git fetch --no-verbose", "git merge --no-verify-signatures main",
                        "git log --format=%H,%s", 'git commit -m "{a,b} $HOME"', "git log -n 3", "git commit -F notes.txt", "echo hello", "",
                        f'git commit -m "docs: never pass {SKIP}"', "git add src/a.py src/b.py",
                        "git log --format='{%H,%s}'", "grep -n git notes.txt", "git push -n", "echo core.hooksPath; git status", "git log -n 3 2>&1 | head", "git status >out.txt 2>&1",
                        'git commit -m "a -> b" -F notes.txt', "git commit -m x 2>/dev/null", "git commit -s>/dev/null -m x",
                        "cat <<EOF > notes.txt\nplain text\nEOF\ngit add notes.txt"):
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
