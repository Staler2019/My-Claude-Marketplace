"""Contract for agents/executor.md: its tools, no pinned model, and the fixed final line."""
import unittest
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent.parent / "agents" / "executor.md"


def split(text):
    _, front, body = text.split("---\n", 2)
    fields = {}
    for line in front.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


class ExecutorAgent(unittest.TestCase):
    def setUp(self):
        self.fields, self.body = split(AGENT.read_text(encoding="utf-8"))

    def test_name_and_tools(self):
        self.assertEqual(self.fields["name"], "executor")
        self.assertEqual([t.strip() for t in self.fields["tools"].split(",")],
                         ["Read", "Write", "Edit", "Glob", "Grep", "Bash"])
        self.assertEqual([t.strip() for t in self.fields["disallowedTools"].split(",")],
                         ["Agent", "Workflow"])

    def test_no_pinned_model(self):
        # The dispatcher passes haiku, sonnet or opus; a pinned model would override it.
        self.assertNotIn("model", self.fields)

    def test_both_final_line_formats(self):
        self.assertIn("EXECUTOR: DONE <first-sha>..<last-sha>", self.body)
        self.assertIn("EXECUTOR: BAIL <one-line reason>", self.body)

    def test_role_rules(self):
        for phrase in ("bail", "never push", "test first", "stage by file"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body.casefold())


if __name__ == "__main__":
    unittest.main()
