"""Environment-only configuration for AI trends automation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
import subprocess
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SPREADSHEET_ID_ENV = "AI_TRENDS_SPREADSHEET_ID"
DISCORD_WEBHOOK_URL_ENV = "AI_TRENDS_DISCORD_WEBHOOK_URL"
X_BEARER_TOKEN_ENV = "AI_TRENDS_X_BEARER_TOKEN"
X_RSS_FEEDS_JSON_ENV = "AI_TRENDS_X_RSS_FEEDS_JSON"
X_RSS_FEEDS_FILE_ENV = "AI_TRENDS_X_RSS_FEEDS_FILE"
GITHUB_TOKEN_ENV = "AI_TRENDS_GITHUB_TOKEN"
TIMEZONE_ENV = "HERMES_TIMEZONE"

ALLOWED_ENV_VAR_NAMES: tuple[str, ...] = (
    SPREADSHEET_ID_ENV,
    DISCORD_WEBHOOK_URL_ENV,
    X_BEARER_TOKEN_ENV,
    X_RSS_FEEDS_JSON_ENV,
    X_RSS_FEEDS_FILE_ENV,
    GITHUB_TOKEN_ENV,
    TIMEZONE_ENV,
)
REQUIRED_ENV_VAR_NAMES: tuple[str, ...] = (
    SPREADSHEET_ID_ENV,
    DISCORD_WEBHOOK_URL_ENV,
    TIMEZONE_ENV,
)
COLLECTION_REQUIRED_ENV_VAR_NAMES: tuple[str, ...] = (
    SPREADSHEET_ID_ENV,
    TIMEZONE_ENV,
)


class ConfigError(ValueError):
    """Raised when required AI trends configuration is missing or invalid."""


@dataclass(frozen=True)
class AITrendsConfig:
    """Validated configuration loaded exclusively from approved environment names."""

    spreadsheet_id: str
    discord_webhook_url: str
    timezone: str
    x_bearer_token: str | None = None
    x_rss_feeds_json: str | None = None
    x_rss_feeds_file: str | None = None
    github_token: str | None = None

    def __repr__(self) -> str:
        return (
            "AITrendsConfig("
            f"spreadsheet_id={_redact(self.spreadsheet_id)}, "
            f"discord_webhook_url={_redact(self.discord_webhook_url)}, "
            f"timezone={self.timezone!r}, "
            f"x_bearer_token={_redact(self.x_bearer_token)}, "
            f"x_rss_feeds_json={_redact(self.x_rss_feeds_json)}, "
            f"x_rss_feeds_file={_redact(self.x_rss_feeds_file)}, "
            f"github_token={_redact(self.github_token)}"
            ")"
        )


@dataclass(frozen=True)
class AITrendsCollectionConfig:
    """Configuration for raw collection jobs that do not report to Discord."""

    spreadsheet_id: str
    timezone: str
    x_bearer_token: str | None = None
    x_rss_feeds_json: str | None = None
    x_rss_feeds_file: str | None = None
    github_token: str | None = None

    def __repr__(self) -> str:
        return (
            "AITrendsCollectionConfig("
            f"spreadsheet_id={_redact(self.spreadsheet_id)}, "
            f"timezone={self.timezone!r}, "
            f"x_bearer_token={_redact(self.x_bearer_token)}, "
            f"x_rss_feeds_json={_redact(self.x_rss_feeds_json)}, "
            f"x_rss_feeds_file={_redact(self.x_rss_feeds_file)}, "
            f"github_token={_redact(self.github_token)}"
            ")"
        )


def load_ai_trends_config(
    environ: Mapping[str, str] | None = None,
    *,
    github_token_resolver: Callable[[], str | None] | None = None,
) -> AITrendsConfig:
    """Load and validate AI trends settings from approved environment variables.

    Args:
        environ: Optional environment mapping for tests. When omitted, ``os.environ``
            is used. Only names in ``ALLOWED_ENV_VAR_NAMES`` are read.

    Returns:
        A validated ``AITrendsConfig`` instance.

    Raises:
        ConfigError: If required values are blank/missing or timezone is invalid.
    """

    source: Mapping[str, str] = os.environ if environ is None else environ
    values = {name: _clean_optional(source.get(name)) for name in ALLOWED_ENV_VAR_NAMES}
    if values[GITHUB_TOKEN_ENV] is None:
        resolver = github_token_resolver
        if resolver is None and environ is None:
            resolver = _resolve_github_cli_token
        if resolver is not None:
            values[GITHUB_TOKEN_ENV] = _clean_optional(resolver())
    missing_names = [name for name in REQUIRED_ENV_VAR_NAMES if values[name] is None]
    if missing_names:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing_names)}")

    timezone = values[TIMEZONE_ENV]
    if timezone is None:
        raise ConfigError(f"Missing required environment variables: {TIMEZONE_ENV}")
    _validate_timezone(timezone)

    spreadsheet_id = values[SPREADSHEET_ID_ENV]
    discord_webhook_url = values[DISCORD_WEBHOOK_URL_ENV]
    if spreadsheet_id is None or discord_webhook_url is None:
        raise ConfigError("Missing required AI trends environment variables")

    return AITrendsConfig(
        spreadsheet_id=spreadsheet_id,
        discord_webhook_url=discord_webhook_url,
        timezone=timezone,
        x_bearer_token=values[X_BEARER_TOKEN_ENV],
        x_rss_feeds_json=values[X_RSS_FEEDS_JSON_ENV],
        x_rss_feeds_file=values[X_RSS_FEEDS_FILE_ENV],
        github_token=values[GITHUB_TOKEN_ENV],
    )


def load_ai_trends_collection_config(
    environ: Mapping[str, str] | None = None,
    *,
    github_token_resolver: Callable[[], str | None] | None = None,
) -> AITrendsCollectionConfig:
    """Load collection-only settings without requiring a Discord webhook."""

    source: Mapping[str, str] = os.environ if environ is None else environ
    values = {name: _clean_optional(source.get(name)) for name in ALLOWED_ENV_VAR_NAMES}
    if values[GITHUB_TOKEN_ENV] is None:
        resolver = github_token_resolver
        if resolver is None and environ is None:
            resolver = _resolve_github_cli_token
        if resolver is not None:
            values[GITHUB_TOKEN_ENV] = _clean_optional(resolver())
    missing_names = [name for name in COLLECTION_REQUIRED_ENV_VAR_NAMES if values[name] is None]
    if missing_names:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing_names)}")

    timezone = values[TIMEZONE_ENV]
    if timezone is None:
        raise ConfigError(f"Missing required environment variables: {TIMEZONE_ENV}")
    _validate_timezone(timezone)

    spreadsheet_id = values[SPREADSHEET_ID_ENV]
    if spreadsheet_id is None:
        raise ConfigError("Missing required AI trends collection environment variables")

    return AITrendsCollectionConfig(
        spreadsheet_id=spreadsheet_id,
        timezone=timezone,
        x_bearer_token=values[X_BEARER_TOKEN_ENV],
        x_rss_feeds_json=values[X_RSS_FEEDS_JSON_ENV],
        x_rss_feeds_file=values[X_RSS_FEEDS_FILE_ENV],
        github_token=values[GITHUB_TOKEN_ENV],
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Invalid {TIMEZONE_ENV}: must be an IANA timezone name") from exc


def _resolve_github_cli_token() -> str | None:
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _redact(value: str | None) -> str:
    if value is None:
        return "None"
    return "'<redacted>'"
