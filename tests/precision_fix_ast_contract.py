"""Allow only the reviewed missing-input/entry-basis fixes in older AST audits.

Behavior is covered by test_precision_review_fixes and test_precision_plan_panel.
Pin entire corrected functions so unrelated future edits cannot be hidden here.
"""
import ast
from copy import deepcopy
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess


APPROVED = {
    "render_entry_execution_plan": "be68d2a9c292421959d2abdbe3015dae07c946a7b1ef3552748a6056d7123af6",
    "build_leveraged_precision_state": "705aefd03b11ec293fb61e5fd081cd054665dfbb948c3b0b9fdd850a614356da",
    "build_leveraged_dca_timing_state": "8622477a656e0047abc26ae521035defd39350a273abaf16555ef290dff3ac44",
}


@lru_cache(maxsize=1)
def _before():
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "show", "768ceb5c:app.py"], cwd=root, encoding="utf-8-sig")
    return {n.name: n for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name in APPROVED}


def before_precision_fixes(node):
    if node.name in APPROVED:
        digest = hashlib.sha256(ast.dump(node).encode()).hexdigest()
        if digest == APPROVED[node.name]:
            return deepcopy(_before()[node.name])
    # Unrecognized edits remain visible to the historical equality assertion.
    return node
