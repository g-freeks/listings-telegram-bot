#!/usr/bin/env bash
# Manual spike helper for Phase 1 — runs the exact runner contract from CLAUDE.md
# so we can reproduce an evaluation from the CLI by hand before the bot exists.
#
# Usage:
#   scripts/run_claude.sh "MESSAGE" [SESSION_ID]
#
# Env:
#   CONFIG_PATH   path to config.json (default: ./config.json — your real,
#                 gitignored config; see config/config.json for the
#                 anonymized example this repo tracks instead)
set -euo pipefail

MESSAGE="${1:?usage: run_claude.sh MESSAGE [SESSION_ID]}"
SESSION_ID="${2:-}"
CONFIG_PATH="${CONFIG_PATH:-config.json}"

RENDERED_CONFIG="$(python3 "$(dirname "$0")/../app/render_config.py" "$CONFIG_PATH")"

RESUME_ARGS=()
if [[ -n "$SESSION_ID" ]]; then
  RESUME_ARGS=(--resume "$SESSION_ID")
fi

claude -p "$MESSAGE" --output-format json "${RESUME_ARGS[@]}" \
  --append-system-prompt "$RENDERED_CONFIG" \
  --allowedTools "WebFetch WebSearch Read" --max-turns 40
