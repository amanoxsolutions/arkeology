---
name: sync-cairn-plugin
description: Pull the latest cairn-mcp skill content for your AI coding tool — auto-detects OpenCode, Claude Code, or Copilot and applies the correct update action.
---

# sync-cairn-plugin — Update cairn-mcp Skills

This skill pulls the latest cairn-mcp skill content into your AI coding tool. It detects
the running tool automatically and applies the correct update action for each.

---

## OpenCode

Clear the Bun package cache so OpenCode fetches the latest version on next start:

```bash
rm -rf ~/.cache/opencode/packages/cairn-mcp@git+*
```

Then **restart OpenCode**. The glob `cairn-mcp@git+*` covers both SSH and HTTPS installs.

---

## Claude Code

Pull the latest changes into the plugin clone, then reload plugins in the same session:

```bash
git -C ~/.claude/plugins/marketplaces/cairn-mcp pull
```

```
/reload-plugins
```

The updated skill content is active immediately after `/reload-plugins` completes.

---

## Copilot (VS Code)

Re-run `install.sh` from the cairn-mcp repository directory to force-reinstall all skills:

```bash
./install.sh
```

Then **reload VS Code** (`Developer: Reload Window` or close and reopen) to pick up the
updated skill content.

---

## Unknown / undetected tool

If the agent cannot determine which tool is running, present all three paths above to the
engineer and ask: *"Which AI coding tool are you using — OpenCode, Claude Code, or Copilot
(VS Code)?"* Then apply the matching block above.

---

## Notes

**This skill updates the plugin / skills only** — it does **not** update the cairn-mcp
server itself.

To update the server, perform these steps separately in the cairn-mcp repository:

```bash
git pull
uv sync
```

Then restart the cairn-mcp server process.
