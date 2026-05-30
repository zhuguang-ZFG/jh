#!/bin/bash
# AI Commit Message Generator
# Uses VPS AI Router to generate commit messages from staged diff

COMMIT_MSG_FILE=$1
COMMIT_SOURCE=$2

if [ "$COMMIT_SOURCE" != "" ]; then
    exit 0
fi

DIFF_CONTENT=$(git diff --cached --unified=2 | head -c 2000)

if [ -z "$DIFF_CONTENT" ]; then
    exit 0
fi

# Use python with explicit UTF-8 encoding
RESPONSE=$(python3 -c "
import json, urllib.request, sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'

diff = sys.stdin.buffer.read().decode('utf-8', errors='replace')
prompt = 'Generate a concise git commit message for this diff. Rules: start with feat/fix/refactor/docs/chore/test, keep under 80 chars, use English. Only output the commit message.\n\nDiff:\n' + diff

body = json.dumps({
    'model': 'glm-flash',
    'messages': [{'role': 'user', 'content': prompt}],
    'max_tokens': 128
}, ensure_ascii=False).encode()

req = urllib.request.Request('http://119.45.204.198:8769/v1/chat/completions', data=body, method='POST')
req.add_header('Content-Type', 'application/json')
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        d = json.loads(resp.read())
        msg = d['choices'][0]['message']['content'].strip()
        sys.stdout.buffer.write(msg.encode('utf-8'))
except Exception as e:
    sys.exit(1)
" <<< "$DIFF_CONTENT" 2>/dev/null)

if [ -n "$RESPONSE" ]; then
    echo "$RESPONSE" > "$COMMIT_MSG_FILE"
    echo "[AI] $RESPONSE"
fi
