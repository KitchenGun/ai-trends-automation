"""Standalone scoring job for previously collected AI trends raw_items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Mapping, Sequence

from ai_trends.hermes_eval import HermesRequester, evaluate_trend_items
from ai_trends.models import RawTrendItem, ScoredTrendItem
from ai_trends.sheets import GwsSheetsClient, RAW_ITEMS_SHEET, SheetsClient, read_sheet_rows_with_numbers, update_raw_item_scores

AGENT_SCORE_RATIONALE_PREFIX = "Hermes agent: "
DEFAULT_SCORING_ITEM_LIMIT = 5
DEFAULT_RAW_ITEM_RETENTION_DAYS = 7


@dataclass(frozen=True)
class ScoringResult:
    """Secret-free scoring job result counters."""

    targeted: int
    succeeded: int
    failed: int
    skipped: int


def run_scoring_workflow(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str | None = None,
    now: datetime | None = None,
    item_limit: int | None = None,
    retention_days: int | None = None,
    hermes_requester: HermesRequester | None = None,
) -> ScoringResult:
    """Score a bounded batch of recent raw_items that lack trusted Hermes scores.

    One item failure is counted and left unchanged so a later cron run can retry it.
    """

    active_now = _ensure_aware_utc(now or datetime.now(timezone.utc))
    active_limit = item_limit if item_limit is not None else _scoring_item_limit()
    active_retention_days = retention_days if retention_days is not None else _raw_item_retention_days()
    rows = read_sheet_rows_with_numbers(sheets_client, RAW_ITEMS_SHEET, spreadsheet_id=spreadsheet_id)
    selected = select_rows_for_scoring(
        rows,
        now=active_now,
        retention_days=active_retention_days,
        limit=active_limit,
    )

    succeeded = 0
    failed = 0
    for row_number, raw_item in selected:
        try:
            scored_items = evaluate_trend_items((raw_item,), requester=hermes_requester)
            if not scored_items:
                failed += 1
                continue
            scored = _mark_agent_scored_item(scored_items[0])
            update_raw_item_scores(sheets_client, [(row_number, scored)], spreadsheet_id=spreadsheet_id)
        except Exception:
            failed += 1
            continue
        succeeded += 1

    return ScoringResult(
        targeted=len(selected),
        succeeded=succeeded,
        failed=failed,
        skipped=max(0, len(rows) - len(selected)),
    )


def select_rows_for_scoring(
    rows: Sequence[tuple[int, Mapping[str, str]]],
    *,
    now: datetime,
    retention_days: int,
    limit: int,
) -> list[tuple[int, RawTrendItem]]:
    """Select recent rows that do not already have a trusted Hermes agent score."""

    cutoff = _ensure_aware_utc(now) - timedelta(days=max(1, retention_days))
    selected: list[tuple[int, RawTrendItem]] = []
    for row_number, row in rows:
        if _row_has_agent_score(row):
            continue
        try:
            raw_item = _raw_item_from_row(row)
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
        if _ensure_aware_utc(raw_item.published_at) < cutoff:
            continue
        selected.append((row_number, raw_item))
        if len(selected) >= max(1, limit):
            break
    return selected


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the no_agent scoring cron job."""

    if argv is None:
        argv = []
    if argv:
        raise SystemExit("scoring entrypoint does not accept positional arguments")
    result = run_scoring_workflow(GwsSheetsClient())
    print(
        "AI 트렌드 scoring 완료: "
        f"대상={result.targeted} 성공={result.succeeded} 실패={result.failed} 건너뜀={result.skipped}"
    )
    return 0


def _row_has_agent_score(row: Mapping[str, str]) -> bool:
    return all(str(row.get(name, "")).strip() for name in ("relevance_score", "importance_score", "score_rationale")) and str(
        row.get("score_rationale", "")
    ).startswith(AGENT_SCORE_RATIONALE_PREFIX)


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


def _mark_agent_scored_item(item: ScoredTrendItem) -> ScoredTrendItem:
    if item.rationale.startswith(AGENT_SCORE_RATIONALE_PREFIX):
        return item
    return ScoredTrendItem(
        raw_item=item.raw_item,
        relevance_score=item.relevance_score,
        importance_score=item.importance_score,
        rationale=f"{AGENT_SCORE_RATIONALE_PREFIX}{item.rationale}",
    )


def _json_str_list(payload: str) -> list[str]:
    values = json.loads(payload or "[]")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("Expected a JSON list of strings")
    return values


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _scoring_item_limit() -> int:
    return _positive_env_int("AI_TRENDS_SCORING_ITEM_LIMIT", DEFAULT_SCORING_ITEM_LIMIT)


def _raw_item_retention_days() -> int:
    return _positive_env_int("AI_TRENDS_RAW_ITEM_RETENTION_DAYS", DEFAULT_RAW_ITEM_RETENTION_DAYS)


def _positive_env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(main())
