from datetime import datetime, timezone

from ai_trends.collector import run_collection_workflow
from ai_trends.models import RawTrendItem
from ai_trends.sheets import RAW_ITEMS_COLUMNS


class RecordingSheetsClient:
    def __init__(self) -> None:
        self.values: list[list[str]] = [list(RAW_ITEMS_COLUMNS)]
        self.append_calls: list[tuple[str, str, list[list[str]]]] = []
        self.delete_calls: list[tuple[str, str, tuple[int, ...]]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.append_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return self.values

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        raise AssertionError("hourly collector must not update digest status")

    def delete_rows(self, spreadsheet_id: str, sheet_name: str, row_numbers: tuple[int, ...]) -> dict[str, object]:
        self.delete_calls.append((spreadsheet_id, sheet_name, row_numbers))
        return {"deletedRows": len(row_numbers)}


def _raw_item(
    *,
    source_name: str = "Official Feed",
    title: str = "Agent runtime release",
    url: str = "https://example.invalid/agent-runtime",
    published_at: datetime = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
) -> RawTrendItem:
    return RawTrendItem(
        source_name=source_name,
        source_type="blog",
        title=title,
        url=url,
        published_at=published_at,
        summary="Runtime release notes.",
        tags=("agents",),
        evidence_urls=(url,),
    )


def test_hourly_collection_appends_unscored_raw_rows_only() -> None:
    client = RecordingSheetsClient()

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=(_raw_item(),),
        now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert result.appended_count == 1
    assert client.append_calls[0][0:2] == ("sheet-id", "raw_items!A:K")
    row = client.append_calls[0][2][0]
    assert row[RAW_ITEMS_COLUMNS.index("title")] == "Agent runtime release"
    assert row[RAW_ITEMS_COLUMNS.index("relevance_score")] == ""
    assert row[RAW_ITEMS_COLUMNS.index("importance_score")] == ""
    assert row[RAW_ITEMS_COLUMNS.index("score_rationale")] == ""
    assert result.pruned_count == 0


def test_hourly_collection_skips_existing_items_without_append_call() -> None:
    existing = _raw_item(url="https://example.invalid/agent-runtime?utm_source=mail")
    client = RecordingSheetsClient()
    client.values.append([
        existing.source_name,
        existing.source_type,
        existing.title,
        existing.url,
        existing.published_at.isoformat(),
        existing.summary,
        "[]",
        "[]",
        "",
        "",
        "",
    ])

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=(_raw_item(url="https://example.invalid/agent-runtime"),),
        now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert result.new_count == 0
    assert result.appended_count == 0
    assert client.append_calls == []


def test_hourly_collection_deletes_raw_rows_older_than_retention_window() -> None:
    old_item = _raw_item(title="Old release", url="https://example.invalid/old", published_at=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc))
    current_item = _raw_item(title="Current release", url="https://example.invalid/current", published_at=datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc))
    client = RecordingSheetsClient()
    for item in (old_item, current_item):
        client.values.append([
            item.source_name,
            item.source_type,
            item.title,
            item.url,
            item.published_at.isoformat(),
            item.summary,
            "[]",
            "[]",
            "",
            "",
            "",
        ])

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=(),
        now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert result.pruned_count == 1
    assert client.delete_calls == [("sheet-id", "raw_items", (2,))]


def test_hourly_collection_does_not_append_new_items_outside_retention_window() -> None:
    client = RecordingSheetsClient()

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=(
            _raw_item(title="Expired release", url="https://example.invalid/expired", published_at=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)),
        ),
        now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
    )

    assert result.new_count == 0
    assert result.appended_count == 0
    assert client.append_calls == []


def test_hourly_collection_round_robins_sources_before_global_limit(monkeypatch) -> None:
    monkeypatch.setenv("AI_TRENDS_COLLECTION_ITEM_LIMIT", "2")
    client = RecordingSheetsClient()
    items = (
        _raw_item(source_name="OpenAI News", title="OpenAI backlog 1", url="https://example.invalid/openai-1"),
        _raw_item(source_name="OpenAI News", title="OpenAI backlog 2", url="https://example.invalid/openai-2"),
        _raw_item(source_name="Hugging Face Blog", title="HF current 1", url="https://example.invalid/hf-1"),
        _raw_item(source_name="Hugging Face Blog", title="HF current 2", url="https://example.invalid/hf-2"),
    )

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=items,
        now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
    )

    appended_titles = [row[RAW_ITEMS_COLUMNS.index("title")] for row in client.append_calls[0][2]]
    assert result.appended_count == 2
    assert appended_titles == ["OpenAI backlog 1", "HF current 1"]
