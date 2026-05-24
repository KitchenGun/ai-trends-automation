"""AI trends automation package."""

from ai_trends.config import AITrendsCollectionConfig, AITrendsConfig, ConfigError, load_ai_trends_collection_config, load_ai_trends_config
from ai_trends.dedupe import canonicalize_url, dedupe_trend_items, normalize_title
from ai_trends.discord import (
    DiscordSendResult,
    render_daily_digest_message,
    render_weekly_digest_message,
    send_discord_webhook,
)
from ai_trends.hermes_eval import HermesEvaluationError, evaluate_trend_item, evaluate_trend_items
from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem, WeeklyDigest
from ai_trends.sheets import append_collected_raw_items, append_daily_digest, append_raw_items, append_weekly_digest, read_sheet_rows, update_discord_status
from ai_trends.sources import DEFAULT_TREND_SOURCES, SourceSpec, collect_trend_items

_LAZY_EXPORTS = {
    "WorkflowResult": ("ai_trends.daily", "WorkflowResult"),
    "run_daily_workflow": ("ai_trends.daily", "run_daily_workflow"),
    "run_weekly_workflow": ("ai_trends.weekly", "run_weekly_workflow"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _LAZY_EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

__all__ = [
    "AITrendsConfig",
    "AITrendsCollectionConfig",
    "ConfigError",
    "DailyDigest",
    "DiscordSendResult",
    "HermesEvaluationError",
    "RawTrendItem",
    "ScoredTrendItem",
    "SourceSpec",
    "WeeklyDigest",
    "WorkflowResult",
    "DEFAULT_TREND_SOURCES",
    "canonicalize_url",
    "collect_trend_items",
    "dedupe_trend_items",
    "evaluate_trend_item",
    "evaluate_trend_items",
    "append_collected_raw_items",
    "append_daily_digest",
    "append_raw_items",
    "append_weekly_digest",
    "load_ai_trends_collection_config",
    "load_ai_trends_config",
    "normalize_title",
    "read_sheet_rows",
    "render_daily_digest_message",
    "render_weekly_digest_message",
    "run_daily_workflow",
    "run_weekly_workflow",
    "send_discord_webhook",
    "update_discord_status",
]
