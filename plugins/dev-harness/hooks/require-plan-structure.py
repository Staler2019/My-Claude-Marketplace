#!/usr/bin/env python3
"""PreToolUse(Agent|Task): a plan-verifier dispatch needs a Plan with user-given outcomes and line-cited changes.

The brief must carry a `Plan: <path>` line. The Plan needs `## Outcome` items that quote the user's own
words from this session's transcript, and a `## Change inventory` (plus an optional `## Refactor
inventory`) whose rows cite existing lines, say what changes there, and name the outcome they serve.
Locations resolve against the repo root holding the session cwd (cwd itself outside a repo).
Every violation is reported in one deny, so the Plan goes back to its author whole. Structure only:
whether a change is predictable and serves only its outcome stays plan-verifier's judgment.
"""
import json
import os
import sys

from adapters import plan_env
from lib.plan_structure import parse_plan, validate_plan

PREFIX = "Blocked by dev-harness/require-plan-structure: "
VERIFIERS = ("plan-verifier", "dev-harness:plan-verifier")


def check(tool_input: dict, cwd: str, transcript_path: str):
    path = plan_env.plan_path(tool_input.get("prompt", ""), cwd)
    if path is None:
        return f"{PREFIX}the plan-verifier brief needs a `Plan: <path>` line naming the Plan file."
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return f"{PREFIX}Plan file {path} cannot be read."
    base = plan_env.location_base(cwd)
    violations = validate_plan(parse_plan(text), quoted=plan_env.quote_checker(transcript_path),
                               line_count=plan_env.line_counter(base))
    if not violations:
        return None
    return (f"{PREFIX}{path} is not ready for plan-verifier (Locations resolve relative to {base}). "
            "Fix all of these first:\n- " + "\n- ".join(violations))


def main() -> None:
    try:
        event = json.load(sys.stdin.buffer)
        tool_input = event.get("tool_input") or {}
        if event.get("tool_name") not in ("Agent", "Task") or tool_input.get("subagent_type") not in VERIFIERS:
            return
        reason = check(tool_input, event.get("cwd") or os.getcwd(), event.get("transcript_path") or "")
    except (ValueError, AttributeError, TypeError):
        return
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))


main()
