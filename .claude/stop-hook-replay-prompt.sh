#!/bin/bash
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MESSAGES=""

DELETED=$(find "$PROJECT_ROOT" -name "nul" -not -path "*/node_modules/*" -not -path "*/.git/*" -type f -delete -print 2>/dev/null)
if [ -n "$DELETED" ]; then
  COUNT=$(echo "$DELETED" | wc -l | tr -d ' ')
  FILES=$(echo "$DELETED" | tr '\n' ', ' | sed 's/,$//')
  MESSAGES="[nul cleanup] ${COUNT} nul file(s) deleted: ${FILES}"
fi

PROMPT_FILE="/tmp/claude-prompt-$SESSION_ID.txt"
if [ -f "$PROMPT_FILE" ]; then
  PROMPT=$(cat "$PROMPT_FILE")
  if [ -n "$PROMPT" ]; then
    PROMPT_MSG="--- Original Prompt ---\n$PROMPT"
    if [ -n "$MESSAGES" ]; then
      MESSAGES="${MESSAGES}\n${PROMPT_MSG}"
    else
      MESSAGES="$PROMPT_MSG"
    fi
  fi
fi

if [ -n "$MESSAGES" ]; then
  jq -nc --arg msg "$MESSAGES" '{systemMessage: $msg}'
fi

exit 0
