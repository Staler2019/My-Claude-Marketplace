"""Plan structure required before a plan-verifier dispatch: user-given outcomes and line-cited inventories.

    ## Outcome
    - O1: <observable result>
      > <the user's own words>

    ## Change inventory            (required; `## Refactor inventory` is optional, same table)
    | Location | Expected change | Serves |
    |---|---|---|
    | `path:L12-L30` / `path:L12` / `path:new` | <what changes there> | O1 |

Pure: the transcript and the filesystem come in as `quoted` and `line_count` callables.
"""
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

OUTCOME, CHANGES, REFACTOR = "Outcome", "Change inventory", "Refactor inventory"
_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_OUTCOME_ITEM = re.compile(r"^\s*[-*]\s+(O\d+)\s*[:：]\s*(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_LOCATION = re.compile(r"^(?P<path>.+?):(?:L(?P<start>\d+)(?:-L?(?P<end>\d+))?|(?P<new>new))$")


@dataclass(frozen=True)
class Outcome:
    id: str
    text: str
    quotes: Tuple[str, ...]


@dataclass(frozen=True)
class Row:
    section: str
    location: str
    expected: str
    serves: Tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    outcomes: Optional[Tuple[Outcome, ...]]  # None: no such section
    changes: Optional[Tuple[Row, ...]]
    refactors: Optional[Tuple[Row, ...]]


def _sections(text: str) -> dict:
    sections, current = {}, None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            current = next((name for name in (OUTCOME, CHANGES, REFACTOR)
                            if heading.group(1).lower().startswith(name.lower())), None)
            if current:
                sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def _outcomes(lines) -> Tuple[Outcome, ...]:
    items = []
    for line in lines:
        item, quote = _OUTCOME_ITEM.match(line), _QUOTE.match(line)
        if item:
            items.append((item.group(1), item.group(2).strip(), []))
        elif quote and items and quote.group(1).strip():
            items[-1][2].append(quote.group(1).strip())
    return tuple(Outcome(id_, text, tuple(quotes)) for id_, text, quotes in items)


def _cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _rows(section: str, lines) -> Tuple[Row, ...]:
    table = [line for line in lines if line.strip().startswith("|")]
    if len(table) < 2:
        return ()
    header = [cell.lower() for cell in _cells(table[0])]

    def cell(cells, name):
        at = header.index(name) if name in header else None
        return cells[at] if at is not None and at < len(cells) else ""

    rows = []
    for line in table[2:]:
        cells = _cells(line)
        serves = tuple(part for part in re.split(r"[,\s]+", cell(cells, "serves")) if part)
        rows.append(Row(section, cell(cells, "location").strip("`"), cell(cells, "expected change"), serves))
    return tuple(rows)


def parse_plan(text: str) -> Plan:
    sections = _sections(text)
    return Plan(
        outcomes=_outcomes(sections[OUTCOME]) if OUTCOME in sections else None,
        changes=_rows(CHANGES, sections[CHANGES]) if CHANGES in sections else None,
        refactors=_rows(REFACTOR, sections[REFACTOR]) if REFACTOR in sections else None,
    )


def _row_violations(row: Row, outcome_ids, line_count) -> List[str]:
    where = f"{row.section} `{row.location}`"
    found = []
    location = _LOCATION.match(row.location)
    if not location:
        found.append(f"{where}: location must be path:L<start>-L<end>, path:L<line>, or path:new.")
    else:
        path, lines = location.group("path"), line_count(location.group("path"))
        if location.group("new"):
            if lines is not None:
                found.append(f"{where}: {path} already exists; cite the lines it changes.")
        else:
            start, end = int(location.group("start")), int(location.group("end") or location.group("start"))
            if lines is None:
                found.append(f"{where}: {path} not found.")
            elif start < 1 or start > end:
                found.append(f"{where}: range is empty or reversed.")
            elif end > lines:
                found.append(f"{where}: L{end} is past the end of {path} ({lines} lines).")
    if not row.expected:
        found.append(f"{where}: no expected change.")
    if not row.serves:
        found.append(f"{where}: serves no outcome; name the O<n> it serves.")
    for id_ in row.serves:
        if outcome_ids and id_ not in outcome_ids:  # no outcomes at all is reported once, not per row
            found.append(f"{where}: serves {id_}, which is not an outcome.")
    return found


def validate_plan(plan: Plan, quoted: Callable[[str], bool],
                  line_count: Callable[[str], Optional[int]]) -> List[str]:
    """Every violation in one list; empty when the Plan may go to plan-verifier."""
    found = []
    if plan.outcomes is None:
        found.append(f"No `## {OUTCOME}` section.")
    elif not plan.outcomes:
        found.append(f"`## {OUTCOME}` has no `- O<n>: <observable result>` item.")
    for outcome in plan.outcomes or ():
        if not outcome.quotes:
            found.append(f"{outcome.id}: no `> ` quote of the user's own words.")
        for quote in outcome.quotes:
            if not quoted(quote):
                found.append(f"{outcome.id}: quote not found in the user's messages in this transcript: {quote}")
    outcome_ids = {outcome.id for outcome in plan.outcomes or ()}
    if plan.changes is None:
        found.append(f"No `## {CHANGES}` section.")
    elif not plan.changes:
        found.append(f"`## {CHANGES}` has no rows.")
    if plan.refactors is not None and not plan.refactors:
        found.append(f"`## {REFACTOR}` has no rows; drop the section or fill it.")
    for row in (plan.changes or ()) + (plan.refactors or ()):
        found.extend(_row_violations(row, outcome_ids, line_count))
    return found
