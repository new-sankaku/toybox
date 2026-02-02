#!/bin/bash
INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')

if [ -n "$PROMPT" ] && [ -n "$SESSION_ID" ]; then
  echo "$PROMPT" > "/tmp/claude-prompt-$SESSION_ID.txt"
fi

exit 0
