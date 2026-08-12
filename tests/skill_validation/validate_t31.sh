#!/usr/bin/env bash
# =============================================================================
# T31 Validation Script
#
# Programmatically checks all automatable assertions from specs:
#   - docs/specs/p9-t31a-setting-up-arkeology-skill.md
#   - docs/specs/p9-t31b-migration-skill-exclusion-gate.md
#   - docs/specs/p9-t31c-readme-reduction.md
#
# Usage:
#   bash tests/skill_validation/validate_t31.sh
#
# Exit codes:
#   0 — all checks PASS
#   1 — one or more checks FAIL
#
# TDD RED phase: all checks are expected to FAIL until T31 is implemented.
# Checks that verify already-stable content (retained README sections, sections
# already removed in the T31 scope-correction) will PASS even before T31 —
# that is correct and expected; they are regression guards.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILURES=0

# ── helpers ──────────────────────────────────────────────────────────────────

pass() {
    printf "  PASS: %s\n" "$1"
}

fail() {
    printf "  FAIL: %s\n" "$1"
    FAILURES=$((FAILURES + 1))
}

# Assert FILE exists and contains the extended-regex PATTERN.
# FAIL if file is missing or pattern is absent.
require_in_file() {
    local file="$1" pattern="$2" label="$3"
    if [ -f "$file" ] && grep -qE "$pattern" "$file"; then
        pass "$label"
    else
        fail "$label"
    fi
}

# Assert FILE exists and does NOT contain the extended-regex PATTERN.
# FAIL if file is missing (cannot verify absence) or pattern is present.
forbid_in_file() {
    local file="$1" pattern="$2" label="$3"
    if [ ! -f "$file" ]; then
        fail "$label  [FILE MISSING — cannot verify absence]"
    elif grep -qE "$pattern" "$file"; then
        fail "$label"
    else
        pass "$label"
    fi
}

# Assert FILE exists.
require_file() {
    local file="$1" label="$2"
    if [ -f "$file" ]; then
        pass "$label"
    else
        fail "$label"
    fi
}

# Assert line count of FILE is between MIN and MAX (inclusive).
check_line_count() {
    local file="$1" min="$2" max="$3" label="$4"
    if [ ! -f "$file" ]; then
        fail "$label  [FILE MISSING]"
        return
    fi
    local count
    count=$(wc -l < "$file")
    if [ "$count" -ge "$min" ] && [ "$count" -le "$max" ]; then
        pass "$label  (${count} lines)"
    else
        fail "$label  (${count} lines; expected ${min}–${max})"
    fi
}

# Assert FILE exists and the count of lines matching PATTERN equals EXPECTED.
check_match_count() {
    local file="$1" pattern="$2" expected="$3" label="$4"
    if [ ! -f "$file" ]; then
        fail "$label  [FILE MISSING]"
        return
    fi
    local count
    count=$(grep -cE "$pattern" "$file" || true)
    if [ "$count" -eq "$expected" ]; then
        pass "$label  (${count} match(es))"
    else
        fail "$label  (${count} match(es); expected ${expected})"
    fi
}

# ── file paths ────────────────────────────────────────────────────────────────
SKILL_MD="$REPO_ROOT/skills/setting-up-arkeology/SKILL.md"
AGENTS_SNIPPET="$REPO_ROOT/skills/setting-up-arkeology/references/agents-snippet.md"
MIGRATION_SKILL="$REPO_ROOT/skills/migrating-to-arkeology/SKILL.md"
README="$REPO_ROOT/README.md"


# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "══ T31a: skills/setting-up-arkeology/SKILL.md ══════════════════════════════"
echo ""
# ─── Existence & size ────────────────────────────────────────────────────────

require_file "$SKILL_MD" \
    "T31a [existence] skills/setting-up-arkeology/SKILL.md exists"

check_line_count "$SKILL_MD" 1 500 \
    "T31a [size]      SKILL.md is ≤ 500 lines"

# ─── Exactly 6 numbered step headings ────────────────────────────────────────

check_match_count "$SKILL_MD" '^## Step [0-9]' 6 \
    "T31a [steps]     SKILL.md has exactly 6 ## Step N headings"

require_in_file "$SKILL_MD" '^## Step 1' \
    "T31a [steps]     SKILL.md has ## Step 1 heading"

require_in_file "$SKILL_MD" '^## Step 2' \
    "T31a [steps]     SKILL.md has ## Step 2 heading"

require_in_file "$SKILL_MD" '^## Step 3' \
    "T31a [steps]     SKILL.md has ## Step 3 heading"

require_in_file "$SKILL_MD" '^## Step 4' \
    "T31a [steps]     SKILL.md has ## Step 4 heading"

require_in_file "$SKILL_MD" '^## Step 5' \
    "T31a [steps]     SKILL.md has ## Step 5 heading"

require_in_file "$SKILL_MD" '^## Step 6' \
    "T31a [steps]     SKILL.md has ## Step 6 heading"

# ─── Step 2 pre-flight CLI commands ──────────────────────────────────────────

require_in_file "$SKILL_MD" 'get-caller-identity' \
    "T31a [step2]     SKILL.md Step 2 includes aws sts get-caller-identity check"

require_in_file "$SKILL_MD" 'head-bucket' \
    "T31a [step2]     SKILL.md Step 2 includes s3api head-bucket check"

require_in_file "$SKILL_MD" 'describe-index' \
    "T31a [step2]     SKILL.md Step 2 includes s3vectors describe-index check"

require_in_file "$SKILL_MD" 'invoke-model' \
    "T31a [step2]     SKILL.md Step 2 includes bedrock invoke-model check"

# ─── Step 6 config block ─────────────────────────────────────────────────────

require_in_file "$SKILL_MD" 'arkeology:config' \
    "T31a [step6]     SKILL.md references arkeology:config block"

require_in_file "$SKILL_MD" 'local_only_types' \
    "T31a [step6]     SKILL.md contains local_only_types key"

require_in_file "$SKILL_MD" 'local_only_paths' \
    "T31a [step6]     SKILL.md contains local_only_paths key"

require_in_file "$SKILL_MD" 'adr_strategy' \
    "T31a [step6]     SKILL.md contains adr_strategy key"

require_in_file "$SKILL_MD" 'installed' \
    "T31a [step6]     SKILL.md contains installed key in config block YAML"

require_in_file "$SKILL_MD" 'references/agents-snippet\.md' \
    "T31a [step6]     SKILL.md instructs agent to load references/agents-snippet.md"

# ─── Forbidden content ────────────────────────────────────────────────────────

forbid_in_file "$SKILL_MD" 'create-bucket' \
    "T31a [bounds]    SKILL.md does not contain create-bucket command"

forbid_in_file "$SKILL_MD" 'create-index' \
    "T31a [bounds]    SKILL.md does not contain create-index command"

forbid_in_file "$SKILL_MD" 'YOUR-' \
    "T31a [bounds]    SKILL.md does not contain YOUR-* placeholders"

forbid_in_file "$SKILL_MD" 'cp \.env\.example' \
    "T31a [bounds]    SKILL.md does not contain cp .env.example instruction"


# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "══ T31a: skills/setting-up-arkeology/references/agents-snippet.md ══════════"
echo ""
# ─── Existence ───────────────────────────────────────────────────────────────

require_file "$AGENTS_SNIPPET" \
    "T31a [existence] skills/setting-up-arkeology/references/agents-snippet.md exists"

# ─── Required content ─────────────────────────────────────────────────────────

require_in_file "$AGENTS_SNIPPET" '<!-- arkeology:config' \
    "T31a [snippet]   agents-snippet.md contains <!-- arkeology:config HTML comment"

require_in_file "$AGENTS_SNIPPET" 'local_only_types' \
    "T31a [snippet]   agents-snippet.md references local_only_types"

require_in_file "$AGENTS_SNIPPET" 'local_only_paths' \
    "T31a [snippet]   agents-snippet.md references local_only_paths"

require_in_file "$AGENTS_SNIPPET" 'Variant A' \
    "T31a [snippet]   agents-snippet.md contains Variant A (git-only ADR) section"

require_in_file "$AGENTS_SNIPPET" 'Variant B' \
    "T31a [snippet]   agents-snippet.md contains Variant B (arkeology-only ADR) section"


# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "══ T31b: skills/migrating-to-arkeology/SKILL.md ════════════════════════════"
echo ""
# ─── Forbidden: Step 2c ADR strategy gate must be removed ────────────────────

forbid_in_file "$MIGRATION_SKILL" '### 2c.*ADR strategy\|### 2c.*adr' \
    "T31b [step2c]    migration SKILL.md Step 2c ADR strategy gate heading is absent"

forbid_in_file "$MIGRATION_SKILL" '\*\*Variant A' \
    "T31b [step5]     migration SKILL.md Variant A block is removed from Step 5"

forbid_in_file "$MIGRATION_SKILL" '\*\*Variant B' \
    "T31b [step5]     migration SKILL.md Variant B block is removed from Step 5"

# ─── Required: pre-flight check and exclusion references ──────────────────────

require_in_file "$MIGRATION_SKILL" 'arkeology:config' \
    "T31b [step2]     migration SKILL.md contains arkeology:config pre-flight check"

require_in_file "$MIGRATION_SKILL" 'setting-up-arkeology' \
    "T31b [step2]     migration SKILL.md references setting-up-arkeology in hard-stop message"

require_in_file "$MIGRATION_SKILL" 'local_only_types' \
    "T31b [step2c]    migration SKILL.md references local_only_types (new Step 2c)"

require_in_file "$MIGRATION_SKILL" 'local_only_paths' \
    "T31b [step2b]    migration SKILL.md references local_only_paths (Step 2b exclusions)"

require_in_file "$MIGRATION_SKILL" 'adr_strategy' \
    "T31b [step5]     migration SKILL.md Step 5 ADR row references adr_strategy in config block"


# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "══ T31c: README.md ══════════════════════════════════════════════════════"
echo ""
# ─── Size ─────────────────────────────────────────────────────────────────────

check_line_count "$README" 310 360 \
    "T31c [size]      README.md is approximately 330 lines (310–360 range)"

# ─── Retained sections (must still be present after T31c) ────────────────────

require_in_file "$README" '^## Prerequisites' \
    "T31c [retained]  README retains ## Prerequisites section"

require_in_file "$README" '^## Minimum IAM Policy' \
    "T31c [retained]  README retains ## Minimum IAM Policy section"

require_in_file "$README" '^## Installation' \
    "T31c [retained]  README retains ## Installation section"

require_in_file "$README" '^## Configuration' \
    "T31c [retained]  README retains ## Configuration section"

require_in_file "$README" '^## Running the server' \
    "T31c [retained]  README retains ## Running the server section"

require_in_file "$README" '^## Development' \
    "T31c [retained]  README retains ## Development section"

require_in_file "$README" 'YOUR-' \
    "T31c [retained]  README Minimum IAM Policy section retains YOUR-* placeholder values"

# ─── Sections that must be absent (removed before or during T31c) ────────────

forbid_in_file "$README" '^## AWS Provisioning' \
    "T31c [removed]   README does not have ## AWS Provisioning section"

forbid_in_file "$README" 'cp \.env\.example' \
    "T31c [removed]   README does not contain cp .env.example"

forbid_in_file "$README" '^## Connecting to an MCP client' \
    "T31c [removed]   README does not have ## Connecting to an MCP client section"

forbid_in_file "$README" '^## Recommended AGENTS\.md Snippet' \
    "T31c [removed]   README does not have ## Recommended AGENTS.md Snippet section"

forbid_in_file "$README" '^### Declare your ADR strategy first' \
    "T31c [removed]   README does not have ### Declare your ADR strategy first heading"

# ─── Required new / updated content ──────────────────────────────────────────

require_in_file "$README" 'Flexible ADR & document strategy' \
    "T31c [updated]   README Key Features has 'Flexible ADR & document strategy' bullet"

require_in_file "$README" 'setting-up-arkeology' \
    "T31c [pointer]   README contains setting-up-arkeology pointer (replacing removed sections)"


# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "══ Summary ══════════════════════════════════════════════════════════════"
echo ""
TOTAL=$((FAILURES))  # captured at end; pass count derived below

if [ "$FAILURES" -eq 0 ]; then
    echo "  All checks PASSED. T31 implementation is complete."
    exit 0
else
    echo "  ${FAILURES} check(s) FAILED."
    echo ""
    echo "  NOTE: Checks that PASS before implementation verify already-stable"
    echo "  content (retained README sections, previously removed sections)."
    echo "  All checks for new/modified files should FAIL at the red phase."
    exit 1
fi
