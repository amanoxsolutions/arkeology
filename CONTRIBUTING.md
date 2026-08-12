# Contributing to Arkeology

Thank you for contributing! This guide covers how to get the development environment
running, how to wire Arkeology into your AI tools, and the conventions the project
follows.

## Development setup

```bash
git clone https://github.com/amanoxsolutions/arkeology.git
cd arkeology
uv sync
```

Install the pre-commit hooks (ruff, mypy, and SKILL.md description validation):

```bash
uv run pre-commit install
```

Run the full quality gate before pushing:

```bash
uv run pytest tests/unit/ -q -m 'not integration'
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
python3 scripts/validate.py
```

## Integration tests

`tests/integration/` requires a project-root `.env` with real AWS credentials and
resource names (`AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, and
optionally `AWS_PROFILE`). Tests are skipped automatically when these are absent.

The suite ignores whatever `WRITE_PREFIX` / `READ_PREFIXES` your `.env` configures — it
writes only under an ephemeral `integration-tests/<run-id>` prefix generated fresh for
each run, and a second `integration-tests/<run-id>-foreign` prefix stands in for any
cross-scope reads. Both prefixes are deleted (S3 objects and vectors) in a best-effort
session-end teardown. This means the suite is **safe to run against any store**,
including one already holding real team memory — it never touches operator-configured
data. It does incur real AWS and Bedrock usage, so it is not free to run.

Run it with:

```bash
uv run pytest tests/integration/ -q
```

## Wiring skills into your AI tools

### Automatic — `install.sh`

Run the install script from the repo root. It detects which AI tools are installed and
applies the correct wiring for each:

```bash
./install.sh
```

Supported tools: OpenCode, Claude Code, and GitHub Copilot (via `gh skill install`).

### Manual — OpenCode

Add one line to `~/.config/opencode/opencode.jsonc`:

```json
"plugin": ["arkeology@git+ssh://git@github.com/amanoxsolutions/arkeology.git"]
```

HTTPS alternative (no SSH key required):

```json
"plugin": ["arkeology@git+https://github.com/amanoxsolutions/arkeology.git"]
```

Restart OpenCode to activate the plugin. All four Arkeology skills (`setting-up-arkeology`,
`migrating-to-arkeology`, `sync-arkeology-plugin`, and `backfilling-references`) will be available
in every subsequent session.

### Manual — Claude Code

Two commands register the marketplace and install the plugin:

```bash
claude plugin marketplace add git@github.com:amanoxsolutions/arkeology.git
claude plugin install arkeology@arkeology
```

HTTPS alternative (for environments where outbound SSH / port 22 is blocked):

```bash
claude plugin marketplace add https://github.com/amanoxsolutions/arkeology.git
claude plugin install arkeology@arkeology
```

This installs all four skills as `arkeology:setting-up-arkeology`, `arkeology:migrating-to-arkeology`,
`arkeology:sync-arkeology-plugin`, and `arkeology:backfilling-references` slash commands. To update
the plugin clone later, run `/arkeology:sync-arkeology-plugin`.

## Adding a new tool

All tool implementations live in `src/arkeology/tools/<name>.py`. Register the new tool
on `_app` in `server.py` via `register_tools()`. Follow the existing tool pattern:
a public function that wraps an `_inner` variant in `try/except Exception`.

## Adding a new skill

Skills live in `plugins/arkeology/skills/<skill-name>/SKILL.md`. Each skill must have a YAML frontmatter
block with `name` and `description` fields. If the `description` value contains `: `
(colon-space), it must be wrapped in double quotes — the Go YAML parser used by
`gh skill install` rejects unquoted colon-space values.

The pre-commit hook (`scripts/validate.py`) enforces this automatically.

## SKILL.md description quoting rule

This is caught at commit time by `scripts/validate.py`:

```yaml
# Wrong — will fail gh skill install
description: Installing arkeology: the MCP server

# Correct — double-quoted
description: "Installing arkeology: the MCP server"
```

## License

Apache License 2.0. By contributing you agree that your contributions will be licensed
under the same terms.
