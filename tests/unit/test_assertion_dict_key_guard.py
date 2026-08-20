"""Guard: dict keys asserted on in tests must exist somewhere in src/.

Regression test for Recommendation 3 of
.docs/reviews/review-2026-08-20-test-suite-assertion-strength.md — the audit found 42
test assertions of the shape `result.get("error_type") is not None`, where
`error_type` is a dict key production code never emits. The disjunct they were part of
was therefore permanently False, silently reducing the assertion to a no-op. Pass 1
(commit 0eae34b) fixed the 42 sites; this guard makes the bug class mechanically
detectable so it cannot silently reappear: any string-literal dict key referenced via
`.get("key")` or `d["key"]` inside a test's `assert` expression must exist as a string
literal somewhere in src/.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "arkeology"
TESTS_ROOT = Path(__file__).resolve().parent.parent

# Keys legitimately absent from src/ — not instances of the dead-disjunct bug class.
# Grouped by originating file/reason, each group commented. Verified against the live
# suite on 2026-08-20 (see .docs/reviews/review-2026-08-20-test-suite-assertion-strength.md,
# Recommendation 3); none of these trace to a src/ response contract.
ALLOWLIST: set[str] = {
    # test_s3.py: arbitrary caller-chosen key in a generic metadata dict round-tripped
    # through S3ClientImpl; not tied to any specific src/ literal.
    "artifact_type",
    # test_vectors.py: raw boto3 S3 Vectors GetVectors/DeleteVectors request kwargs,
    # captured via mocker.spy on the underlying boto3 client method.
    "keys",
    "returnData",
    # test_vectors.py: test-chosen vector key labels used to assert similarity ranking
    # order, not schema fields.
    "near",
    "mid",
    "far",
    # test_failure_log.py: caller-chosen field in a passthrough entry dict —
    # append_failure_entry writes back whatever the caller supplies; no src/ schema
    # names this key.
    "raw_error",
    # test_references_resolution.py: test-chosen manifest paths used as data
    # values/lookup keys in build_path_to_id_map's result, not schema field names.
    "docs/spec/search.md",
    "docs/notes/readme.txt",
    "docs/notes/README",
    "docs/decisions/b.md",
    "docs/adr/001-use-s3.md",
    "decisions/B.md",
    "dir/sibling.md",
    # test_server.py / test_tools_migrate_artifacts.py / test_tools_archive.py /
    # test_tools_link_metadata.py / test_tools_write.py: real src/ parameter names
    # asserted via a mock's captured call kwargs (e.g. call_args.kwargs["if_match"]).
    # Keyword-argument names are AST identifiers, not string-literal constants, so
    # they are structurally invisible to the src/ literal collector even when correct.
    "artifact_concurrency",
    "artifact_ids",
    "since_ulid",
    "if_match",
    "if_none_match",
    # test_tools_link_metadata.py: purely local test counter dict
    # (call_count = {"n": 0}), unrelated to any src/ dict.
    "n",
    # test_tools_list.py: test-fixture artifact IDs used as lookup keys in a dict
    # built by the test itself ({a["artifact_id"]: a for a in ...}), not schema
    # field names.
    "other-team/t3-with-refs-a",
    "other-team/t3-with-refs-b",
    "artifacts/own-with-refs-spy",
    "other-team/t3-with-missing-ref",
    "other-team/t3-with-own-ref",
}


def _dict_key_from_node(node: ast.AST) -> set[str]:
    """Return the string-literal dict key `node` references, if any."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return {node.args[0].value}
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return {sl.value}
    return set()


def _assert_dict_keys(func_node: ast.AST) -> set[str]:
    """Collect every string-literal dict key referenced inside `func_node`'s assert expressions."""
    keys: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                keys |= _dict_key_from_node(sub)
    return keys


def _iter_test_function_assert_keys(tree: ast.Module) -> list[tuple[str, set[str]]]:
    """Yield (function_name, keys) for every test_* function/method with asserted dict keys."""
    results: list[tuple[str, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test_"
        ):
            keys = _assert_dict_keys(node)
            if keys:
                results.append((node.name, keys))
    return results


def _collect_src_literals(src_root: Path) -> set[str]:
    """Collect every string-literal constant appearing anywhere in src_root's .py files."""
    literals: set[str] = set()
    for path in src_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    return literals


# --- Self-check (TDD red/green proof that the scanner has teeth) ----------------------


def test_scanner_flags_key_absent_from_src_literal_set() -> None:
    """Self-check: scanner flags a key absent from src (the historical error_type shape)."""
    source = (
        "def test_credential_error():\n"
        "    result = {}\n"
        '    assert "error" in result or result.get("error_type") is not None\n'
    )
    tree = ast.parse(source)
    fake_src_literals = {"error", "message"}  # "error_type" deliberately absent

    findings = [
        key
        for _, keys in _iter_test_function_assert_keys(tree)
        for key in keys
        if key not in fake_src_literals
    ]

    assert findings == ["error_type"]


def test_scanner_does_not_flag_key_present_in_src_literal_set() -> None:
    """Self-check: scanner does not flag a key that legitimately exists in src/."""
    source = (
        "def test_credential_error():\n"
        "    result = {}\n"
        '    assert result.get("error") == "credential_error"\n'
    )
    tree = ast.parse(source)
    fake_src_literals = {"error", "credential_error"}

    findings = [
        key
        for _, keys in _iter_test_function_assert_keys(tree)
        for key in keys
        if key not in fake_src_literals
    ]

    assert findings == []


# --- Real guard, run against the live suite --------------------------------------------


def test_no_dead_assertion_dict_keys() -> None:
    """Every dict key asserted on in tests/ must exist as a string literal somewhere in src/."""
    src_literals = _collect_src_literals(SRC_ROOT)
    findings: list[str] = []

    for path in sorted(TESTS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func_name, keys in _iter_test_function_assert_keys(tree):
            for key in sorted(keys):
                if key in src_literals or key in ALLOWLIST:
                    continue
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}::{func_name} asserts on dict key "
                    f"{key!r}, which appears nowhere in src/"
                )

    assert not findings, "Dead/typo dict keys referenced in test assertions:\n" + "\n".join(
        findings
    )
