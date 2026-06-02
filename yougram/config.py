from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config, loaded from env (prefix YOUGRAM_) or .env file.

    Provider API keys (e.g. ANTHROPIC_API_KEY) are read directly by Pydantic AI
    from the standard, unprefixed env vars — they are intentionally NOT here.
    """

    model_config = SettingsConfigDict(env_prefix="YOUGRAM_", env_file=".env", extra="ignore")

    api_id: int
    api_hash: str
    bot_token: str
    allowed_user_id: int

    llm_model: str = "anthropic:claude-haiku-4-5"
    session_name: str = "yougram"

    # IANA timezone (e.g. "Europe/Warsaw") used to resolve "today"/"this week".
    timezone: str = "UTC"
