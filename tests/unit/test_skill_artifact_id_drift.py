"""Drift guard: the skills' offline artifact-ID snippets must match the server's algorithm.

``migrating-to-arkeology`` and ``backfilling-references`` each document a standalone
``python3`` snippet that computes an artifact's full key *offline* — before the Arkeology
server is necessarily installed or reachable — so neither can import
:func:`arkeology.artifact.generate_artifact_id`. That duplication is deliberate (see
``docs/specs/p12-t51-migration-reference-rewrite.md``, "Open Questions") and is held to the
server's behaviour by this test rather than by single-sourcing.

Each SKILL.md snippet is extracted from the shipped file (never retyped here), executed as a
real subprocess over a shared input table, and compared against the server-composed full key.
The assertion is on computed identifiers only — never on the skill's source text, which could
be present verbatim and still compute the wrong thing.
"""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from arkeology.artifact import generate_artifact_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO_ROOT / "plugins" / "arkeology" / "skills"

# Every skill that documents its own offline ID computation. A new such skill is one entry.
SKILL_FILES = [
    _SKILLS_DIR / "migrating-to-arkeology" / "SKILL.md",
    _SKILLS_DIR / "backfilling-references" / "SKILL.md",
]

# The snippet is documented as a heredoc: ``python3 - "$TYPE" ... <<'PY' … PY``. Both the body
# and the closing delimiter may be indented (the backfilling skill nests it in a list item).
_SNIPPET_RE = re.compile(r"<<'PY'\n(.*?\n)[ \t]*PY\n", re.DOTALL)

WRITE_PREFIX = "platform/arkeology"

# (case_id, type, tier, date, title, extension)
ID_CASES = [
    ("tier2-plain", "spec", 2, "2026-05-30", "Auth Module Spec", ".md"),
    ("tier3-plain", "runbook", 3, "2026-05-30", "Deploy Runbook", ".md"),
    ("underscore-type", "code_review", 2, "2026-05-30", "Auth Module Review", ".md"),
    ("underscore-type-tier3", "implementation_note", 3, "2026-05-30", "Cache Layer", ".md"),
    ("non-ascii-title", "spec", 2, "2026-05-30", "Café déjà vu — naïve façade", ".md"),
    ("punctuation-collapse-a", "code_review", 2, "2026-05-30", "Auth: Module Review", ".md"),
    ("punctuation-collapse-b", "code_review", 2, "2026-05-30", "Auth module (review)", ".md"),
    ("over-60-char-title", "plan", 2, "2026-05-30", "A" * 40 + " " + "B" * 40, ".md"),
    ("truncation-boundary-dash", "plan", 3, "2026-05-30", "x" * 59 + " tail", ".md"),
    ("empty-slug-title", "adr", 2, "2026-05-30", "日本語のタイトル", ".md"),
    ("empty-slug-punctuation", "adr", 3, "2026-05-30", "!!! ??? ...", ".md"),
    ("no-extension", "prd", 2, "2026-05-30", "Product Requirements", ""),
]


def _extract_snippet(skill_file: Path) -> str:
    """Return the dedented ID-computation snippet documented in ``skill_file``.

    Fails (never skips) when the snippet cannot be located — a missing or renamed block means
    the drift guard is no longer guarding anything.
    """
    if not skill_file.is_file():
        pytest.fail(f"skill file not found: {skill_file}")

    matches = _SNIPPET_RE.findall(skill_file.read_text(encoding="utf-8"))
    if len(matches) != 1:
        pytest.fail(
            f"expected exactly one `<<'PY' … PY` ID-computation snippet in {skill_file}, "
            f"found {len(matches)}. The drift guard cannot locate the documented algorithm — "
            f"restore the heredoc block or update _SNIPPET_RE."
        )
    return textwrap.dedent(matches[0])


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("case", ID_CASES, ids=lambda c: c[0])
def test_skill_snippet_matches_generate_artifact_id(
    skill_file: Path, case: tuple[str, str, int, str, str, str]
) -> None:
    """Verifies each skill's documented offline snippet computes the server's exact full key."""
    case_id, type_, tier, date, title, extension = case
    snippet = _extract_snippet(skill_file)

    completed = subprocess.run(
        [sys.executable, "-c", snippet, type_, str(tier), date, title, extension, WRITE_PREFIX],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"{skill_file.parent.name} snippet failed on case '{case_id}':\n{completed.stderr}"
    )
    skill_key = completed.stdout.strip()
    server_key = (
        f"{WRITE_PREFIX}/"
        f"{generate_artifact_id(tier=tier, type=type_, date=date, title=title)}{extension}"
    )

    assert skill_key == server_key, (
        f"ID drift on case '{case_id}' "
        f"(type={type_!r}, tier={tier}, date={date!r}, title={title!r}, ext={extension!r}):\n"
        f"  {skill_file.parent.name}/SKILL.md → {skill_key}\n"
        f"  generate_artifact_id       → {server_key}\n"
        f"One side moved; the skill snippet and src/arkeology/artifact.py must agree."
    )


def test_punctuation_collapse_cases_share_a_slug() -> None:
    """Verifies the collapse pair really exercises the hash suffix (same slug, distinct keys)."""
    a = generate_artifact_id(
        tier=2, type="code_review", date="2026-05-30", title="Auth: Module Review"
    )
    b = generate_artifact_id(
        tier=2, type="code_review", date="2026-05-30", title="Auth module (review)"
    )

    assert a.rsplit("-", 1)[0] == b.rsplit("-", 1)[0]
    assert a != b
