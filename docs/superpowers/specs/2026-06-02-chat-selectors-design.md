# Chat Selectors (folders + fuzzy search + forward) — Design

**Date:** 2026-06-02
**Status:** Approved

## Purpose

The user often doesn't know the exact @usernames of channels/chats. Add three
ways to *select which chats to read* without knowing exact names:

1. **Folders** — "summarize today's posts from the channels in folder AI".
2. **Fuzzy name** — "that channel about crypto" (typo-tolerant, ranked).
3. **Forward** — forward a message from a channel to point the bot at it, then
   ask follow-up questions about it.

Reading by date/`since` already exists; this work is purely about *selecting the
target chats*.

## Core idea

The agent gains new "chat selector" tools, and forwarding adds a small in-memory
context memory. All three feed the existing `fetch_messages`/`search_messages`.

## Reader capabilities (`telegram_reader.py`)

- `list_folders() -> list[Folder]` — read the user's chat folders (Telethon
  dialog filters via `messages.GetDialogFiltersRequest`). Returns folder titles.
- `chats_in_folder(name) -> list[Dialog]` — fuzzy-match a folder by name, resolve
  its `include_peers` to `Dialog` value objects.
- `list_dialogs(query)` — improved with fuzzy ranking (typo tolerance) using
  `difflib` (stdlib): substring match boosted, then ranked by similarity ratio.

Notes:
- Telethon's `DialogFilter.title` may be a `TextWithEntities` in recent layers;
  the reader normalizes it to a plain string.
- Default/preset filters (`DialogFilterDefault`) without a real title are skipped.

## Domain models (`models.py`)

- Add `Folder(id: int, title: str)`.
- Reuse existing `Dialog` for chats within a folder.

## Agent tools (`tools.py`)

- `list_folders(ctx)` and `chats_in_folder(ctx, name)` — delegate to the reader.
- Existing `list_dialogs`, `fetch_messages`, `search_messages` unchanged.

## Forward handling + context memory

- `forwards.py` → `extract_forward_source(message) -> ForwardSource | None`.
  - Reads Telethon `message.fwd_from`. For a visible channel origin, returns a
    `ForwardSource` with `username`/`chat_id` and `title`.
  - If the origin is hidden by privacy (`from_id` is None, only `from_name`),
    returns a `ForwardSource` with only `title` and `resolvable=False`.
  - Returns `None` if the message is not a forward.
- `context.py` → `ConversationContext`: in-memory per-`user_id` "current chat"
  store (`set_chat`, `get_chat`, `clear`). No persistence (resets on restart).
- `bot.py`:
  - On a forwarded message: extract the source. If resolvable, store it as the
    current chat and reply "Контекст: канал X. Питай 🙂". If hidden, tell the
    user the origin is private and suggest searching by name.
  - On a normal text message: if a current chat is stored, prepend a structured
    context line to the question passed to the agent, e.g.
    `[Current chat context: chat 'X' (@x). Apply the question to this chat unless another is named.]`
    The agent then calls `fetch_messages`/`search_messages` on that chat.

## Agent prompt (`agent.py`)

- Register the two new tools.
- Extend the system prompt: explain folders (`list_folders` →
  `chats_in_folder` → read each), fuzzy `list_dialogs`, and that a "current chat
  context" line may be supplied by the bot.

## Data flow examples

- "summarize today's posts from folder AI" → `chats_in_folder("AI")` →
  `fetch_messages(each, since=today)` → summary.
- forward a channel → context = X; "what's there over 3 days?" →
  `fetch_messages(X, since=now-3d)`.
- "that channel about crypto" → `list_dialogs("crypto")` (fuzzy) → read top match.

## Error handling

- Folder not found → say so, offer `list_folders` output.
- Forward origin hidden → explain privacy limit, suggest fuzzy name search.
- No access to a private channel → report the failure for that chat and continue
  with the others.

## Testing

Telethon is mocked (no live account):
- Fake dialog filters → `list_folders`, `chats_in_folder` resolution.
- `list_dialogs` fuzzy ranking (typo + ordering).
- Fake `fwd_from` → `extract_forward_source` (visible vs hidden origin vs
  non-forward).
- `ConversationContext` set/get/clear.
- Bot routing: forward stores context; normal message injects context into the
  agent question.

## Out of scope

- Persisting context across restarts (in-memory only).
- The account ever sending/forwarding messages.
- Folder editing.
