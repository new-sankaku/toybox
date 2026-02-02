#!/bin/bash
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')

PROMPT_FILE="/tmp/claude-prompt-$SESSION_ID.txt"
if [ -f "$PROMPT_FILE" ]; then
  PROMPT=$(cat "$PROMPT_FILE")
  if [ -n "$PROMPT" ]; then
    jq -nc --arg prompt "$PROMPT" '{systemMessage: ("--- Original Prompt ---\n" + $prompt)}'
  fi
fi

exit 0
