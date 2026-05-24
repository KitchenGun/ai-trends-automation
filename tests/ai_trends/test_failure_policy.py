from datetime import datetime, timezone

import pytest

from ai_trends.daily import run_daily_digest_workflow, run_daily_workflow
from ai_trends.models import RawTrendItem, ScoredTrendItem
from ai_trends.sheets import DAILY_DIGEST_COLUMNS, WEEKLY_DIGEST_COLUMNS
from ai_trends.weekly import run_weekly_workflow


class RecordingSheetsClient:
    def __init__(self, *, fail_on_append_range: str | None = None) -> None:
        self.fail_on_append_range = fail_on_append_range
        self.append_calls: list[tuple[str, str, list[list[str]]]] = []
        self.update_calls: list[tuple[str, str, list[list[str]]]] = []
        self.values: list[list[str]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        if self.fail_on_append_range is not None and self.fail_on_append_range in range_name:
            raise RuntimeError("spreadsheet append failed")
        self.append_calls.append((spreadsheet_id, range_name, values))
        row_number = len(self.append_calls) + 1
        end_column = range_name.rsplit(":", 1)[1]
        sheet_name = range_name.split("!", 1)[0]
        return {"updates": {"updatedRange": f"{sheet_name}!A{row_number}:{end_column}{row_number}"}}

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return self.values

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.update_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}


def _raw_item(title: str = "Hermes autonomous review") -> RawTrendItem:
    return RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title=title,
        url=f"https://example.invalid/{title.lower().replace(' ', '-')}",
        published_at=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
        summary="Hermes adds agentic code review workflows.",
        tags=("ai-agent", "code-review"),
        evidence_urls=("https://example.invalid/review",),
    )


def _scored_item(title: str = "Hermes autonomous review") -> ScoredTrendItem:
    return ScoredTrendItem(
        raw_item=_raw_item(title),
        relevance_score=9,
        importance_score=8,
        rationale="Official evidence with concrete AI-agent workflow impact.",
    )


def test_daily_spreadsheet_append_failure_prevents_discord_send() -> None:
    sheets = RecordingSheetsClient(fail_on_append_range="daily_digest")
    discord_calls: list[str] = []

    with pytest.raises(RuntimeError, match="spreadsheet append failed"):
        run_daily_workflow(
            sheets,
            sources=(),
            collected_items=(_raw_item(),),
            spreadsheet_id="sheet-id",
            discord_webhook_url="https://example.invalid/webhook-secret",
            hermes_requester=lambda _prompt: '{"relevance_score":9,"importance_score":8,"rationale":"Official evidence"}',
            discord_transport=lambda _url, _headers, body: (discord_calls.append(body.decode()), (204, ""))[1],
            digest_date="2026-05-22",
        )

    assert discord_calls == []
    assert not sheets.update_calls


def test_weekly_spreadsheet_append_failure_prevents_discord_send() -> None:
    sheets = RecordingSheetsClient(fail_on_append_range="weekly_digest")
    sheets.values = [
        [
            "source_name",
            "source_type",
            "title",
            "url",
            "published_at",
            "summary",
            "tags_json",
            "evidence_urls_json",
            "relevance_score",
            "importance_score",
            "score_rationale",
        ],
        [
            "Official Blog",
            "blog",
            "Hermes autonomous review",
            "https://example.invalid/review",
            "2026-05-22T09:00:00+00:00",
            "Hermes adds agentic code review workflows.",
            '["ai-agent","code-review"]',
            '["https://example.invalid/review"]',
            "9",
            "8",
            "Official evidence with concrete AI-agent workflow impact.",
        ],
    ]
    discord_calls: list[str] = []

    with pytest.raises(RuntimeError, match="spreadsheet append failed"):
        run_weekly_workflow(
            sheets,
            spreadsheet_id="sheet-id",
            discord_webhook_url="https://example.invalid/webhook-secret",
            discord_transport=lambda _url, _headers, body: (discord_calls.append(body.decode()), (204, ""))[1],
            summary_requester=lambda _prompt: "Weekly summary for AI agent builders.",
            week_start="2026-05-18",
            week_end="2026-05-24",
        )

    assert discord_calls == []
    assert not sheets.update_calls


def test_daily_discord_failure_preserves_digest_row_with_empty_sent_at_and_failed_status() -> None:
    sheets = RecordingSheetsClient()

    result = run_daily_workflow(
        sheets,
        sources=(),
        collected_items=(_raw_item(),),
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        hermes_requester=lambda _prompt: '{"relevance_score":9,"importance_score":8,"rationale":"Official evidence"}',
        discord_transport=lambda _url, _headers, _body: (500, "upstream discord error"),
        digest_date="2026-05-22",
    )

    digest_row = sheets.append_calls[1][2][0]
    assert digest_row[DAILY_DIGEST_COLUMNS.index("discord_status")] == "pending"
    assert digest_row[DAILY_DIGEST_COLUMNS.index("discord_sent_at")] == ""
    assert result.discord_status == "failed"
    assert result.discord_sent_at == ""
    assert sheets.update_calls[-1] == (
        "sheet-id",
        "daily_digest!H3:J3",
        [["failed", "Discord webhook returned HTTP 500: upstream discord error", ""]],
    )


def test_daily_digest_scores_unscored_raw_rows_at_report_time() -> None:
    sheets = RecordingSheetsClient()
    sheets.values = [
        [
            "source_name",
            "source_type",
            "title",
            "url",
            "published_at",
            "summary",
            "tags_json",
            "evidence_urls_json",
            "relevance_score",
            "importance_score",
            "score_rationale",
        ],
        [
            "Official Blog",
            "blog",
            "Hermes autonomous review",
            "https://example.invalid/review",
            "2026-05-22T09:00:00+00:00",
            "Hermes adds agentic code review workflows.",
            '["ai-agent","code-review"]',
            '["https://example.invalid/review"]',
            "",
            "",
            "",
        ],
    ]

    result = run_daily_digest_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        hermes_requester=lambda _prompt: '{"relevance_score":9,"importance_score":8,"rationale":"Report-time scoring"}',
        discord_transport=lambda _url, _headers, _body: (204, ""),
        digest_date="2026-05-22",
    )

    assert result.discord_status == "sent"
    digest_row = sheets.append_calls[0][2][0]
    assert "Report-time scoring" in digest_row[DAILY_DIGEST_COLUMNS.index("score_rationales_json")]


def test_weekly_discord_failure_preserves_digest_row_with_empty_sent_at_and_failed_status() -> None:
    sheets = RecordingSheetsClient()
    sheets.values = [["items_json"], [_scored_item().to_dict()["raw_item"]["title"]]]

    result = run_weekly_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        discord_transport=lambda _url, _headers, _body: (500, "upstream discord error"),
        summary_requester=lambda _prompt: "Weekly summary for AI agent builders.",
        scored_items=(_scored_item(),),
        week_start="2026-05-18",
        week_end="2026-05-24",
    )

    digest_row = sheets.append_calls[0][2][0]
    assert digest_row[WEEKLY_DIGEST_COLUMNS.index("discord_status")] == "pending"
    assert digest_row[WEEKLY_DIGEST_COLUMNS.index("discord_sent_at")] == ""
    assert result.discord_status == "failed"
    assert result.discord_sent_at == ""
    assert sheets.update_calls[-1] == (
        "sheet-id",
        "weekly_digest!I2:K2",
        [["failed", "Discord webhook returned HTTP 500: upstream discord error", ""]],
    )


def test_weekly_report_scores_unscored_raw_rows_at_report_time() -> None:
    sheets = RecordingSheetsClient()
    sheets.values = [
        [
            "source_name",
            "source_type",
            "title",
            "url",
            "published_at",
            "summary",
            "tags_json",
            "evidence_urls_json",
            "relevance_score",
            "importance_score",
            "score_rationale",
        ],
        [
            "Official Blog",
            "blog",
            "Hermes autonomous review",
            "https://example.invalid/review",
            "2026-05-22T09:00:00+00:00",
            "Hermes adds agentic code review workflows.",
            '["ai-agent","code-review"]',
            '["https://example.invalid/review"]',
            "",
            "",
            "",
        ],
    ]

    result = run_weekly_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        discord_webhook_url="https://example.invalid/webhook-secret",
        discord_transport=lambda _url, _headers, _body: (204, ""),
        summary_requester=lambda _prompt: "Weekly summary for AI agent builders.",
        hermes_requester=lambda _prompt: '{"relevance_score":9,"importance_score":8,"rationale":"Weekly report-time scoring"}',
        week_start="2026-05-18",
        week_end="2026-05-24",
    )

    assert result.discord_status == "sent"
    digest_row = sheets.append_calls[0][2][0]
    assert "Weekly report-time scoring" in digest_row[WEEKLY_DIGEST_COLUMNS.index("score_rationales_json")]
