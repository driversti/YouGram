# Context Memory — Design

**Date:** 2026-06-03
**Status:** Approved

## Purpose

The bot answers every question from scratch: each turn calls `agent.run(question)`
with no prior messages. A follow-up like "про що його останній пост?" has no
antecedent — the model never saw the previous turn where a channel was named, so
it asks the user to specify the chat again.

Goal: let the bot remember the conversation between turns, cheaply (without
ballooning token cost on every message).

## Two layers of memory

Both are in-memory, per-user, matching the existing `ConversationContext`. Nothing
new is persisted across bot restarts.

### 1. Active chat (primary, ~0 tokens)

- When a read tool (`fetch_messages` / `search_messages`) successfully resolves
  **exactly one** concrete chat, record it as the active chat in
  `ConversationContext`.
- A folder summary, a multi-chat search, or zero successful resolutions does
  **not** touch the active chat — it stays whatever it was (per the user's
  "don't set any" choice for multi-chat queries).
- The bot already injects a `[Current chat context: 'Name' (id=N)]` line for
  forwards. With this change that line is also present after an ordinary read, so
  "його останній пост" resolves against the last single channel the user looked
  at — at essentially no token cost.

### 2. Short history window (richer follow-ups)

- Keep the last **2 turns** of the conversation per user and pass them as
  `message_history` to `agent.run(...)`.
- **Token saving:** strip the heavy tool-result payloads from stored turns (the
  message dumps from `fetch_messages`/`search_messages` are what cost tokens).
  Keep the user questions and the assistant's text answers. The exact trimming
  mechanism (e.g. a Pydantic AI `history_processor` vs. filtering
  `result.new_messages()`) is settled during TDD; the requirement is: stored
  history must not carry stale tool dumps, and must remain a valid message
  sequence (no orphaned tool-call/tool-return parts).
- A "turn" = one user question plus the assistant's response. The window holds the
  two most recent turns; older turns are dropped.

## Components

- `context.py` — `ConversationContext` gains per-user conversation history:
  `append_turn(user_id, messages)`, `get_history(user_id) -> list`, capped at the
  last 2 turns. Existing `set_chat`/`get_chat`/`clear` are unchanged; `clear` also
  clears history for that user.
- `tools.py` — `Deps` gains `context` and `user_id`. `fetch_messages` and
  `search_messages` set the active chat in `context` when they resolve exactly one
  chat. (They already know the resolved chat; on a `ChatNotResolved` or multi-chat
  call they leave the context alone.)
- `agent.py` — `ask(agent, reader, question, *, context=None, user_id=None)`
  passes the stored history as `message_history` and returns both the text output
  and the (trimmed) new messages so the caller can store them. Signature stays
  backward-compatible for tests that call it without context.
- `bot.py` — `handle_question` reads history from `context`, passes it into
  `ask`, stores the trimmed result back, and injects the
  `[Current chat context: ...]` line whenever an active chat is set (forward or
  prior read).

## Data flow

1. User sends a question → bot loads `get_history(user_id)` and the active chat.
2. Bot calls `ask(..., context, user_id)` with that history as `message_history`.
3. During the run, a single-chat read tool sets the active chat in `context`.
4. `ask` returns output + trimmed new messages.
5. Bot `append_turn(user_id, trimmed_messages)` (window keeps last 2) and replies.
6. Next turn, the model sees the recent Q&A plus the active-chat line — "його …"
   resolves.

## Error handling

- No active chat and an ambiguous follow-up → unchanged behaviour: the agent asks
  the user to name a chat/folder (existing prompt rule).
- History trimming must never produce an invalid sequence; if trimming a turn
  would orphan a tool part, drop that whole turn rather than emit a partial one.
- A forward still overrides the active chat (explicit user intent).

## Testing (Telethon + model mocked)

- `ConversationContext`: history append, 2-turn cap, `clear` wipes history.
- `fetch_messages`/`search_messages` set active chat on a single resolved chat;
  do **not** set it for a folder/multi-chat call or on `ChatNotResolved`.
- `ask` passes `message_history` through and returns new messages; works with and
  without `context`/`user_id`.
- Trimming: stored history carries no tool-result payloads and is a valid message
  sequence.
- `bot.py`: a follow-up question after a single-chat read carries the active-chat
  line and the prior turn's history.

## Out of scope

- Persisting context/history across bot restarts (stays in-memory).
- LLM-based summarisation of older history.
- Changing the active chat from folder or multi-chat queries.
- A larger or configurable history window (fixed at 2 turns for now).
