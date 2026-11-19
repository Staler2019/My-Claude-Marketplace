"""Tests for scripts/install-git-hooks: what it copies, and when it refuses."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent.parent / "scripts" / "install-git-hooks"
COPIED = {"pre-commit", "pre-push", "dev_harness_hook.py", "secret_scan.py", "dev-harness.conf"}


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.org",
                        GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.org")
        (self.tmp / "gitconfig").write_text("")
        self.repo = self.tmp / "repo"
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        self.hooks = self.repo / ".git" / "hooks"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                              capture_output=True, text=True, check=True)

    def install(self, *args, target=None):
        return subprocess.run([sys.executable, str(INSTALLER), *args, str(target or self.repo)],
                              env=self.env, capture_output=True, text=True)

    def dev_harness_files(self):
        return {p.name for p in self.hooks.iterdir() if not p.name.endswith(".sample")}

    def test_copies_a_self_contained_set_and_lists_it(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dev_harness_files(), COPIED)
        for name in COPIED:
            self.assertIn(str(self.hooks / name), result.stdout)
        for hook in ("pre-commit", "pre-push"):
            self.assertTrue(os.access(self.hooks / hook, os.X_OK))
        self.assertEqual((self.hooks / "dev-harness.conf").read_text(), "personal=on\n")

    def test_no_personal_flag_is_recorded(self):
        self.install("--no-personal")
        self.assertEqual((self.hooks / "dev-harness.conf").read_text(), "personal=off\n")

    def test_reinstall_over_its_own_hooks(self):
        self.install()
        self.assertEqual(self.install().returncode, 0)

    def test_refuses_to_overwrite_a_foreign_hook(self):
        (self.hooks / "pre-push").write_text("#!/bin/sh\necho mine\n")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.hooks / "pre-push").read_text(), "#!/bin/sh\necho mine\n")
        self.assertEqual(self.dev_harness_files(), {"pre-push"})

    def test_refuses_a_linked_worktree_and_writes_nothing(self):
        self.git("commit", "-q", "--allow-empty", "-m", "root")
        linked = self.tmp / "linked"
        self.git("worktree", "add", "-q", "-b", "side", str(linked))
        result = self.install(target=linked)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree", result.stderr)
        self.assertEqual(self.dev_harness_files(), set())

    def test_refuses_when_core_hooks_path_is_set(self):
        self.git("config", "core.hooksPath", str(self.tmp / "elsewhere"))
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.dev_harness_files(), set())


if __name__ == "__main__":
    unittest.main()
