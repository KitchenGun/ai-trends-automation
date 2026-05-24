from datetime import datetime, timezone

from ai_trends.collector import run_collection_workflow
from ai_trends.models import RawTrendItem
from ai_trends.sheets import RAW_ITEMS_COLUMNS


class RecordingSheetsClient:
    def __init__(self) -> None:
        self.values: list[list[str]] = [list(RAW_ITEMS_COLUMNS)]
        self.append_calls: list[tuple[str, str, list[list[str]]]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.append_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return self.values

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        raise AssertionError("hourly collector must not update digest status")


def _raw_item() -> RawTrendItem:
    return RawTrendItem(
        source_name="Official Feed",
        source_type="blog",
        title="Agent runtime release",
        url="https://example.invalid/agent-runtime",
        published_at=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
        summary="Runtime release notes.",
        tags=("agents",),
        evidence_urls=("https://example.invalid/agent-runtime",),
    )


def test_hourly_collection_appends_unscored_raw_rows_only() -> None:
    client = RecordingSheetsClient()

    result = run_collection_workflow(
        client,
        sources=(),
        spreadsheet_id="sheet-id",
        collected_items=(_raw_item(),),
    )

    assert result.appended_count == 1
    assert client.append_calls[0][0:2] == ("sheet-id", "raw_items!A:K")
    row = client.append_calls[0][2][0]
    assert row[RAW_ITEMS_COLUMNS.index("title")] == "Agent runtime release"
    assert row[RAW_ITEMS_COLUMNS.index("relevance_score")] == ""
    assert row[RAW_ITEMS_COLUMNS.index("importance_score")] == ""
    assert row[RAW_ITEMS_COLUMNS.index("score_rationale")] == ""
