# Post Links + Robust Resolution — Design

**Date:** 2026-06-02
**Status:** Approved

## Purpose

Two linked problems surfaced in live use:

1. **Resolution crash.** Asking "in which chat was X discussed? show me the post"
   produced `Error: Nobody is using this username (ResolveUsernameRequest)`. The
   agent passed a human name/guess straight to a read tool; Telethon tried to
   resolve it as a `@username` and failed.
2. **No link.** There is no way to get a clickable link to a found post.

Goal: make the bot reliably find the post and return a clickable `t.me` link.

## 1. Robust chat resolution (fixes the crash)

- `fetch_messages` / `search_messages` catch Telethon resolution errors
  (`UsernameNotOccupiedError`, `ValueError`, and similar) for a chat and return a
  clear, structured "could not resolve chat X" signal instead of crashing with a
  raw Telethon error.
- System prompt: never pass a human name directly to a read tool — first resolve
  it with `list_dialogs` / `chats_in_folder`, then pass the returned
  `id`/`@username`.
- For a "which chat discussed X" question with **no** scope (no forward context,
  no named chat/folder), the agent must **ask the user to name a folder or chat**
  rather than guessing. (Search scope decision: scoped, with an explicit ask when
  unknown.)

## 2. Search scope

- Forward context set → search there.
- User named a chat/folder → resolve and search those.
- Neither → ask the user to name a folder or chat. No mass-search across all
  dialogs.

## 3. Post links (new)

- Add `link: str | None` to the `Message` model.
- The reader resolves the target chat once per fetch/search and builds a `t.me`
  permalink for each message:
  - public channel (`@username`): `https://t.me/<username>/<message_id>`
  - private channel (no username): `https://t.me/c/<internal_id>/<message_id>`
    (the raw positive channel id, no `-100` prefix)
  - if neither a username nor a channel id is available, `link` is `None`.
- The agent shows the matched post's text plus its clickable link.

## Components

- `models.py` — `Message` gains `link: str | None = None`.
- `telegram_reader.py`:
  - a `_message_link(entity, message_id)` helper building the permalink from a
    resolved chat entity.
  - `fetch_messages` / `search_messages` resolve the chat entity once, pass it to
    `_to_message` so each `Message.link` is populated; wrap resolution in
    try/except and raise a typed `ChatNotResolved` (or return an empty result with
    a flagged reason) the tool layer turns into a friendly message.
- `tools.py` — the read tools translate a resolution failure into a clear return
  value/string the agent can relay (e.g. "could not find chat 'X'").
- `agent.py` — prompt updates for resolve-first and ask-when-no-scope.

## Error handling

- Unresolvable chat → tool returns "could not find chat 'X' — name a folder or
  channel"; the agent relays it and asks the user to specify.
- Private channel without access → reported per chat; other chats continue.

## Testing (Telethon mocked)

- `_message_link`: public (username) vs private (`c/<id>`) vs neither (`None`).
- `Message.link` populated in `fetch_messages` / `search_messages` results.
- Resolution error path: a chat that raises on resolve yields the friendly
  "could not find chat" outcome, not a crash.

## Out of scope

- Mass-searching every dialog.
- Deep-linking to private chats the account cannot access.
- Persisting anything new (still on-demand/in-memory).
