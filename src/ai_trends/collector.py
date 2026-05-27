"""Hourly AI trends raw collection entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os

from ai_trends.config import load_ai_trends_collection_config
from ai_trends.daily import _ensure_aware_utc
from ai_trends.dedupe import canonicalize_url, dedupe_trend_items, normalize_title
from ai_trends.models import RawTrendItem
from ai_trends.sheets import GwsSheetsClient, RAW_ITEMS_SHEET, SheetsClient, append_collected_raw_items, delete_sheet_rows, read_sheet_rows, read_sheet_rows_with_numbers
from ai_trends.sources import DEFAULT_TREND_SOURCES, FetchText, SourceSpec, collect_trend_items

DEFAULT_COLLECTION_ITEM_LIMIT = 20
DEFAULT_RAW_ITEM_RETENTION_DAYS = 7


@dataclass(frozen=True)
class CollectionResult:
    collected_count: int
    new_count: int
    appended_count: int
    pruned_count: int = 0


def run_collection_workflow(
    sheets_client: SheetsClient,
    *,
    sources: tuple[SourceSpec, ...] | list[SourceSpec] = DEFAULT_TREND_SOURCES,
    spreadsheet_id: str | None = None,
    fetcher: FetchText | None = None,
    now: datetime | None = None,
    collected_items: tuple[RawTrendItem, ...] | list[RawTrendItem] | None = None,
) -> CollectionResult:
    """Collect public items, filter duplicates, and append unscored ``raw_items``."""

    config = None if spreadsheet_id else load_ai_trends_collection_config()
    active_spreadsheet_id = spreadsheet_id or config.spreadsheet_id  # type: ignore[union-attr]
    run_time = _ensure_aware_utc(now or datetime.now(timezone.utc))

    raw_items = tuple(collected_items) if collected_items is not None else collect_trend_items(
        sources=sources,
        fetcher=fetcher,
        now=run_time,
        github_token=config.github_token if config is not None else None,
        x_bearer_token=config.x_bearer_token if config is not None else None,
        x_rss_feeds_json=config.x_rss_feeds_json if config is not None else None,
        x_rss_feeds_file=config.x_rss_feeds_file if config is not None else None,
    )
    pruned_count = prune_stale_raw_items(
        sheets_client,
        spreadsheet_id=active_spreadsheet_id,
        now=run_time,
    )
    retained_items = _filter_retained_items(raw_items, now=run_time)
    deduped_items = dedupe_trend_items(retained_items)
    existing_rows = read_sheet_rows(sheets_client, RAW_ITEMS_SHEET, spreadsheet_id=active_spreadsheet_id)
    new_items = _filter_existing_items(deduped_items, existing_rows)
    limited_items = _select_collection_window(new_items, limit=_collection_item_limit())
    if limited_items:
        append_collected_raw_items(sheets_client, limited_items, spreadsheet_id=active_spreadsheet_id)

    return CollectionResult(
        collected_count=len(raw_items),
        new_count=len(new_items),
        appended_count=len(limited_items),
        pruned_count=pruned_count,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = []
    if argv:
        raise SystemExit("collector entrypoint does not accept positional arguments")
    result = run_collection_workflow(GwsSheetsClient())
    print(
        "시간별 AI 트렌드 수집 완료: "
        f"수집={result.collected_count} 신규={result.new_count} 추가={result.appended_count} 삭제={result.pruned_count}"
    )
    return 0


def prune_stale_raw_items(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str,
    now: datetime,
    retention_days: int | None = None,
) -> int:
    """Delete raw item rows older than the retention window."""

    active_retention_days = retention_days if retention_days is not None else _raw_item_retention_days()
    cutoff = _ensure_aware_utc(now) - timedelta(days=active_retention_days)
    stale_row_numbers: list[int] = []
    for row_number, row in read_sheet_rows_with_numbers(sheets_client, RAW_ITEMS_SHEET, spreadsheet_id=spreadsheet_id):
        published_at = _parse_row_datetime(row.get("published_at", ""))
        if published_at is not None and published_at < cutoff:
            stale_row_numbers.append(row_number)
    delete_sheet_rows(sheets_client, RAW_ITEMS_SHEET, stale_row_numbers, spreadsheet_id=spreadsheet_id)
    return len(stale_row_numbers)


def _filter_retained_items(items: tuple[RawTrendItem, ...], *, now: datetime) -> tuple[RawTrendItem, ...]:
    cutoff = _ensure_aware_utc(now) - timedelta(days=_raw_item_retention_days())
    return tuple(item for item in items if _ensure_aware_utc(item.published_at) >= cutoff)


def _filter_existing_items(items: tuple[RawTrendItem, ...], rows: list[dict[str, str]]) -> tuple[RawTrendItem, ...]:
    existing_urls = {canonicalize_url(row["url"]) for row in rows if row.get("url")}
    existing_title_source = {
        (_normalize_source_name(row.get("source_name", "")), normalize_title(row.get("title", "")))
        for row in rows
        if row.get("source_name") and row.get("title")
    }
    out: list[RawTrendItem] = []
    for item in items:
        if canonicalize_url(item.url) in existing_urls:
            continue
        if (_normalize_source_name(item.source_name), normalize_title(item.title)) in existing_title_source:
            continue
        out.append(item)
    return tuple(out)


def _select_collection_window(items: tuple[RawTrendItem, ...], *, limit: int) -> tuple[RawTrendItem, ...]:
    """Pick new items fairly across sources before applying the global append limit."""

    if limit <= 0 or not items:
        return ()
    by_source: dict[str, list[RawTrendItem]] = {}
    source_order: list[str] = []
    for item in items:
        key = _normalize_source_name(item.source_name)
        if key not in by_source:
            by_source[key] = []
            source_order.append(key)
        by_source[key].append(item)

    selected: list[RawTrendItem] = []
    index = 0
    while len(selected) < limit:
        added_this_round = False
        for source_key in source_order:
            source_items = by_source[source_key]
            if index >= len(source_items):
                continue
            selected.append(source_items[index])
            added_this_round = True
            if len(selected) >= limit:
                break
        if not added_this_round:
            break
        index += 1
    return tuple(selected)


def _collection_item_limit() -> int:
    raw_value = os.environ.get("AI_TRENDS_COLLECTION_ITEM_LIMIT", "").strip()
    if not raw_value:
        return DEFAULT_COLLECTION_ITEM_LIMIT
    try:
        return max(1, min(20, int(raw_value)))
    except ValueError:
        return DEFAULT_COLLECTION_ITEM_LIMIT


def _raw_item_retention_days() -> int:
    raw_value = os.environ.get("AI_TRENDS_RAW_ITEM_RETENTION_DAYS", "").strip()
    if not raw_value:
        return DEFAULT_RAW_ITEM_RETENTION_DAYS
    try:
        return max(1, min(365, int(raw_value)))
    except ValueError:
        return DEFAULT_RAW_ITEM_RETENTION_DAYS


def _parse_row_datetime(value: str) -> datetime | None:
    try:
        return _ensure_aware_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _normalize_source_name(source_name: str) -> str:
    return " ".join(source_name.casefold().split())


if __name__ == "__main__":
    raise SystemExit(main())
