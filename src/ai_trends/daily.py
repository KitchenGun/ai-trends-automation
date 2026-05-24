"""Daily AI trends workflow entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import os
import json
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from ai_trends.config import load_ai_trends_config
from ai_trends.dedupe import dedupe_trend_items
from ai_trends.discord import DiscordTransport, render_daily_digest_message, send_discord_webhook
from ai_trends.hermes_eval import HermesRequester, evaluate_trend_items
from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem
from ai_trends.sheets import DAILY_DIGEST_SHEET, GwsSheetsClient, RAW_ITEMS_SHEET, SheetsClient, append_daily_digest, append_raw_items, read_sheet_rows, update_discord_status
from ai_trends.sources import DEFAULT_TREND_SOURCES, FetchText, SourceSpec, collect_trend_items

DAILY_BUSINESS_DAY_START = time(hour=8)
DEFAULT_DAILY_ITEM_LIMIT = 12
DEFAULT_DAILY_SOURCES: tuple[SourceSpec, ...] = DEFAULT_TREND_SOURCES


@dataclass(frozen=True)
class WorkflowResult:
    """Secret-free result metadata for a daily or weekly workflow run."""

    discord_status: str
    discord_error: str = ""
    discord_sent_at: str = ""
    digest_row_number: int | None = None


def run_daily_workflow(
    sheets_client: SheetsClient,
    *,
    sources: tuple[SourceSpec, ...] | list[SourceSpec],
    spreadsheet_id: str | None = None,
    discord_webhook_url: str | None = None,
    fetcher: FetchText | None = None,
    hermes_requester: HermesRequester | None = None,
    discord_transport: DiscordTransport | None = None,
    now: datetime | None = None,
    digest_date: str | None = None,
    collected_items: tuple[RawTrendItem, ...] | list[RawTrendItem] | None = None,
) -> WorkflowResult:
    """Run collect -> dedupe -> Hermes evaluate -> Sheets -> Discord daily lifecycle.

    Spreadsheet appends happen before Discord delivery. If either raw item or digest
    append raises, the exception propagates and Discord is not attempted. If Discord
    fails, the digest row remains appended with empty ``discord_sent_at`` and the
    row status is updated to ``failed`` with a safe error message.
    """

    config = None if spreadsheet_id and discord_webhook_url else load_ai_trends_config()
    active_spreadsheet_id = spreadsheet_id or config.spreadsheet_id  # type: ignore[union-attr]
    active_webhook_url = discord_webhook_url or config.discord_webhook_url  # type: ignore[union-attr]
    timezone_name = config.timezone if config is not None else "UTC"
    run_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    local_run_time = run_time.astimezone(ZoneInfo(timezone_name))

    raw_items = tuple(collected_items) if collected_items is not None else collect_trend_items(
        sources=sources,
        fetcher=fetcher,
        now=run_time,
        github_token=config.github_token if config is not None else None,
        x_bearer_token=config.x_bearer_token if config is not None else None,
    )
    raw_items = raw_items[:_daily_item_limit()]
    scored_items = evaluate_trend_items(dedupe_trend_items(raw_items), requester=hermes_requester)
    append_raw_items(sheets_client, scored_items, spreadsheet_id=active_spreadsheet_id)

    digest = DailyDigest(
        digest_date=digest_date or daily_digest_date(run_time, timezone_name=timezone_name).isoformat(),
        items=scored_items,
        summary=_daily_summary(scored_items),
    )
    append_result = append_daily_digest(
        sheets_client,
        digest,
        spreadsheet_id=active_spreadsheet_id,
        discord_status="pending",
        discord_error="",
        discord_sent_at="",
    )
    digest_row_number = _appended_row_number(append_result)

    discord_result = send_discord_webhook(
        active_webhook_url,
        render_daily_digest_message(digest),
        transport=discord_transport,
    )
    status_payload = discord_result.to_status_payload()
    sent_at = local_run_time.isoformat() if discord_result.ok else ""
    if digest_row_number is not None:
        update_discord_status(
            sheets_client,
            DAILY_DIGEST_SHEET,
            row_number=digest_row_number,
            status=status_payload["discord_status"],
            error=status_payload["discord_error"],
            sent_at=sent_at,
            spreadsheet_id=active_spreadsheet_id,
        )

    return WorkflowResult(
        discord_status=status_payload["discord_status"],
        discord_error=status_payload["discord_error"],
        discord_sent_at=sent_at,
        digest_row_number=digest_row_number,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the daily AI trends cron job."""

    if argv is None:
        argv = []
    if argv:
        raise SystemExit("daily entrypoint does not accept positional arguments")
    result = run_daily_digest_workflow(GwsSheetsClient())
    print(f"일간 AI 트렌드 보고 완료: Discord 상태={result.discord_status}")
    return 0


def run_daily_digest_workflow(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str | None = None,
    discord_webhook_url: str | None = None,
    discord_transport: DiscordTransport | None = None,
    now: datetime | None = None,
    digest_date: str | None = None,
    scored_items: tuple[ScoredTrendItem, ...] | list[ScoredTrendItem] | None = None,
    hermes_requester: HermesRequester | None = None,
) -> WorkflowResult:
    """Create the daily digest from already collected ``raw_items`` rows."""

    config = None if spreadsheet_id and discord_webhook_url else load_ai_trends_config()
    active_spreadsheet_id = spreadsheet_id or config.spreadsheet_id  # type: ignore[union-attr]
    active_webhook_url = discord_webhook_url or config.discord_webhook_url  # type: ignore[union-attr]
    timezone_name = config.timezone if config is not None else "UTC"
    run_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    local_run_time = run_time.astimezone(ZoneInfo(timezone_name))
    active_digest_date = digest_date or daily_digest_date(run_time, timezone_name=timezone_name).isoformat()

    items = tuple(scored_items) if scored_items is not None else _read_daily_scored_items(
        sheets_client,
        spreadsheet_id=active_spreadsheet_id,
        digest_date=active_digest_date,
        timezone_name=timezone_name,
        hermes_requester=hermes_requester,
    )
    deduped_items = _dedupe_scored_items(items)[:_daily_item_limit()]
    if not deduped_items:
        return WorkflowResult(
            discord_status="skipped",
            discord_error=f"보고 날짜 {active_digest_date}에 해당하는 raw_items가 없습니다",
        )
    digest = DailyDigest(
        digest_date=active_digest_date,
        items=deduped_items,
        summary=_daily_summary(deduped_items),
    )
    append_result = append_daily_digest(
        sheets_client,
        digest,
        spreadsheet_id=active_spreadsheet_id,
        discord_status="pending",
        discord_error="",
        discord_sent_at="",
    )
    digest_row_number = _appended_row_number(append_result)

    discord_result = send_discord_webhook(
        active_webhook_url,
        render_daily_digest_message(digest),
        transport=discord_transport,
    )
    status_payload = discord_result.to_status_payload()
    sent_at = local_run_time.isoformat() if discord_result.ok else ""
    if digest_row_number is not None:
        update_discord_status(
            sheets_client,
            DAILY_DIGEST_SHEET,
            row_number=digest_row_number,
            status=status_payload["discord_status"],
            error=status_payload["discord_error"],
            sent_at=sent_at,
            spreadsheet_id=active_spreadsheet_id,
        )

    return WorkflowResult(
        discord_status=status_payload["discord_status"],
        discord_error=status_payload["discord_error"],
        discord_sent_at=sent_at,
        digest_row_number=digest_row_number,
    )


def _daily_summary(items: tuple[Any, ...]) -> str:
    top_titles = ", ".join(item.raw_item.title for item in items[:3])
    return f"일간 AI 에이전트 트렌드 보고: 총 {len(items)}개 항목을 다룹니다. 주요 항목: {top_titles}."


def _read_daily_scored_items(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str,
    digest_date: str,
    timezone_name: str,
    hermes_requester: HermesRequester | None = None,
) -> tuple[ScoredTrendItem, ...]:
    rows = read_sheet_rows(sheets_client, RAW_ITEMS_SHEET, spreadsheet_id=spreadsheet_id)
    items: list[ScoredTrendItem] = []
    unscored_items: list[RawTrendItem] = []
    zone = ZoneInfo(timezone_name)
    for row in rows:
        raw_item = _raw_item_from_row(row)
        if raw_item.published_at.astimezone(zone).date().isoformat() != digest_date:
            continue
        if _row_has_score(row):
            items.append(_scored_item_from_row(row))
        else:
            unscored_items.append(raw_item)
        if len(items) + len(unscored_items) >= _daily_item_limit():
            break
    if unscored_items:
        for item in evaluate_trend_items(dedupe_trend_items(tuple(unscored_items)), requester=hermes_requester):
            items.append(item)
    return tuple(items)


def _raw_item_from_row(row: Mapping[str, str]) -> RawTrendItem:
    return RawTrendItem(
        source_name=row["source_name"],
        source_type=row["source_type"],
        title=row["title"],
        url=row["url"],
        published_at=datetime.fromisoformat(row["published_at"]),
        summary=row["summary"],
        tags=tuple(_json_str_list(row["tags_json"])),
        evidence_urls=tuple(_json_str_list(row["evidence_urls_json"])),
    )


def _scored_item_from_row(row: Mapping[str, str]) -> ScoredTrendItem:
    raw = _raw_item_from_row(row)
    return ScoredTrendItem(
        raw_item=raw,
        relevance_score=int(row["relevance_score"]),
        importance_score=int(row["importance_score"]),
        rationale=row["score_rationale"],
    )


def _row_has_score(row: Mapping[str, str]) -> bool:
    return all(str(row.get(name, "")).strip() for name in ("relevance_score", "importance_score", "score_rationale"))


def _dedupe_scored_items(items: tuple[ScoredTrendItem, ...]) -> tuple[ScoredTrendItem, ...]:
    deduped_raw_items = dedupe_trend_items(tuple(item.raw_item for item in items))
    by_identity = {(item.raw_item.source_name, item.raw_item.title, item.raw_item.url): item for item in items}
    return tuple(by_identity[(item.source_name, item.title, item.url)] for item in deduped_raw_items)


def _json_str_list(payload: str) -> list[str]:
    values = json.loads(payload)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("Expected a JSON list of strings")
    return values


def _appended_row_number(append_result: object) -> int | None:
    if not isinstance(append_result, dict):
        return None
    updated_range = append_result.get("updatedRange")
    updates = append_result.get("updates")
    if updated_range is None and isinstance(updates, dict):
        updated_range = updates.get("updatedRange")
    if not isinstance(updated_range, str):
        return None
    cell_range = updated_range.split("!", 1)[-1]
    first_cell = cell_range.split(":", 1)[0]
    digits = "".join(character for character in first_cell if character.isdigit())
    return int(digits) if digits else None


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def daily_digest_date(run_time: datetime, *, timezone_name: str) -> date:
    local_time = _ensure_aware_utc(run_time).astimezone(ZoneInfo(timezone_name))
    if local_time.timetz().replace(tzinfo=None) < DAILY_BUSINESS_DAY_START:
        return local_time.date() - timedelta(days=1)
    return local_time.date()


def _daily_item_limit() -> int:
    raw_value = os.environ.get("AI_TRENDS_DAILY_ITEM_LIMIT", "").strip()
    if not raw_value:
        return DEFAULT_DAILY_ITEM_LIMIT
    try:
        return max(1, min(50, int(raw_value)))
    except ValueError:
        return DEFAULT_DAILY_ITEM_LIMIT


if __name__ == "__main__":
    raise SystemExit(main())
