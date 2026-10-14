# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Claude Code wiring

- Project status: pre-code. No `Makefile`, Terraform or pipeline code exists yet; the commands in
  `AGENTS.md` are the target contract, not something to run today.
- Host is Windows 11. The Bash tool is Git Bash; paths with `!` must be quoted
  (`"/d/Projects/!Python/..."`).
- Skills load from `.claude/skills` -> `../.agents/skills` (native symlink). Edit the files under
  `.agents/skills/`. A skill's `description` is routing text: rewording it can stop it loading.

## Second opinions

Three read-only subagents in `.claude/agents/`. Use one only when the user names that route or asks
for a second opinion from it; the output is advisory and is relayed, not acted on unreviewed.

| Agent | CLI | Pinned model | Barrier |
|---|---|---|---|
| `codex-thinking` | `codex` 0.160.0 | `gpt-6.1-sol`, effort `max` | `-s read-only`, `--ignore-user-config` |
| `cursor-thinking` | `cursor-agent` 2026.10.01 | `gpt-5.6-sol-max` | `--mode plan --trust` |
| `gemini-thinking` | `agy` 1.3.0 | `gemini-3.8-flash-high` | `~/.gemini/antigravity-cli/settings.json` permissions allow only `read_file(*)` |

All three were probed on 2026-10-13 and returned `PROBE_OK`. Do not change a pin without a new
probe plus a negative control, recorded in the agent file.

Usage ledger: `.claude/settings.local.json` (machine-specific, gitignored) sets `SECOND_OPINION_MONITOR_DIR`; read it with
`python3 .claude/monitoring/second_opinion_usage.py report`.
