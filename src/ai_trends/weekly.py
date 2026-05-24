"""Weekly AI trends workflow entrypoint."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import shutil
import subprocess
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ai_trends.config import load_ai_trends_config
from ai_trends.daily import WorkflowResult, _appended_row_number, _ensure_aware_utc
from ai_trends.dedupe import dedupe_trend_items
from ai_trends.discord import DiscordTransport, render_weekly_digest_message, send_discord_webhook
from ai_trends.hermes_eval import HermesRequester, evaluate_trend_items
from ai_trends.models import RawTrendItem, ScoredTrendItem, WeeklyDigest
from ai_trends.sheets import RAW_ITEMS_SHEET, WEEKLY_DIGEST_SHEET, GwsSheetsClient, SheetsClient, append_weekly_digest, read_sheet_rows, update_discord_status

SummaryRequester = Callable[[str], str]
DEFAULT_WEEKLY_ITEM_LIMIT = 20


def run_weekly_workflow(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str | None = None,
    discord_webhook_url: str | None = None,
    discord_transport: DiscordTransport | None = None,
    summary_requester: SummaryRequester | None = None,
    hermes_requester: HermesRequester | None = None,
    now: datetime | None = None,
    week_start: str | None = None,
    week_end: str | None = None,
    scored_items: tuple[ScoredTrendItem, ...] | list[ScoredTrendItem] | None = None,
) -> WorkflowResult:
    """Run read week window -> dedupe -> Hermes summary -> Sheets -> Discord lifecycle.

    The weekly workflow is a separate entrypoint from daily collection. Spreadsheet
    append failure aborts Discord delivery. Discord failure leaves the appended row
    with empty ``discord_sent_at`` and updates status/error columns only with safe
    non-secret values.
    """

    config = None if spreadsheet_id and discord_webhook_url else load_ai_trends_config()
    active_spreadsheet_id = spreadsheet_id or config.spreadsheet_id  # type: ignore[union-attr]
    active_webhook_url = discord_webhook_url or config.discord_webhook_url  # type: ignore[union-attr]
    timezone_name = config.timezone if config is not None else "UTC"
    run_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    local_run_time = run_time.astimezone(ZoneInfo(timezone_name))
    start_date, end_date = _week_window(local_run_time, week_start=week_start, week_end=week_end)

    items = tuple(scored_items) if scored_items is not None else _read_scored_items(
        sheets_client,
        spreadsheet_id=active_spreadsheet_id,
        week_start=start_date,
        week_end=end_date,
        hermes_requester=hermes_requester,
    )
    deduped_items = _dedupe_scored_items(items)[:_weekly_item_limit()]
    summary = _weekly_summary(deduped_items, start_date=start_date, end_date=end_date, requester=summary_requester)
    digest = WeeklyDigest(
        week_start=start_date.isoformat(),
        week_end=end_date.isoformat(),
        items=deduped_items,
        summary=summary,
    )
    append_result = append_weekly_digest(
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
        render_weekly_digest_message(digest),
        transport=discord_transport,
    )
    status_payload = discord_result.to_status_payload()
    sent_at = local_run_time.isoformat() if discord_result.ok else ""
    if digest_row_number is not None:
        update_discord_status(
            sheets_client,
            WEEKLY_DIGEST_SHEET,
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
    """CLI entrypoint for the weekly AI trends cron job."""

    if argv is None:
        argv = []
    if argv:
        raise SystemExit("weekly entrypoint does not accept positional arguments")
    result = run_weekly_workflow(GwsSheetsClient())
    print(f"주간 AI 트렌드 보고 완료: Discord 상태={result.discord_status}")
    return 0


def _week_window(run_time: datetime, *, week_start: str | None, week_end: str | None) -> tuple[date, date]:
    if week_start is not None and week_end is not None:
        start_date = date.fromisoformat(week_start)
        end_date = date.fromisoformat(week_end)
    elif week_start is None and week_end is None:
        end_date = run_time.date()
        start_date = date.fromordinal(end_date.toordinal() - 6)
    else:
        raise ValueError("week_start and week_end must be provided together")
    if end_date < start_date:
        raise ValueError("week_end must be on or after week_start")
    return start_date, end_date


def _read_scored_items(
    sheets_client: SheetsClient,
    *,
    spreadsheet_id: str,
    week_start: date,
    week_end: date,
    hermes_requester: HermesRequester | None = None,
) -> tuple[ScoredTrendItem, ...]:
    rows = read_sheet_rows(sheets_client, RAW_ITEMS_SHEET, spreadsheet_id=spreadsheet_id)
    items: list[ScoredTrendItem] = []
    unscored_items: list[RawTrendItem] = []
    for row in rows:
        raw_item = _raw_item_from_row(row)
        published_date = raw_item.published_at.date()
        if not week_start <= published_date <= week_end:
            continue
        if _row_has_score(row):
            items.append(_scored_item_from_row(row))
        else:
            unscored_items.append(raw_item)
        if len(items) + len(unscored_items) >= _weekly_item_limit():
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


def _weekly_summary(
    items: tuple[ScoredTrendItem, ...],
    *,
    start_date: date,
    end_date: date,
    requester: SummaryRequester | None,
) -> str:
    prompt = _weekly_summary_prompt(items, start_date=start_date, end_date=end_date)
    response = (requester or _request_hermes_cli)(prompt).strip()
    if not response:
        raise ValueError("Weekly summary must be non-blank")
    return response


def _weekly_summary_prompt(items: tuple[ScoredTrendItem, ...], *, start_date: date, end_date: date) -> str:
    item_lines = "\n".join(
        f"- {item.raw_item.title} ({item.raw_item.url}) relevance={item.relevance_score} importance={item.importance_score}: {item.rationale}"
        for item in items
    )
    return (
        "Discord에 게시할 주간 AI 에이전트 트렌드 보고 요약을 한국어로 간결하게 작성하세요.\n"
        f"보고 기간: {start_date.isoformat()} ~ {end_date.isoformat()}\n"
        "관련 항목을 묶고 중복 강조를 제거하며 AI 에이전트 개발자에게 주는 구체적 영향을 강조하세요.\n"
        "원문 기사 제목, GitHub 저장소명, 논문 제목 같은 고유명사는 번역하지 않아도 됩니다.\n"
        f"항목:\n{item_lines}\n"
    )


def _request_hermes_cli(prompt: str) -> str:
    completed = subprocess.run(
        [_hermes_bin(), "-z", prompt],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout.strip()


def _hermes_bin() -> str:
    return os.environ.get("HERMES_BIN") or shutil.which("hermes") or "hermes"


def _weekly_item_limit() -> int:
    raw_value = os.environ.get("AI_TRENDS_WEEKLY_ITEM_LIMIT", "").strip()
    if not raw_value:
        return DEFAULT_WEEKLY_ITEM_LIMIT
    try:
        return max(1, min(50, int(raw_value)))
    except ValueError:
        return DEFAULT_WEEKLY_ITEM_LIMIT


def _json_str_list(payload: str) -> list[str]:
    values = json.loads(payload)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("Expected a JSON list of strings")
    return values


if __name__ == "__main__":
    raise SystemExit(main())
