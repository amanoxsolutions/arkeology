#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WIRED_OPENCODE=false
WIRED_CLAUDE=false
WIRED_COPILOT=false

# ── Check if any supported tools are present ────────────────────────────────
if ! command -v opencode &>/dev/null && \
   ! command -v claude &>/dev/null && \
   ! command -v copilot &>/dev/null; then
  echo "No supported AI tools detected on PATH (opencode, claude, copilot)."
  echo "Install at least one supported tool and re-run ./install.sh"
  exit 0
fi

# ── OpenCode ─────────────────────────────────────────────────────────────────
if command -v opencode &>/dev/null; then
  echo "✓ opencode detected"
  WIRED_OPENCODE=true
  echo
  echo "  Add one of the following lines to ~/.config/opencode/opencode.jsonc:"
  echo
  echo '    SSH (primary):'
  echo '    "plugin": ["cairn-mcp@git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git"]'
  echo
  echo '    HTTPS alternative (no SSH key required):'
  echo '    "plugin": ["cairn-mcp@git+https://github.com/amanoxsolutions/cairn-mcp.git"]'
  echo

  echo "  Clearing stale cairn-mcp OpenCode plugin cache (forces fresh fetch on next restart)..."
  rm -rf ~/.cache/opencode/packages/cairn-mcp@git+* 2>/dev/null || true
  echo "  Cache cleared."
  echo
else
  echo "  opencode not found on PATH — skipping OpenCode wiring"
fi

# ── Claude Code ───────────────────────────────────────────────────────────────
if command -v claude &>/dev/null; then
  echo "✓ claude detected"
  WIRED_CLAUDE=true

  echo "  Registering cairn-mcp marketplace (SSH)..."
  claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git || true

  echo "  Updating cairn-mcp marketplace cache..."
  claude plugin marketplace update cairn-mcp || true

  echo "  Installing cairn plugin..."
  claude plugin install cairn@cairn-mcp || true

  echo "  Merging pre-approval rule into ~/.claude/settings.json..."
  python3 - <<'PYEOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
rule = "Bash(git -C * pull)"

try:
    with open(settings_path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}

perms = data.setdefault("permissions", {})
allow = perms.setdefault("allow", [])
if rule not in allow:
    allow.append(rule)
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("  Pre-approval rule added.")
else:
    print("  Pre-approval rule already present — no change.")
PYEOF

else
  echo "  claude not found on PATH — skipping Claude Code wiring"
fi

# ── Copilot ───────────────────────────────────────────────────────────────────
if command -v copilot &>/dev/null; then
  echo "✓ copilot detected"

  if ! command -v gh &>/dev/null; then
    echo "  gh CLI required for gh skill install — https://cli.github.com"
    echo "  Skipping Copilot wiring."
  elif ! gh skill --help &>/dev/null; then
    echo "  gh skill subcommand not available — install or update gh CLI"
    echo "  Skipping Copilot wiring."
  else
    WIRED_COPILOT=true
    echo "  Installing skills via gh skill install..."
    for skill_dir in "$REPO_DIR/skills"/*/; do
      skill_name="$(basename "$skill_dir")"
      echo "    Installing skill: $skill_name"
      gh skill install "$REPO_DIR" "$skill_name" --from-local --agent github-copilot --scope user --force || {
        echo "  Error: gh skill install failed for skill '$skill_name'"
        echo "  See: https://cli.github.com/manual/gh_skill_install"
        exit 1
      }
    done
    echo "  All Copilot skills installed successfully."
  fi
else
  echo "  copilot not found on PATH — skipping Copilot wiring"
fi

# ── Session refresh ───────────────────────────────────────────────────────────
echo
echo "══════════════════════════════════════════════════════════════════════"
echo "  Session refresh"
echo "══════════════════════════════════════════════════════════════════════"
echo

if $WIRED_OPENCODE; then
  echo "  OpenCode: restart OpenCode to activate the cairn-mcp plugin"
  echo
fi

if $WIRED_CLAUDE; then
  echo "  Claude Code: run /reload-plugins or start a new session"
  echo
fi

if $WIRED_COPILOT; then
  echo "  Copilot: reload the VS Code window to pick up the installed skills"
  echo
fi

echo "  ── OpenCode plugin lines (add one to ~/.config/opencode/opencode.jsonc) ──"
echo
echo '  SSH (primary):'
echo '  "plugin": ["cairn-mcp@git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git"]'
echo
echo '  HTTPS alternative (no SSH key required):'
echo '  "plugin": ["cairn-mcp@git+https://github.com/amanoxsolutions/cairn-mcp.git"]'
echo
echo "  ── Claude Code commands ──────────────────────────────────────────────────"
echo
echo "  SSH (primary):"
echo "  claude plugin marketplace add git@github.com:amanoxsolutions/cairn-mcp.git"
echo "  claude plugin install cairn@cairn-mcp"
echo
echo "  HTTPS alternative (if SSH / port 22 is blocked):"
echo "  claude plugin marketplace add https://github.com/amanoxsolutions/cairn-mcp.git"
echo "  claude plugin install cairn@cairn-mcp"
echo
