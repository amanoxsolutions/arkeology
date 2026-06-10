import { fileURLToPath } from 'url';
import path from 'path';

// Resolve the skills/ directory relative to this plugin file so the path is
// correct regardless of where Bun caches the package on the engineer's machine.
// This file lives at .opencode/plugins/cairn.js, so ../../skills resolves to
// the repo root skills/ directory.
const __dirname = fileURLToPath(new URL('.', import.meta.url));
const skillsDir = path.resolve(__dirname, '../../skills');

/**
 * cairn-mcp — OpenCode plugin.
 *
 * Registers the cairn-mcp skills (installing-cairn, migrating-to-cairn) with
 * OpenCode by pushing the skills/ directory into config.skills.paths via the
 * config hook. Engineers install this plugin by adding one line to
 * ~/.config/opencode/opencode.jsonc:
 *
 *   "plugin": ["cairn-mcp@git+ssh://git@github.com/amanoxsolutions/cairn-mcp.git"]
 *
 * Or with HTTPS (no SSH key required):
 *
 *   "plugin": ["cairn-mcp@git+https://github.com/amanoxsolutions/cairn-mcp.git"]
 *
 * After adding the line, restart OpenCode to activate.
 */
export default function ({ project, client, $, directory, worktree }) {
  return {
    /**
     * config hook — fires at startup with the live OpenCode config object.
     * Mutations to cfg are reflected immediately when skills are lazily
     * discovered. Guard against duplicate registration on plugin re-load.
     */
    config: (cfg) => {
      try {
        cfg.skills = cfg.skills ?? {};
        cfg.skills.paths = cfg.skills.paths ?? [];

        if (!cfg.skills.paths.includes(skillsDir)) {
          cfg.skills.paths.push(skillsDir);
        }
      } catch (err) {
        // Errors in the config hook must not crash the OpenCode session.
        console.error('[cairn-mcp] config hook error:', err);
      }
    },
  };
}
