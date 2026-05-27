#!/bin/bash
# evo_codex — Codex CLI wrapper with automatic memory injection
# Usage: evo_codex [codex args...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVO_HOOK="$SCRIPT_DIR/evo_hook.py"
EVO_SESSION_ID="codex-$(date +%s)"

# Pre-hook: recall relevant skills
python3 "$EVO_HOOK" post codex "$EVO_SESSION_ID" "running" "Codex session started" 2>/dev/null || true

# Run Codex with all args
if command -v codex &>/dev/null; then
    codex "$@"
    EXIT_CODE=$?
else
    echo "[evo] codex not found, install with: npm install -g @openai/codex"
    exit 1
fi

# Post-hook: log result
if [ $EXIT_CODE -eq 0 ]; then
    python3 "$EVO_HOOK" post codex "$EVO_SESSION_ID" success "Codex completed successfully" 2>/dev/null || true
else
    python3 "$EVO_HOOK" post codex "$EVO_SESSION_ID" failure "Codex exited with code $EXIT_CODE" 2>/dev/null || true
fi

exit $EXIT_CODE
