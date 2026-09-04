#!/usr/bin/env python3
"""Validate SKILL.md frontmatter description values for gh-compatibility.

gh skill install uses a Go YAML parser that rejects plain scalars containing
': ' (colon-space). Any description value with ': ' must be wrapped in double
quotes. This script enforces that rule at commit time.
"""

import sys
from pathlib import Path


def check_description_line(line: str) -> tuple[bool, str]:
    """Return (ok, problem) for a 'description:' frontmatter line.

    A description is problematic if its value contains ': ' and is not
    wrapped in double quotes (value starts with '"' and ends with '"').
    """
    value = line[len("description:") :].strip()
    if ": " not in value:
        return True, ""
    if value.startswith('"') and value.endswith('"'):
        return True, ""
    return False, f"description value contains ': ' but is not double-quoted: {value!r}"


def check_skill_file(path: Path) -> list[str]:
    """Return a list of error messages for the given SKILL.md path."""
    errors: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read file: {exc}"]

    lines = content.splitlines()
    in_frontmatter = False
    frontmatter_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            frontmatter_count += 1
            if frontmatter_count == 1:
                in_frontmatter = True
            elif frontmatter_count == 2:
                in_frontmatter = False
            continue

        if in_frontmatter and line.startswith("description:"):
            ok, problem = check_description_line(line)
            if not ok:
                errors.append(f"{path}: {problem}")

    return errors


def main() -> int:
    skills_dir = Path(__file__).parent.parent / "plugins" / "arkeology" / "skills"
    if not skills_dir.exists():
        print("No plugins/arkeology/skills/ directory found — nothing to validate.")
        return 0

    all_errors: list[str] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        errors = check_skill_file(skill_md)
        all_errors.extend(errors)

    if all_errors:
        print("SKILL.md description validation failed:")
        for error in all_errors:
            print(f"  {error}")
        print()
        print("Fix: wrap the description value in double quotes, e.g.:")
        print('  description: "My skill: a description with a colon"')
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
