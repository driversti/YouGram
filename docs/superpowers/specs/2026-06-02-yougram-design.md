# YouGram — Design

**Date:** 2026-06-02
**Status:** Approved

## Purpose

Connect an LLM (Claude) to the user's personal Telegram account so the user can
ask natural-language questions about content they have access to:

- "What was posted on channel X today?"
- "Did anyone mention Y across these channels?"
- "Re-read my chat with my girlfriend so I can ask about details."

A standard Telegram Bot cannot read channel/group history or private chats. The
only way to satisfy these queries is a **user-client (MTProto)** logged into the
user's real account.

## Core decisions

- **Read mechanism:** MTProto user-client via **Telethon** (logs into the user's
  real account as another device). Accepted ToS grey-area risk for personal use.
- **Interaction surface:** a **separate Telegram Bot** (Bot API). The user DMs
  the bot questions; the bot replies.
- **Strategy:** **on-demand** — when asked, the agent fetches fresh messages live
  via Telethon, reads them, answers. No archival/RAG at this stage (YAGNI; add
  later only if context limits become a real problem).
- **Language/stack:** Python (Telethon + Pydantic AI).
- **LLM:** provider-agnostic via **Pydantic AI** — any provider/model that
  supports tool calling (Anthropic, OpenAI, Gemini, local). Default model:
  **Claude Haiku**, switchable via config.
- **Deploy:** dedicated LXC + Docker image via `registry.yurii.live` (same
  pattern as NutritionBot).
- **Access:** the bot replies only to the user's own `user_id` (whitelist).

## Two Telegram entities (kept strictly separate)

1. **Reader** — Telethon user-client, authenticated as the user's account. Only
   *reads* channels/groups/chats. Never sends.
2. **Bot** — Bot API bot, the user's interface. Receives questions, returns
   answers. Has no access to the user account.

The bot never touches the account session; the account never posts anything.

## Data flow

```
User → Bot → Agent (Claude + tools) → Telethon reads account → Claude answers → Bot → User
```

## Agent tools (the model calls as needed)

- `list_dialogs(query)` — resolve a channel/group/chat by name/handle.
- `fetch_messages(chat, since, limit)` — pull messages for a period/limit.
- `search_messages(query, chats, since)` — text search across one or more chats.

Example mapping:

- "what was posted on channel X today?" → `fetch_messages(X, since=today)`
- "did anyone write about Y in these channels?" → `search_messages("Y", [chats], since)`
- "re-read my chat with my girlfriend" → `fetch_messages(chat, limit=N)` then Q&A

## Components (modules)

- `telegram_reader.py` — Telethon client + session lifecycle.
- `tools.py` — the three tools above, clean interfaces, no Claude coupling.
- `agent.py` — Pydantic AI agent: model config (provider-agnostic), tool
  registration, query loop.
- `bot.py` — Bot API handler, whitelist, route question → agent → reply.
- `config.py` — secrets/config (`API_ID`/`API_HASH`, bot token, LLM provider +
  model + provider API key).

Each module has one purpose and a defined interface so tools can be unit-tested
without a live account.

## Security & privacy

- Bot replies only to the user's `user_id`.
- Telethon session file (`.session`) = full key to the account. Lives only in an
  LXC volume; never committed, never baked into the image.
- On-demand only: private message content is held in memory for the duration of
  a request, not persisted to disk.
- No secrets in git or the Docker image; injected via environment/volume.

## Testing

- Telethon is mocked — no real account in the test suite.
- `tools.py` unit-tested against fake message fixtures.
- `agent.py` tested against mocked tools (verifies tool selection/routing).

## One-time setup

1. Obtain `API_ID` / `API_HASH` from my.telegram.org.
2. First interactive login with the SMS code → generates the `.session` file.
3. Create the interface bot via BotFather → bot token.
4. Configure the LLM provider, model (default Claude Haiku), and its API key.

## Out of scope (for now)

- Archival / vector search (RAG).
- The account ever sending messages.
- Multi-user access.
