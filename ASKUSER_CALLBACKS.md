# AskUserQuestion Callbacks (Claude Code Chat)

## Overview

This document describes how Claude Code can ask clarifying questions during a chat
session and receive user responses over WebSocket. The flow relies on the Agent SDK
`can_use_tool` callback and a WebSocket bridge in `AgentSessionManager`.

Key integration points:
- `app/services/agent_chat.py`: adds `AskUserQuestion` to `allowed_tools`, wires
  `can_use_tool`, and installs a no-op `PreToolUse` hook for SDK streaming.
- `app/services/agent_session_manager.py`: maintains pending question state,
  sends WebSocket events, waits for responses, and resolves SDK permission results.
- `app/api/chat.py`: handles `ask_user_response` messages and extends
  `session_status` payloads.

## WebSocket Protocol

### Server → Client

`ask_user_question`
```json
{
  "type": "ask_user_question",
  "question_id": "q_123",
  "questions": [
    {
      "question": "How should I format the output?",
      "header": "Format",
      "options": [
        {"label": "Summary", "description": "Brief overview"},
        {"label": "Detailed", "description": "Full explanation"}
      ],
      "multiSelect": false
    }
  ],
  "timeout_seconds": 55
}
```

`ask_user_timeout`
```json
{
  "type": "ask_user_timeout",
  "question_id": "q_123",
  "error": "User response timed out"
}
```

`session_status` (additional fields)
```json
{
  "type": "session_status",
  "session_id": "session-123",
  "is_processing": false,
  "waiting_for_user": true,
  "pending_question_id": "q_123"
}
```

### Client → Server

`ask_user_response`
```json
{
  "type": "ask_user_response",
  "data": {
    "question_id": "q_123",
    "answers": {
      "How should I format the output?": "Summary"
    },
    "cancelled": false
  }
}
```

Notes:
- `answers` values are strings. For multi-select, join selections with `", "`.
- Free-text answers are allowed even if not in options.
- Late responses after timeout are ignored.
- Responses from non-active connections are rejected with `session_taken`.

## Backend Flow

1. SDK calls `can_use_tool` with `AskUserQuestion`.
2. `AgentSessionManager` creates a `question_id`, stores pending state, and sends
   `ask_user_question` over WebSocket (or buffers if disconnected).
3. `AgentSessionManager` awaits the response with a 55s timeout.
4. On response:
   - Normalize answers (multi-select joined with `", "`).
   - Return `PermissionResultAllow(updated_input={questions, answers})`.
5. On timeout or cancel:
   - Emit `ask_user_timeout`.
   - Return `PermissionResultDeny(message="User response timeout", interrupt=True)`.

## Frontend Guidance

- Render `ask_user_question` as a modal or inline prompt.
- Support:
  - Optional header tag
  - Single-select or multi-select options
  - Free-text input
- Disable normal chat input while `waiting_for_user` is true (queued on backend).
- Submit `ask_user_response` with `cancelled: true` when the user cancels.

## Reconnect Behavior

- If the client is disconnected when the question is asked, the event is buffered.
- On reconnect, the pending question is replayed so the user can respond.
