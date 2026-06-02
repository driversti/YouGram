from yougram.config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("YOUGRAM_API_ID", "12345")
    monkeypatch.setenv("YOUGRAM_API_HASH", "abc")
    monkeypatch.setenv("YOUGRAM_BOT_TOKEN", "123:token")
    monkeypatch.setenv("YOUGRAM_ALLOWED_USER_ID", "777")

    s = Settings(_env_file=None)

    assert s.api_id == 12345
    assert s.api_hash == "abc"
    assert s.bot_token == "123:token"
    assert s.allowed_user_id == 777
    assert s.llm_model == "anthropic:claude-haiku-4-5"  # default
    assert s.session_name == "yougram"  # default
