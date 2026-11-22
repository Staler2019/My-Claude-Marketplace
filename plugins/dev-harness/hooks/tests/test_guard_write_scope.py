"""Tests for guard-write-scope.py: stdin JSON in, a deny decision (or nothing) out."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
HOOK = HOOKS / "guard-write-scope.py"
PREFIX = "Blocked by dev-harness/guard-write-scope:"


class WriteScope(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.tmp / "repo"
        (self.repo / ".git" / "hooks").mkdir(parents=True)
        (self.repo / ".git" / "modules" / "sub" / "hooks").mkdir(parents=True)
        self.profile = self.tmp / "profile"
        (self.profile / "plugins").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def decide(self, path, tool="Write", key="file_path", profile=None, home=None, cwd=None):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        if profile is not None:
            env["CLAUDE_CONFIG_DIR"] = str(profile)
        if home is not None:
            env["HOME"] = str(home)
        payload = {"tool_name": tool, "tool_input": {key: str(path)}, "cwd": str(cwd or self.repo)}
        # The hook process runs elsewhere: only the payload's cwd may anchor a relative path.
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                              capture_output=True, timeout=10, env=env, cwd=str(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            return None
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    def assert_denied(self, path, **kw):
        reason = self.decide(path, **kw)
        self.assertIsNotNone(reason, path)
        self.assertTrue(reason.startswith(PREFIX), reason)

    def test_git_hooks_in_any_case(self):
        self.assert_denied(self.repo / ".git" / "hooks" / "pre-commit")
        self.assert_denied(self.repo / ".GIT" / "Hooks" / "pre-push")

    def test_submodule_hooks(self):
        self.assert_denied(self.repo / ".git" / "modules" / "sub" / "hooks" / "pre-commit")

    def test_symlink_into_git_hooks(self):
        (self.repo / "link").symlink_to(self.repo / ".git" / "hooks")
        self.assert_denied(self.repo / "link" / "pre-commit")

    def test_dot_dot_and_relative_paths(self):
        self.assert_denied(self.repo / "src" / ".." / ".git" / "hooks" / "x")
        self.assert_denied(".git/hooks/x")
        self.assert_denied("settings.json", profile=self.profile, cwd=self.profile)

    def test_git_config(self):
        self.assert_denied(self.repo / ".git" / "config")

    def test_profile_settings_and_plugins(self):
        self.assert_denied(self.profile / "settings.json", profile=self.profile)
        self.assert_denied(self.profile / "settings.local.json", profile=self.profile)
        self.assert_denied(self.profile / "plugins" / "x" / "hooks.json", profile=self.profile)

    def test_default_profile_is_home_dot_claude(self):
        home = self.tmp / "home"
        (home / ".claude").mkdir(parents=True)
        self.assert_denied(home / ".claude" / "settings.json", home=home)

    def test_the_loaded_plugin_root(self):
        self.assert_denied(HOOKS / "guard-write-scope.py")
        self.assert_denied(HOOKS.parent / "README.md")

    def test_every_write_tool(self):
        target = self.repo / ".git" / "hooks" / "x"
        for tool in ("Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                self.assert_denied(target, tool=tool)
        self.assert_denied(target, tool="NotebookEdit", key="notebook_path")

    def test_ordinary_files_are_allowed(self):
        for path in (self.repo / "src" / "a.py", self.repo / "hooks" / "x.py",
                     self.repo / ".github" / "workflows" / "ci.yml",
                     self.profile / "CLAUDE.md", self.profile / "plans" / "p.md"):
            with self.subTest(path=path):
                self.assertIsNone(self.decide(path, profile=self.profile))

    def test_unparseable_input_is_ignored(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True,
                              capture_output=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
