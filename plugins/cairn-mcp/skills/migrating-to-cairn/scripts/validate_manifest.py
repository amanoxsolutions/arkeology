#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Validate CAIRN_IMPORT.yaml before executing migration (Step 3.B5).

Checks that every status=pending entry has all required fields populated.
Exits 0 if valid, 1 if any issue is found.
"""

import sys
from pathlib import Path

import yaml

REQUIRED_GLOBAL: list[str] = ["team", "project", "visibility"]
REQUIRED_ENTRY: list[str] = ["path", "type", "tier", "date", "description"]


def main() -> int:
    manifest_path = Path("CAIRN_IMPORT.yaml")
    if not manifest_path.exists():
        print("ERROR: CAIRN_IMPORT.yaml not found in the current directory.")
        return 1

    data = yaml.safe_load(manifest_path.read_text())
    errors: list[str] = []

    global_section = data.get("global", {})
    for field in REQUIRED_GLOBAL:
        if not global_section.get(field):
            errors.append(f"global.{field} is missing or empty")

    artifacts = data.get("artifacts", [])
    pending = 0
    for i, entry in enumerate(artifacts):
        if entry.get("status") != "pending":
            continue
        pending += 1
        label = entry.get("path", f"artifacts[{i}]")
        for field in REQUIRED_ENTRY:
            if not entry.get(field):
                errors.append(f"{label}: '{field}' is missing or empty")

    if errors:
        print(f"CAIRN_IMPORT.yaml validation FAILED — {len(errors)} issue(s):\n")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"CAIRN_IMPORT.yaml OK — {pending} pending entries ready to migrate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
