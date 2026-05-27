from datetime import datetime, timezone
import json

from ai_trends.daily import run_daily_digest_workflow
from ai_trends.models import RawTrendItem, ScoredTrendItem
from ai_trends.sheets import DAILY_DIGEST_COLUMNS, RAW_ITEMS_COLUMNS, WEEKLY_DIGEST_COLUMNS
from ai_trends.weekly import run_weekly_workflow


class SheetMapClient:
    def __init__(self, values_by_sheet: dict[str, list[list[str]]]) -> None:
        self.values_by_sheet = values_by_sheet
        self.append_calls: list[tuple[str, str, list[list[str]]]] = []
        self.update_calls: list[tuple[str, str, list[list[str]]]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.append_calls.append((spreadsheet_id, range_name, values))
        row_number = len(self.values_by_sheet.get(range_name.split("!", 1)[0], [])) + len(self.append_calls) + 1
        end_column = range_name.rsplit(":", 1)[1]
        sheet_name = range_name.split("!", 1)[0]
        return {"updates": {"updatedRange": f"{sheet_name}!A{row_number}:{end_column}{row_number}"}}

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return self.values_by_sheet.get(range_name.split("!", 1)[0], [])

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.update_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}


def _raw_item(title: str = "Hermes autonomous review", url: str = "https://example.invalid/review") -> RawTrendItem:
    return RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title=title,
        url=url,
        published_at=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
        summary="Hermes adds agentic code review workflows.",
        tags=("ai-agent", "code-review"),
        evidence_urls=(url,),
    )


def _scored_item(title: str = "Hermes autonomous review", url: str = "https://example.invalid/review") -> ScoredTrendItem:
    return ScoredTrendItem(
        raw_item=_raw_item(title=title, url=url),
        relevance_score=9,
        importance_score=8,
        rationale="Hermes agent: Official evidence with concrete AI-agent workflow impact.",
    )


def _raw_row(item: ScoredTrendItem) -> list[str]:
    raw = item.raw_item
    return [
        raw.source_name,
        raw.source_type,
        raw.title,
        raw.url,
        raw.published_at.isoformat(),
        raw.summary,
        json.dumps(list(raw.tags), separators=(",", ":")),
        json.dumps(list(raw.evidence_urls), separators=(",", ":")),
        str(item.relevance_score),
        str(item.importance_score),
        item.rationale,
    ]


def _daily_digest_row(*, digest_date: str, links: list[str]) -> list[str]:
    return [
        digest_date,
        "existing summary",
        str(len(links)),
        json.dumps(["Existing title"] * len(links), separators=(",", ":")),
        json.dumps(links, separators=(",", ":")),
        json.dumps(["existing rationale"] * len(links), separators=(",", ":")),
        "{}",
        "sent",
        "",
        "2026-05-22T09:30:00+00:00",
        "",
    ]


def _weekly_digest_row(*, week_start: str, week_end: str, links: list[str]) -> list[str]:
    return [
        week_start,
        week_end,
        "existing summary",
        str(len(links)),
        json.dumps(["Existing title"] * len(links), separators=(",", ":")),
        json.dumps(links, separators=(",", ":")),
        json.dumps(["existing rationale"] * len(links), separators=(",", ":")),
        "{}",
        "sent",
        "",
        "2026-05-24T09:30:00+00:00",
        "",
    ]


def test_daily_digest_skips_existing_digest_date_with_same_item_set_and_does_not_send_discord() -> None:
    item = _scored_item(url="https://example.invalid/review?utm_source=rss")
    sheets = SheetMapClient(
        {
            "raw_items": [list(RAW_ITEMS_COLUMNS), _raw_row(item)],
            "daily_digest": [
                list(DAILY_DIGEST_COLUMNS),
                _daily_digest_row(digest_date="2026-05-22", links=["https://example.invalid/review"]),
            ],
        }
    )
    discord_calls: list[str] = []

    result = run_daily_digest_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        discord_transport=lambda _url, _headers, body: (discord_calls.append(body.decode()), (204, ""))[1],
        digest_date="2026-05-22",
    )

    assert result.discord_status == "skipped"
    assert "동일" in result.discord_error
    assert sheets.append_calls == []
    assert sheets.update_calls == []
    assert discord_calls == []


def test_weekly_digest_skips_existing_week_window_with_same_item_set_and_does_not_send_discord() -> None:
    item = _scored_item(url="https://example.invalid/review?ref=github")
    sheets = SheetMapClient(
        {
            "raw_items": [list(RAW_ITEMS_COLUMNS), _raw_row(item)],
            "weekly_digest": [
                list(WEEKLY_DIGEST_COLUMNS),
                _weekly_digest_row(
                    week_start="2026-05-18",
                    week_end="2026-05-24",
                    links=["https://example.invalid/review"],
                ),
            ],
        }
    )
    discord_calls: list[str] = []

    result = run_weekly_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        discord_transport=lambda _url, _headers, body: (discord_calls.append(body.decode()), (204, ""))[1],
        summary_requester=lambda _prompt: "Weekly summary for AI agent builders.",
        week_start="2026-05-18",
        week_end="2026-05-24",
    )

    assert result.discord_status == "skipped"
    assert "동일" in result.discord_error
    assert sheets.append_calls == []
    assert sheets.update_calls == []
    assert discord_calls == []
