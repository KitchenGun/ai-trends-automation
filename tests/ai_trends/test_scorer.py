from datetime import datetime, timedelta, timezone
import json
import subprocess

from ai_trends.sheets import RAW_ITEMS_COLUMNS, collected_raw_item_row
from ai_trends.models import RawTrendItem
from ai_trends.scorer import (
    AGENT_SCORE_RATIONALE_PREFIX,
    ScoringResult,
    run_scoring_workflow,
    select_rows_for_scoring,
)


class RecordingSheetsClient:
    def __init__(self) -> None:
        self.values: list[list[str]] = []
        self.update_calls: list[tuple[str, str, list[list[str]]]] = []

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        raise AssertionError("scoring job must not append rows")

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return self.values

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        self.update_calls.append((spreadsheet_id, range_name, values))
        return {"updatedRows": len(values)}


def _raw_item(title: str, published_at: datetime) -> RawTrendItem:
    slug = title.lower().replace(" ", "-")
    return RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title=title,
        url=f"https://example.invalid/{slug}",
        published_at=published_at,
        summary=f"{title} summary for AI agent builders.",
        tags=("ai-agent",),
        evidence_urls=(f"https://example.invalid/{slug}",),
    )


def _row(
    title: str,
    published_at: datetime,
    *,
    relevance_score: str = "",
    importance_score: str = "",
    score_rationale: str = "",
) -> list[str]:
    row = collected_raw_item_row(_raw_item(title, published_at))
    row[RAW_ITEMS_COLUMNS.index("relevance_score")] = relevance_score
    row[RAW_ITEMS_COLUMNS.index("importance_score")] = importance_score
    row[RAW_ITEMS_COLUMNS.index("score_rationale")] = score_rationale
    return row


def test_selects_only_recent_rows_without_trusted_agent_score() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    rows = [
        (2, dict(zip(RAW_ITEMS_COLUMNS, _row("Blank recent", now - timedelta(days=1)), strict=True))),
        (
            3,
            dict(
                zip(
                    RAW_ITEMS_COLUMNS,
                    _row(
                        "Already agent scored",
                        now - timedelta(days=2),
                        relevance_score="8",
                        importance_score="7",
                        score_rationale="Hermes agent: trusted score",
                    ),
                    strict=True,
                )
            ),
        ),
        (
            4,
            dict(
                zip(
                    RAW_ITEMS_COLUMNS,
                    _row(
                        "Untrusted existing score",
                        now - timedelta(days=3),
                        relevance_score="1",
                        importance_score="1",
                        score_rationale="keyword match",
                    ),
                    strict=True,
                )
            ),
        ),
        (5, dict(zip(RAW_ITEMS_COLUMNS, _row("Too old", now - timedelta(days=8)), strict=True))),
    ]

    selected = select_rows_for_scoring(rows, now=now, retention_days=7, limit=5)

    assert [(row_number, item.title) for row_number, item in selected] == [
        (2, "Blank recent"),
        (4, "Untrusted existing score"),
    ]


def test_select_respects_limit() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    rows = [
        (row_number, dict(zip(RAW_ITEMS_COLUMNS, _row(f"Item {row_number}", now - timedelta(hours=row_number)), strict=True)))
        for row_number in range(2, 6)
    ]

    selected = select_rows_for_scoring(rows, now=now, retention_days=7, limit=2)

    assert [row_number for row_number, _ in selected] == [2, 3]


def test_run_scoring_updates_raw_item_score_columns_with_agent_prefix() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    sheets = RecordingSheetsClient()
    sheets.values = [list(RAW_ITEMS_COLUMNS), _row("Blank recent", now - timedelta(days=1))]

    result = run_scoring_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        now=now,
        item_limit=5,
        retention_days=7,
        hermes_requester=lambda _prompt: json.dumps(
            {"relevance_score": 9, "importance_score": 8, "rationale": "official evidence and concrete impact"}
        ),
    )

    assert result == ScoringResult(targeted=1, succeeded=1, failed=0, skipped=0)
    assert sheets.update_calls == [
        (
            "sheet-id",
            "raw_items!I2:K2",
            [["9", "8", f"{AGENT_SCORE_RATIONALE_PREFIX}official evidence and concrete impact"]],
        )
    ]


def test_run_scoring_marks_timeout_error_with_fallback_score() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    sheets = RecordingSheetsClient()
    sheets.values = [list(RAW_ITEMS_COLUMNS), _row("Blank recent", now - timedelta(days=1))]

    def failing_requester(_prompt: str) -> str:
        raise TimeoutError("Hermes timed out")

    result = run_scoring_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        now=now,
        item_limit=5,
        retention_days=7,
        hermes_requester=failing_requester,
    )

    assert result == ScoringResult(targeted=1, succeeded=1, failed=0, skipped=0)
    assert sheets.update_calls[0][0:2] == ("sheet-id", "raw_items!I2:K2")
    assert sheets.update_calls[0][2][0][2].startswith("Hermes agent: Fallback(")


def test_run_scoring_skips_agent_prefixed_rows_and_retries_unprefixed_existing_scores() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    sheets = RecordingSheetsClient()
    sheets.values = [
        list(RAW_ITEMS_COLUMNS),
        _row("Trusted", now - timedelta(days=1), relevance_score="9", importance_score="8", score_rationale="Hermes agent: done"),
        _row("Untrusted", now - timedelta(days=1), relevance_score="1", importance_score="1", score_rationale="keyword match"),
    ]

    result = run_scoring_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        now=now,
        item_limit=5,
        retention_days=7,
        hermes_requester=lambda _prompt: '{"relevance_score":7,"importance_score":6,"rationale":"agent reviewed"}',
    )

    assert result == ScoringResult(targeted=1, succeeded=1, failed=0, skipped=1)
    assert sheets.update_calls == [("sheet-id", "raw_items!I3:K3", [["7", "6", "Hermes agent: agent reviewed"]])]


def test_run_scoring_marks_subprocess_timeout_with_fallback_score() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    sheets = RecordingSheetsClient()
    sheets.values = [list(RAW_ITEMS_COLUMNS), _row("Blank recent", now - timedelta(days=1))]

    def timeout_requester(_prompt: str) -> str:
        raise subprocess.TimeoutExpired(cmd=["hermes"], timeout=1)

    result = run_scoring_workflow(
        sheets,
        spreadsheet_id="sheet-id",
        now=now,
        item_limit=5,
        retention_days=7,
        hermes_requester=timeout_requester,
    )

    assert result == ScoringResult(targeted=1, succeeded=1, failed=0, skipped=0)
    assert sheets.update_calls[0][0:2] == ("sheet-id", "raw_items!I2:K2")
    assert sheets.update_calls[0][2][0][0].isdigit()
    assert sheets.update_calls[0][2][0][2].startswith("Hermes agent: Fallback(hermes_cli_timeout)")
