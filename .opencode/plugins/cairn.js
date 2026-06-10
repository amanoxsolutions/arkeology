import { fileURLToPath } from 'url';
import { resolve, dirname } from 'path';

export default function (config) {
  try {
    const pluginDir = dirname(fileURLToPath(import.meta.url));
    const skillsPath = resolve(pluginDir, '../../skills');

    if (!config.skills) {
      config.skills = {};
    }
    if (!config.skills.paths) {
      config.skills.paths = [];
    }
    if (!config.skills.paths.includes(skillsPath)) {
      config.skills.paths.push(skillsPath);
    }
  } catch (err) {
    process.stderr.write(`cairn-mcp plugin error: ${err}\n`);
  }
  return config;
}
