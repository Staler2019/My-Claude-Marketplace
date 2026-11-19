"""Tests for require-plan-structure.py: a plan-verifier dispatch in, a deny decision (or nothing) out."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "require-plan-structure.py"
SAID = "add a filter button that shows only pinned tags"
PLAN = f"""# Plan

## Outcome
- O1: A Local button hides every non-local branch.
  > {SAID}

## Change inventory
| Location | Expected change | Serves |
|---|---|---|
| `src/list.py:L2-L3` | add the toggle | O1 |
"""


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "list.py").write_text("a\nb\nc\n", encoding="utf-8")
        (self.tmp / "plan.md").write_text(PLAN, encoding="utf-8")
        self.transcript = self.tmp / "t.jsonl"
        self.elsewhere = self.tmp / "elsewhere"  # the hook process runs here, not in the session cwd
        self.elsewhere.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def say(self, *entries):
        with open(self.transcript, "w", encoding="utf-8") as out:
            for entry in entries:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def run_hook(self, tool_input, tool="Agent", cwd=None):
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or self.tmp),
                   "transcript_path": str(self.transcript), "session_id": "s"}
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", cwd=self.elsewhere, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            return None
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    def verifier(self, prompt="Review unit S1.\nPlan: plan.md\n"):
        return {"subagent_type": "plan-verifier", "prompt": prompt, "description": "review"}

    def test_plugin_namespaced_verifier_is_checked_too(self):
        self.say()
        brief = dict(self.verifier(), subagent_type="dev-harness:plan-verifier")
        reason = self.run_hook(brief)
        self.assertTrue(reason.startswith("Blocked by dev-harness/require-plan-structure: "), reason)

    def test_other_agents_pass_through(self):
        self.assertIsNone(self.run_hook({"subagent_type": "scout", "prompt": "find x"}))

    def test_valid_plan_with_user_quote_is_allowed(self):
        self.say({"type": "user", "message": {"role": "user", "content": f"請做：{SAID}"}})
        self.assertIsNone(self.run_hook(self.verifier()))

    def test_legacy_task_tool_name_is_checked(self):
        self.say()
        self.assertIsNotNone(self.run_hook(self.verifier(), tool="Task"))

    def test_text_block_content_counts_as_user_words(self):
        self.say({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": SAID}]}})
        self.assertIsNone(self.run_hook(self.verifier()))

    def test_quote_whitespace_is_normalised(self):
        self.say({"type": "user", "message": {"role": "user",
                                              "content": SAID.replace(" shows", "\n shows").replace("filter", "filter  ")}})
        self.assertIsNone(self.run_hook(self.verifier()))

    def test_brief_without_plan_path_is_denied(self):
        reason = self.run_hook(self.verifier(prompt="Review unit S1."))
        self.assertIn("Plan:", reason)

    def test_missing_plan_file_is_denied(self):
        reason = self.run_hook(self.verifier(prompt="Plan: nope.md"))
        self.assertIn("nope.md", reason)

    def test_quote_only_in_tool_result_is_not_user_words(self):
        self.say({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": SAID}]}})
        self.assertIn("transcript", self.run_hook(self.verifier()))

    def test_quote_only_in_system_reminder_is_not_user_words(self):
        self.say({"type": "user", "message": {"role": "user",
                                              "content": f"hi <system-reminder>{SAID}</system-reminder>"}})
        self.assertIn("transcript", self.run_hook(self.verifier()))

    def test_quote_only_in_meta_message_is_not_user_words(self):
        self.say({"type": "user", "isMeta": True, "message": {"role": "user", "content": SAID}})
        self.assertIn("transcript", self.run_hook(self.verifier()))

    def test_quote_only_from_assistant_is_not_user_words(self):
        self.say({"type": "assistant", "message": {"role": "assistant",
                                                   "content": [{"type": "text", "text": SAID}]}})
        self.assertIn("transcript", self.run_hook(self.verifier()))

    def test_cited_lines_resolve_against_the_repo_root_from_a_subdirectory(self):
        self.say({"type": "user", "message": {"role": "user", "content": SAID}})
        (self.tmp / ".git").mkdir()
        self.assertIsNone(self.run_hook(self.verifier(prompt=f"Plan: {self.tmp / 'plan.md'}"), cwd=self.tmp / "src"))

    def test_a_worktree_git_file_marks_the_repo_root(self):
        self.say({"type": "user", "message": {"role": "user", "content": SAID}})
        (self.tmp / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        self.assertIsNone(self.run_hook(self.verifier(prompt=f"Plan: {self.tmp / 'plan.md'}"), cwd=self.tmp / "src"))

    def test_not_found_names_the_directory_it_resolved_against(self):
        self.say({"type": "user", "message": {"role": "user", "content": SAID}})
        reason = self.run_hook(self.verifier(prompt=f"Plan: {self.tmp / 'plan.md'}"), cwd=self.tmp / "src")
        self.assertIn(f"relative to {self.tmp / 'src'}", reason)

    def test_cited_lines_resolve_against_cwd(self):
        self.say({"type": "user", "message": {"role": "user", "content": SAID}})
        (self.tmp / "src" / "list.py").write_text("a\n", encoding="utf-8")
        self.assertIn("src/list.py", self.run_hook(self.verifier()))


if __name__ == "__main__":
    unittest.main()
