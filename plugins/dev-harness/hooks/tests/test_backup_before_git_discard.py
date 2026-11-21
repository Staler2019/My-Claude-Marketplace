"""Tests for backup-before-git-discard.py: a git command that can discard local work backs it up first."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(os.environ.get("HOOK_UNDER_TEST",
                           Path(__file__).resolve().parent.parent / "backup-before-git-discard.py"))


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo,
                   check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.root = self.tmp / "backups"
        self.env = {}
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "tracked.txt").write_text("v1\n")
        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "staged.txt").write_text("s1\n")
        git(self.repo, "add", ".gitignore", "tracked.txt", "sub/staged.txt")
        git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dirty(self):
        (self.repo / "tracked.txt").write_text("v2 modified\n")
        (self.repo / "sub" / "staged.txt").write_text("s2 staged\n")
        git(self.repo, "add", "sub/staged.txt")
        (self.repo / "new file.txt").write_text("untracked\n")
        (self.repo / "ignored.txt").write_text("ignored\n")

    def run_hook(self, command, cwd=None, tool="Bash"):
        payload = {"tool_name": tool, "tool_input": {"command": command},
                   "cwd": str(cwd or self.repo)}
        # cp1252 is a GitHub Windows runner's console encoding; it cannot encode Chinese,
        # so a hook that prints non-ASCII text there crashes instead of reporting.
        env = dict(os.environ, GIT_DISCARD_BACKUP_ROOT=str(self.root),
                   PYTHONIOENCODING="cp1252", **self.env)
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              text=True, capture_output=True, timeout=30, env=env)

    def backups(self):
        return sorted(self.root.iterdir()) if self.root.exists() else []

    def assert_backed_up(self, command, cwd=None, tool="Bash"):
        shutil.rmtree(self.root, ignore_errors=True)
        self.dirty()
        proc = self.run_hook(command, cwd, tool)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dirs = self.backups()
        self.assertEqual(len(dirs), 1, proc.stdout)
        files = dirs[0] / "files"
        self.assertEqual((files / "tracked.txt").read_text(), "v2 modified\n")
        self.assertEqual((files / "sub" / "staged.txt").read_text(), "s2 staged\n")
        self.assertEqual((files / "new file.txt").read_text(), "untracked\n")
        self.assertIn("v2 modified", (dirs[0] / "unstaged.patch").read_text())
        self.assertIn("s2 staged", (dirs[0] / "staged.patch").read_text())
        out = json.loads(proc.stdout)
        self.assertIn(str(dirs[0]), out["systemMessage"])
        self.assertNotIn("permissionDecision", out.get("hookSpecificOutput", {}))
        return files

    def assert_no_backup(self, command, cwd=None):
        shutil.rmtree(self.root, ignore_errors=True)
        self.dirty()
        proc = self.run_hook(command, cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.backups(), [], command)
        self.assertEqual(proc.stdout.strip(), "")


class Reset(Base):
    def test_every_form_of_reset(self):
        for command in ("git reset --hard", "git reset --soft HEAD~1", "git reset",
                        "git reset -- a.txt"):
            with self.subTest(command=command):
                files = self.assert_backed_up(command)
                self.assertFalse((files / "ignored.txt").exists())

    def test_behind_operators_and_git_options(self):
        self.assert_backed_up("git stash && git -c user.name=x reset --hard HEAD")

    def test_cd_into_the_repo_first(self):
        self.assert_backed_up(f'cd "{self.repo}" && git reset --hard', cwd=self.tmp)

    def test_git_dash_C(self):
        self.assert_backed_up(f'git -C "{self.repo}" reset --hard', cwd=self.tmp)

    def test_cd_into_a_subdirectory(self):
        self.assert_backed_up("cd sub; git reset --hard")

    def test_powershell_tool(self):
        self.assert_backed_up("Set-Location sub; git reset --hard; git status", tool="PowerShell")


class OtherDiscards(Base):
    def test_restore(self):
        for command in ("git restore tracked.txt", "git restore --staged sub/staged.txt",
                        "git restore -SW ."):
            with self.subTest(command=command):
                self.assert_backed_up(command)

    def test_checkout_over_files(self):
        for command in ("git checkout -- tracked.txt", "git checkout .",
                        "git checkout HEAD tracked.txt", "git checkout -f main",
                        "git checkout --force main", "git checkout -fb topic",
                        "git checkout -p", "git checkout --theirs tracked.txt"):
            with self.subTest(command=command):
                self.assert_backed_up(command)

    def test_forced_switch(self):
        for command in ("git switch -f main", "git switch --discard-changes main",
                        "git switch --force main"):
            with self.subTest(command=command):
                self.assert_backed_up(command)

    def test_abort_resets_the_worktree(self):
        for command in ("git merge --abort", "git rebase --abort", "git cherry-pick --abort",
                        "git revert --abort", "git am --abort"):
            with self.subTest(command=command):
                self.assert_backed_up(command)

    def test_rm_from_the_worktree(self):
        self.assert_backed_up("git rm tracked.txt")
        self.assert_backed_up("git rm -rf sub")

    def test_clean_backs_up_what_it_would_remove(self):
        for command in ("git clean -fd", "git clean -f -d -- .", "git clean --force"):
            with self.subTest(command=command):
                files = self.assert_backed_up(command)
                self.assertFalse((files / "ignored.txt").exists())

    def test_clean_x_backs_up_ignored_files_too(self):
        files = self.assert_backed_up("git clean -fdx")
        self.assertEqual((files / "ignored.txt").read_text(), "ignored\n")
        files = self.assert_backed_up("git clean -fX")
        self.assertEqual((files / "ignored.txt").read_text(), "ignored\n")

    def test_clean_x_removes_an_ignored_directory(self):
        with open(self.repo / ".gitignore", "a") as f:
            f.write("build/\n")
        (self.repo / "build" / "deep").mkdir(parents=True)
        (self.repo / "build" / "deep" / "out.bin").write_text("artifact\n")
        files = self.assert_backed_up("git clean -fdx")
        self.assertEqual((files / "build" / "deep" / "out.bin").read_text(), "artifact\n")

    def test_quiet_clean_still_lists_what_it_would_remove(self):
        for command in ("git clean -fdx -q", "git clean -qfdx", "git clean --quiet -fdx"):
            with self.subTest(command=command):
                files = self.assert_backed_up(command)
                self.assertEqual((files / "ignored.txt").read_text(), "ignored\n")

    def test_interactive_clean_is_dry_run_without_its_prompt(self):
        files = self.assert_backed_up("git clean -fdxi")
        self.assertEqual((files / "ignored.txt").read_text(), "ignored\n")
        files = self.assert_backed_up("git clean --interactive -fdx")
        self.assertEqual((files / "ignored.txt").read_text(), "ignored\n")


class Skips(Base):
    def test_commands_that_keep_local_work(self):
        for command in ("git status && git log --oneline -3", "git checkout main",
                        "git checkout -b topic", "git checkout -B topic HEAD", "git switch main",
                        "git switch -c topic", "git restore --help", "git rm --cached tracked.txt",
                        "git clean -n", "git clean -fdn", "git clean --dry-run -fd",
                        "git merge topic", "git rebase --continue", "git stash"):
            with self.subTest(command=command):
                self.assert_no_backup(command)

    def test_only_in_quotes_comments_or_heredocs(self):
        for command in ("echo 'git reset --hard'", "git status # git clean -fd",
                        "cat <<EOF\ngit restore .\nEOF"):
            with self.subTest(command=command):
                self.assert_no_backup(command)

    def test_clean_tree_has_nothing_to_back_up(self):
        proc = self.run_hook("git reset --hard")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.backups(), [])

    def test_not_a_repository(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        proc = self.run_hook("git reset --hard", cwd=plain)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.backups(), [])


class Retention(Base):
    DAY = 86400

    def old_backup(self, name, age_days, size=10):
        d = self.root / name
        (d / "files").mkdir(parents=True)
        (d / "files" / "blob").write_bytes(b"x" * size)
        (d / "info.txt").write_text("repo: elsewhere\n")
        when = __import__("time").time() - age_days * self.DAY
        os.utime(d / "info.txt", (when, when))
        return d

    def run_reset(self):
        self.dirty()
        proc = self.run_hook("git reset --hard")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def test_backups_older_than_14_days_are_pruned(self):
        stale = self.old_backup("stale", 15)
        fresh = self.old_backup("fresh", 13)
        self.run_reset()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(len(self.backups()), 2)

    def test_days_can_be_overridden(self):
        self.env["GIT_DISCARD_BACKUP_DAYS"] = "3"
        stale = self.old_backup("stale", 4)
        self.run_reset()
        self.assertFalse(stale.exists())

    def test_a_directory_that_is_not_a_backup_is_never_touched(self):
        foreign = self.root / "mine"
        foreign.mkdir(parents=True)
        (foreign / "notes.txt").write_text("keep")
        os.utime(foreign, (0, 0))
        stale = self.old_backup("stale", 15)
        self.run_reset()
        self.assertTrue((foreign / "notes.txt").exists())
        self.assertFalse(stale.exists())

    def test_oldest_go_first_once_the_total_passes_the_cap(self):
        self.env["GIT_DISCARD_BACKUP_MAX_BYTES"] = "5000"
        oldest = self.old_backup("oldest", 3, size=2000)
        middle = self.old_backup("middle", 2, size=2000)
        newest = self.old_backup("newest", 1, size=2000)
        self.run_reset()
        self.assertFalse(oldest.exists())
        self.assertTrue(middle.exists())
        self.assertTrue(newest.exists())
        self.assertEqual(len(self.backups()), 3)

    def test_a_backup_bigger_than_the_cap_denies_the_command(self):
        self.env["GIT_DISCARD_BACKUP_MAX_BYTES"] = "20"
        proc = self.run_reset()
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("GIT_DISCARD_BACKUP_MAX_BYTES", out["permissionDecisionReason"])
        self.assertEqual(self.backups(), [])

    def test_room_is_made_for_the_new_backup(self):
        self.env["GIT_DISCARD_BACKUP_MAX_BYTES"] = "5000"
        # Each old backup is 2470 + its info.txt (16) = 2486 bytes: 4972 fits on its own,
        # and stops fitting only once the incoming backup (~30 bytes) is counted.
        oldest = self.old_backup("oldest", 2, size=2470)
        newest = self.old_backup("newest", 1, size=2470)
        self.run_reset()
        self.assertFalse(oldest.exists())
        self.assertTrue(newest.exists())

    def test_default_cap_is_two_gibibytes(self):
        src = (Path(HOOK).read_text(encoding="utf-8"))
        self.assertIn("2 * 1024 ** 3", src)
        self.assertIn('"14"', src)


class FailsClosed(Base):
    def test_unwritable_backup_root_denies_the_command(self):
        self.dirty()
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the backup directory should go")
        self.root = blocker / "nested"
        proc = self.run_hook("git reset --hard")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertEqual((self.repo / "tracked.txt").read_text(), "v2 modified\n")


if __name__ == "__main__":
    unittest.main()
