from datetime import datetime, timezone
import json

from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem, WeeklyDigest
from ai_trends.sheets import (
    DAILY_DIGEST_COLUMNS,
    RAW_ITEMS_COLUMNS,
    WEEKLY_DIGEST_COLUMNS,
    append_collected_raw_items,
    append_daily_digest,
    append_raw_items,
    append_weekly_digest,
    collected_raw_item_row,
    daily_digest_row,
    raw_item_row,
    read_sheet_rows,
    update_discord_status,
    weekly_digest_row,
)


class FakeSheetsClient:
    def __init__(self) -> None:
        self.append_calls: list[tuple[str, str, list[list[str]]]] = []
        self.read_calls: list[tuple[str, str]] = []
        self.update_calls: list[tuple[str, str, list[list[str]]]] = []
        self.values: list[list[str]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.append_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        self.read_calls.append((spreadsheet_id, range_name))
        return self.values

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.update_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}


def _scored_item() -> ScoredTrendItem:
    raw = RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title="Hermes autonomous review",
        url="https://example.invalid/review",
        published_at=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
        summary="Hermes adds agentic code review workflows.",
        tags=("ai-agent", "code-review"),
        evidence_urls=("https://example.invalid/review", "https://example.invalid/docs"),
    )
    return ScoredTrendItem(
        raw_item=raw,
        relevance_score=9,
        importance_score=8,
        rationale="Official evidence with concrete AI-agent workflow impact.",
    )


def test_raw_item_row_order_matches_schema_and_uses_json_for_lists() -> None:
    scored = _scored_item()

    assert RAW_ITEMS_COLUMNS == (
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
    )
    assert raw_item_row(scored) == [
        "Official Blog",
        "blog",
        "Hermes autonomous review",
        "https://example.invalid/review",
        "2026-05-22T09:00:00+00:00",
        "Hermes adds agentic code review workflows.",
        json.dumps(["ai-agent", "code-review"], separators=(",", ":")),
        json.dumps(["https://example.invalid/review", "https://example.invalid/docs"], separators=(",", ":")),
        "9",
        "8",
        "Official evidence with concrete AI-agent workflow impact.",
    ]


def test_collected_raw_item_row_leaves_score_columns_blank() -> None:
    raw = _scored_item().raw_item

    assert collected_raw_item_row(raw) == [
        "Official Blog",
        "blog",
        "Hermes autonomous review",
        "https://example.invalid/review",
        "2026-05-22T09:00:00+00:00",
        "Hermes adds agentic code review workflows.",
        json.dumps(["ai-agent", "code-review"], separators=(",", ":")),
        json.dumps(["https://example.invalid/review", "https://example.invalid/docs"], separators=(",", ":")),
        "",
        "",
        "",
    ]


def test_digest_row_order_matches_daily_and_weekly_schemas() -> None:
    scored = _scored_item()
    daily = DailyDigest(digest_date="2026-05-22", items=(scored,), summary="Daily summary", sheet_row_id="d-1")
    weekly = WeeklyDigest(
        week_start="2026-05-18",
        week_end="2026-05-24",
        items=(scored,),
        summary="Weekly summary",
        sheet_row_id="w-1",
    )

    assert DAILY_DIGEST_COLUMNS == (
        "digest_date",
        "summary",
        "item_count",
        "top_titles_json",
        "top_links_json",
        "score_rationales_json",
        "items_json",
        "discord_status",
        "discord_error",
        "discord_sent_at",
        "sheet_row_id",
    )
    assert daily_digest_row(daily, discord_status="pending") == [
        "2026-05-22",
        "Daily summary",
        "1",
        json.dumps(["Hermes autonomous review"], separators=(",", ":")),
        json.dumps(["https://example.invalid/review"], separators=(",", ":")),
        json.dumps(["Official evidence with concrete AI-agent workflow impact."], separators=(",", ":")),
        daily.to_json(),
        "pending",
        "",
        "",
        "d-1",
    ]
    assert WEEKLY_DIGEST_COLUMNS[:3] == ("week_start", "week_end", "summary")
    assert weekly_digest_row(weekly, discord_status="sent")[:5] == [
        "2026-05-18",
        "2026-05-24",
        "Weekly summary",
        "1",
        json.dumps(["Hermes autonomous review"], separators=(",", ":")),
    ]


def test_append_read_and_update_helpers_use_injected_client_without_network() -> None:
    client = FakeSheetsClient()
    scored = _scored_item()
    daily = DailyDigest(digest_date="2026-05-22", items=(scored,), summary="Daily summary")
    weekly = WeeklyDigest(week_start="2026-05-18", week_end="2026-05-24", items=(scored,), summary="Weekly summary")
    client.values = [list(RAW_ITEMS_COLUMNS), raw_item_row(scored)]

    append_raw_items(client, (scored,), spreadsheet_id="sheet-id")
    append_collected_raw_items(client, (scored.raw_item,), spreadsheet_id="sheet-id")
    append_daily_digest(client, daily, spreadsheet_id="sheet-id")
    append_weekly_digest(client, weekly, spreadsheet_id="sheet-id")
    rows = read_sheet_rows(client, "raw_items", spreadsheet_id="sheet-id")
    update_discord_status(
        client,
        "daily_digest",
        row_number=2,
        status="failed",
        error="HTTP 500 from Discord",
        spreadsheet_id="sheet-id",
    )

    assert client.append_calls[0] == ("sheet-id", "raw_items!A:K", [raw_item_row(scored)])
    assert client.append_calls[1] == ("sheet-id", "raw_items!A:K", [collected_raw_item_row(scored.raw_item)])
    assert client.append_calls[2][1] == "daily_digest!A:K"
    assert client.append_calls[3][1] == "weekly_digest!A:L"
    assert rows == [dict(zip(RAW_ITEMS_COLUMNS, raw_item_row(scored), strict=True))]
    assert client.update_calls == [("sheet-id", "daily_digest!H2:J2", [["failed", "HTTP 500 from Discord", ""]])]


def test_default_spreadsheet_id_reads_only_scoped_env(monkeypatch) -> None:
    monkeypatch.setenv("AI_TRENDS_SPREADSHEET_ID", "env-sheet-id")
    monkeypatch.delenv("AI_TRENDS_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    client = FakeSheetsClient()

    append_raw_items(client, (_scored_item(),))

    assert client.append_calls[0][0] == "env-sheet-id"


def test_helpers_do_not_leak_secret_values_in_errors() -> None:
    client = FakeSheetsClient()

    try:
        read_sheet_rows(client, "unknown", spreadsheet_id="spreadsheet-secret-value")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert "spreadsheet-secret-value" not in message
    assert "unknown" in message
