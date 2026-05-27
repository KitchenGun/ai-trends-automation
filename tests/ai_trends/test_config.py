import pytest

from ai_trends.config import (
    ALLOWED_ENV_VAR_NAMES,
    ConfigError,
    load_ai_trends_collection_config,
    load_ai_trends_config,
)


def test_missing_required_env_names_fail_without_leaking_secret_values() -> None:
    leaked_spreadsheet_id = "spreadsheet-secret-value"
    leaked_webhook = "https://example.invalid/webhook-secret-value"
    environ = {
        "AI_TRENDS_SPREADSHEET_ID": leaked_spreadsheet_id,
        "AI_TRENDS_DISCORD_WEBHOOK_URL": leaked_webhook,
        "AI_TRENDS_X_BEARER_TOKEN": "x-token-secret-value",
        "AI_TRENDS_GITHUB_TOKEN": "github-token-secret-value",
    }

    with pytest.raises(ConfigError) as exc_info:
        load_ai_trends_config(environ)

    message = str(exc_info.value)
    assert "HERMES_TIMEZONE" in message
    assert leaked_spreadsheet_id not in message
    assert leaked_webhook not in message
    assert "x-token-secret-value" not in message
    assert "github-token-secret-value" not in message


def test_config_loads_only_approved_env_names_and_redacts_secrets() -> None:
    environ = {
        "AI_TRENDS_SPREADSHEET_ID": "spreadsheet-id-from-env",
        "AI_TRENDS_DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook-from-env",
        "AI_TRENDS_X_BEARER_TOKEN": "x-token-from-env",
        "AI_TRENDS_X_RSS_FEEDS_JSON": '["https://rss.example.invalid/alice.xml"]',
        "AI_TRENDS_X_RSS_FEEDS_FILE": "/var/lib/ai-trends/x-rss-feeds.json",
        "AI_TRENDS_GITHUB_TOKEN": "github-token-from-env",
        "HERMES_TIMEZONE": "Asia/Seoul",
        "UNRELATED_SECRET": "must-not-be-read",
    }

    config = load_ai_trends_config(environ)

    assert config.spreadsheet_id == "spreadsheet-id-from-env"
    assert config.discord_webhook_url == "https://discord.invalid/webhook-from-env"
    assert config.x_bearer_token == "x-token-from-env"
    assert config.x_rss_feeds_json == '["https://rss.example.invalid/alice.xml"]'
    assert config.x_rss_feeds_file == "/var/lib/ai-trends/x-rss-feeds.json"
    assert config.github_token == "github-token-from-env"
    assert config.timezone == "Asia/Seoul"
    assert set(ALLOWED_ENV_VAR_NAMES) == {
        "AI_TRENDS_SPREADSHEET_ID",
        "AI_TRENDS_DISCORD_WEBHOOK_URL",
        "AI_TRENDS_X_BEARER_TOKEN",
        "AI_TRENDS_X_RSS_FEEDS_JSON",
        "AI_TRENDS_X_RSS_FEEDS_FILE",
        "AI_TRENDS_GITHUB_TOKEN",
        "HERMES_TIMEZONE",
    }
    assert "must-not-be-read" not in repr(config)
    assert "webhook-from-env" not in repr(config)
    assert "x-token-from-env" not in repr(config)
    assert "rss.example.invalid" not in repr(config)
    assert "rss.example.invalid" not in repr(config)
    assert "github-token-from-env" not in repr(config)


def test_config_falls_back_to_github_cli_token_when_env_is_missing() -> None:
    config = load_ai_trends_config(
        {
            "AI_TRENDS_SPREADSHEET_ID": "spreadsheet-id-from-env",
            "AI_TRENDS_DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook-from-env",
            "HERMES_TIMEZONE": "Asia/Seoul",
        },
        github_token_resolver=lambda: "github-token-from-gh-cli",
    )

    assert config.github_token == "github-token-from-gh-cli"
    assert "github-token-from-gh-cli" not in repr(config)


def test_collection_config_does_not_require_discord_webhook() -> None:
    config = load_ai_trends_collection_config(
        {
            "AI_TRENDS_SPREADSHEET_ID": "spreadsheet-id-from-env",
            "AI_TRENDS_X_BEARER_TOKEN": "x-token-from-env",
            "AI_TRENDS_X_RSS_FEEDS_JSON": '["https://rss.example.invalid/alice.xml"]',
            "HERMES_TIMEZONE": "Asia/Seoul",
        },
        github_token_resolver=lambda: "github-token-from-gh-cli",
    )

    assert config.spreadsheet_id == "spreadsheet-id-from-env"
    assert config.timezone == "Asia/Seoul"
    assert config.x_bearer_token == "x-token-from-env"
    assert config.x_rss_feeds_json == '["https://rss.example.invalid/alice.xml"]'
    assert config.github_token == "github-token-from-gh-cli"
    assert "spreadsheet-id-from-env" not in repr(config)
    assert "x-token-from-env" not in repr(config)


def test_config_prefers_github_env_token_over_cli_fallback() -> None:
    config = load_ai_trends_config(
        {
            "AI_TRENDS_SPREADSHEET_ID": "spreadsheet-id-from-env",
            "AI_TRENDS_DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook-from-env",
            "AI_TRENDS_GITHUB_TOKEN": "github-token-from-env",
            "HERMES_TIMEZONE": "Asia/Seoul",
        },
        github_token_resolver=lambda: "github-token-from-gh-cli",
    )

    assert config.github_token == "github-token-from-env"


def test_blank_required_env_values_are_missing() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_ai_trends_config(
            {
                "AI_TRENDS_SPREADSHEET_ID": " ",
                "AI_TRENDS_DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook",
                "HERMES_TIMEZONE": "Asia/Seoul",
            }
        )

    assert "AI_TRENDS_SPREADSHEET_ID" in str(exc_info.value)


def test_invalid_timezone_fails_with_name_not_secret_values() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_ai_trends_config(
            {
                "AI_TRENDS_SPREADSHEET_ID": "spreadsheet-secret-value",
                "AI_TRENDS_DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook-secret-value",
                "HERMES_TIMEZONE": "Not/A_Timezone",
            }
        )

    message = str(exc_info.value)
    assert "HERMES_TIMEZONE" in message
    assert "spreadsheet-secret-value" not in message
    assert "webhook-secret-value" not in message
