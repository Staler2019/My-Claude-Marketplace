"""Plugin-level contract for the copied hooks: deny prefixes, registration, backup root choice."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
DENYING = {
    "guard-repo-discipline.py": "git add -A",
    "block-fuzzy-kill.py": "pkill foo",
    "guard-hook-bypass.py": "git commit -n -m x",
}
REGISTERED = {
    "guard-hook-bypass.py": "Bash",
    "guard-repo-discipline.py": "Bash",
    "block-fuzzy-kill.py": "Bash",
    "backup-before-git-discard.py": "Bash|PowerShell",
    "require-plan-structure.py": "Agent|Task",
}


def hook_reason(name, command, cwd=None, env=None):
    payload = {"tool_input": {"command": command}, "cwd": str(cwd or HOOKS)}
    proc = subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=30, env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


class DenyPrefix(unittest.TestCase):
    def test_each_guard_names_itself_by_plugin(self):
        for name, command in DENYING.items():
            with self.subTest(hook=name):
                reason = hook_reason(name, command)["permissionDecisionReason"]
                self.assertTrue(reason.startswith(f"Blocked by dev-harness/{name[:-3]}:"), reason)
                self.assertNotIn("~/.claude", reason)

    def test_no_copied_hook_points_at_the_user_profile(self):
        for name in REGISTERED:
            with self.subTest(hook=name):
                self.assertNotIn("~/.claude/hooks", (HOOKS / name).read_text(encoding="utf-8"))


class Registration(unittest.TestCase):
    def test_every_guard_is_registered_once_from_the_plugin_root(self):
        config = json.loads((HOOKS / "hooks.json").read_text())
        for name, matcher in REGISTERED.items():
            with self.subTest(hook=name):
                entries = [h for group in config["hooks"]["PreToolUse"] if group.get("matcher") == matcher
                           for h in group["hooks"] if name in h["command"]]
                self.assertEqual(len(entries), 1)
                self.assertIn(f"${{CLAUDE_PLUGIN_ROOT}}/hooks/{name}", entries[0]["command"])


class BackupRoot(unittest.TestCase):
    """$GIT_DISCARD_BACKUP_ROOT, then $CLAUDE_CONFIG_DIR/backups/git-discard, then ~/.claude/…"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git + ["init", "-q"], cwd=self.repo, check=True)
        (self.repo / "a.txt").write_text("v1\n")
        subprocess.run(git + ["add", "a.txt"], cwd=self.repo, check=True)
        subprocess.run(git + ["commit", "-qm", "init"], cwd=self.repo, check=True)
        (self.repo / "a.txt").write_text("v2\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backup_parent(self, **overrides):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DISCARD_BACKUP_ROOT", "CLAUDE_CONFIG_DIR")}
        env.update(HOME=str(self.home), **overrides)
        out = hook_reason("backup-before-git-discard.py", "git reset --hard", self.repo, env)
        where = out["additionalContext"].rsplit(": ", 1)[1]
        return Path(where).parent

    def test_explicit_root_wins(self):
        explicit = self.tmp / "explicit"
        self.assertEqual(self.backup_parent(GIT_DISCARD_BACKUP_ROOT=str(explicit),
                                            CLAUDE_CONFIG_DIR=str(self.tmp / "profile")), explicit)

    def test_profile_dir_is_next(self):
        profile = self.tmp / "profile"
        self.assertEqual(self.backup_parent(CLAUDE_CONFIG_DIR=str(profile)),
                         profile / "backups" / "git-discard")

    def test_empty_or_relative_values_fall_through_to_home(self):
        fallback = self.home / ".claude" / "backups" / "git-discard"
        self.assertEqual(self.backup_parent(), fallback)
        self.assertEqual(self.backup_parent(GIT_DISCARD_BACKUP_ROOT="", CLAUDE_CONFIG_DIR="rel"), fallback)


if __name__ == "__main__":
    unittest.main()
