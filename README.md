# YouGram

Ask an LLM about your own Telegram. YouGram connects Claude to your personal
Telegram account so you can ask natural-language questions about content you
already have access to:

- "What was posted on channel X today?"
- "Did anyone mention Y across these channels this week?"
- "Re-read my chat with someone so I can ask about the details."

## How it works

A normal Telegram bot can't read channel history or your private chats. YouGram
uses **two strictly separated** Telegram entities:

1. **Reader** — an MTProto user-client ([Telethon](https://docs.telethon.dev))
   logged into your account. It only *reads*; it never sends.
2. **Bot** — a regular Bot API bot that is your chat interface. You DM it
   questions, it replies. It has no access to your account.

```
You → Bot → Agent (Claude + tools) → Telethon reads account → Claude answers → Bot → You
```

When you ask something, the agent fetches the relevant messages live (on-demand)
and answers. Nothing is archived to disk.

## Quick start

1. `cp .env.example .env` and fill in the values (see comments in the file).
2. Create the user session once (interactive, asks for an SMS code):
   ```bash
   uv sync
   uv run python scripts/login.py
   ```
   It prints your numeric user id — put it in `YOUGRAM_ALLOWED_USER_ID`.
3. Run it: `uv run python -m yougram` (or `docker compose up -d`).
4. DM your bot a question, e.g. "what was posted on @somechannel today?"

## Status

🚧 Early development. See the design spec in
[`docs/superpowers/specs/`](docs/superpowers/specs/) for the full architecture.

## ⚠️ Disclaimer

YouGram logs into your personal Telegram account via MTProto (a "userbot").
This is a grey area in Telegram's Terms of Service. Use at your own risk on an
account you're comfortable with. Your `.session` file is the full key to your
account — keep it secret, keep it out of git (it's gitignored).

## License

[MIT](LICENSE)
