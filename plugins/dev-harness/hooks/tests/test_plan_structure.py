"""Tests for lib/plan_structure.py: Plan text in, every structural violation out at once."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.plan_structure import parse_plan, validate_plan  # noqa: E402

GOOD = """# Plan: local branch filter

## Outcome
- O1: Branch list toolbar has a Local button; pressing it hides every non-local branch.
  > add a filter button that shows only pinned tags

## Change inventory
| Location | Expected change | Serves |
|---|---|---|
| `src/toolbar.py:L12-L30` | add LocalFilter toggle to the toolbar row | O1 |
| `src/filter.py:new` | LocalFilter predicate: keep refs with no remote | O1 |

## Refactor inventory
| Location | Expected change | Serves |
|---|---|---|
| `src/toolbar.py:L40` | extract toolbar builder so the toggle has one home | O1 |
"""

FILES = {"src/toolbar.py": 120}
USER_SAID = "ok add a filter button that shows only pinned tags please"


def check(text, files=FILES, said=USER_SAID):
    return validate_plan(parse_plan(text),
                         quoted=lambda quote: quote in said,
                         line_count=lambda path: files.get(path))


class Valid(unittest.TestCase):
    def test_good_plan_has_no_violations(self):
        self.assertEqual(check(GOOD), [])

    def test_refactor_inventory_is_optional(self):
        text = GOOD.split("## Refactor inventory")[0]
        self.assertEqual(check(text), [])

    def test_single_line_location(self):
        text = GOOD.replace("`src/toolbar.py:L12-L30`", "`src/toolbar.py:L120`")
        self.assertEqual(check(text), [])


class Outcome(unittest.TestCase):
    def test_missing_outcome_section(self):
        text = GOOD.replace("## Outcome", "## Goal")
        self.assertIn("Outcome", " ".join(check(text)))

    def test_outcome_section_without_items(self):
        text = GOOD.replace("- O1: Branch list toolbar", "Branch list toolbar")
        self.assertTrue(any("O<n>" in v for v in check(text)))

    def test_outcome_without_user_quote(self):
        text = GOOD.replace("  > add a filter button that shows only pinned tags\n", "")
        self.assertTrue(any("O1" in v and "quote" in v for v in check(text)))

    def test_quote_not_said_by_user(self):
        self.assertTrue(any("O1" in v and "transcript" in v for v in check(GOOD, said="something else")))


class Inventory(unittest.TestCase):
    def test_missing_change_inventory(self):
        text = GOOD.replace("## Change inventory", "## Changes")
        self.assertIn("Change inventory", " ".join(check(text)))

    def test_change_inventory_without_rows(self):
        start = GOOD.index("| `src/toolbar.py:L12")
        end = GOOD.index("## Refactor")
        text = GOOD[:start] + "\n" + GOOD[end:]
        self.assertTrue(any("Change inventory" in v and "no rows" in v for v in check(text)))

    def test_location_without_line_numbers(self):
        text = GOOD.replace("`src/toolbar.py:L12-L30`", "`src/toolbar.py`")
        self.assertTrue(any("src/toolbar.py" in v and "path:L" in v for v in check(text)))

    def test_line_beyond_end_of_file(self):
        text = GOOD.replace("L12-L30", "L12-L121")
        self.assertTrue(any("L121" in v and "120" in v for v in check(text)))

    def test_range_start_after_end(self):
        text = GOOD.replace("L12-L30", "L30-L12")
        self.assertTrue(any("L30-L12" in v for v in check(text)))

    def test_cited_file_missing(self):
        text = GOOD.replace("`src/toolbar.py:L12-L30`", "`src/gone.py:L1`")
        self.assertTrue(any("src/gone.py" in v and "not found" in v for v in check(text)))

    def test_new_file_that_already_exists(self):
        text = GOOD.replace("`src/filter.py:new`", "`src/toolbar.py:new`")
        self.assertTrue(any("already exists" in v for v in check(text)))

    def test_empty_expected_change(self):
        text = GOOD.replace("add LocalFilter toggle to the toolbar row", " ")
        self.assertTrue(any("expected change" in v for v in check(text)))

    def test_serves_nothing(self):
        text = GOOD.replace("| LocalFilter predicate: keep refs with no remote | O1 |",
                            "| LocalFilter predicate: keep refs with no remote |  |")
        self.assertTrue(any("src/filter.py" in v and "serves" in v for v in check(text)))

    def test_serves_undefined_outcome(self):
        text = GOOD.replace("keep refs with no remote | O1 |", "keep refs with no remote | O2 |")
        self.assertTrue(any("O2" in v for v in check(text)))

    def test_refactor_rows_get_the_same_checks(self):
        text = GOOD.replace("one home | O1 |", "one home | cleanup |")
        self.assertTrue(any("Refactor inventory" in v and "cleanup" in v for v in check(text)))


class FullWidth(unittest.TestCase):
    def test_full_width_colon_names_an_outcome(self):
        self.assertEqual(check(GOOD.replace("- O1: Branch", "- O1：Branch")), [])

    def test_unparsed_outcomes_do_not_cascade_into_every_row(self):
        violations = check(GOOD.replace("- O1: Branch list toolbar", "Branch list toolbar"))
        self.assertEqual(violations, ["`## Outcome` has no `- O<n>: <observable result>` item."])


class AllAtOnce(unittest.TestCase):
    def test_every_violation_is_reported_in_one_pass(self):
        text = (GOOD.replace("L12-L30", "L12-L999")
                .replace("keep refs with no remote | O1 |", "keep refs with no remote | O9 |")
                .replace("one home | O1 |", "one home | |"))
        violations = check(text, said="nothing")
        self.assertEqual(len(violations), 4, violations)


if __name__ == "__main__":
    unittest.main()
