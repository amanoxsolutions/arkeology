---
name: plugin-sync
description: Update the cairn-mcp Claude Code plugin clone and reload skills
---

# cairn:plugin-sync — Update the Plugin Clone

This skill updates the cairn-mcp Claude Code plugin clone. Run it after a new release
has been pushed to pick up updated skills without reinstalling.

---

## Steps

1. Pull the latest changes into the plugin clone:

   ```bash
   git -C ~/.claude/plugins/cairn-mcp pull
   ```

2. Reload plugins so Claude Code picks up the updated skill content:

   ```
   /reload-plugins
   ```

---

## Notes

**This skill only updates the Claude Code plugin clone** (`~/.claude/plugins/cairn-mcp`).
It does **not** update the cairn-mcp server itself.

To update the server, perform these steps separately:

1. Pull the latest changes into your server clone:

   ```bash
   git -C /path/to/cairn-mcp pull
   ```

2. Re-sync dependencies:

   ```bash
   uv sync
   ```

3. Restart the cairn-mcp server process.

Perform both the plugin-sync and the server update after a new release to ensure the
skills and server are in sync.
