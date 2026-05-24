from datetime import datetime, timezone
import json

import pytest

from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem, WeeklyDigest


def test_raw_trend_item_validates_required_fields_and_evidence_urls() -> None:
    published_at = datetime(2026, 5, 22, 8, 30, tzinfo=timezone.utc)

    item = RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title="New agent release",
        url="https://example.invalid/release",
        published_at=published_at,
        summary="Release summary",
        tags=("coding-agent", "mcp"),
        evidence_urls=("https://example.invalid/evidence",),
    )

    assert item.title == "New agent release"
    assert item.tags == ("coding-agent", "mcp")
    assert item.evidence_urls == ("https://example.invalid/evidence",)

    with pytest.raises(ValueError, match="title"):
        RawTrendItem(
            source_name="Official Blog",
            source_type="blog",
            title=" ",
            url="https://example.invalid/release",
            published_at=published_at,
            summary="Release summary",
            tags=("coding-agent",),
            evidence_urls=(),
        )

    with pytest.raises(ValueError, match="evidence_urls"):
        RawTrendItem(
            source_name="Official Blog",
            source_type="blog",
            title="New agent release",
            url="https://example.invalid/release",
            published_at=published_at,
            summary="Release summary",
            tags=("coding-agent",),
            evidence_urls=("not-a-url",),
        )


def test_scored_item_validates_score_ranges() -> None:
    raw = RawTrendItem(
        source_name="GitHub",
        source_type="release",
        title="Automation release",
        url="https://example.invalid/release",
        published_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        summary="Release summary",
        tags=("github-automation",),
        evidence_urls=("https://example.invalid/release",),
    )

    scored = ScoredTrendItem(
        raw_item=raw,
        relevance_score=8,
        importance_score=7,
        rationale="Relevant to AI agents and automation.",
    )

    assert scored.relevance_score == 8

    with pytest.raises(ValueError, match="relevance_score"):
        ScoredTrendItem(raw_item=raw, relevance_score=11, importance_score=7, rationale="bad")

    with pytest.raises(ValueError, match="importance_score"):
        ScoredTrendItem(raw_item=raw, relevance_score=8, importance_score=0, rationale="bad")


def test_models_round_trip_through_json() -> None:
    raw = RawTrendItem(
        source_name="Paper",
        source_type="paper",
        title="Local-first AI agents",
        url="https://example.invalid/paper",
        published_at=datetime(2026, 5, 22, 1, 2, 3, tzinfo=timezone.utc),
        summary="Paper summary",
        tags=("local-first-ai",),
        evidence_urls=("https://example.invalid/paper",),
    )
    scored = ScoredTrendItem(
        raw_item=raw,
        relevance_score=9,
        importance_score=8,
        rationale="Strong relevance and evidence.",
    )
    daily = DailyDigest(
        digest_date="2026-05-22",
        items=(scored,),
        summary="Daily digest summary",
        sheet_row_id="daily-1",
    )
    weekly = WeeklyDigest(
        week_start="2026-05-18",
        week_end="2026-05-24",
        items=(scored,),
        summary="Weekly digest summary",
        sheet_row_id="weekly-1",
    )

    daily_payload = json.loads(daily.to_json())
    weekly_payload = json.loads(weekly.to_json())

    assert daily_payload["items"][0]["raw_item"]["published_at"] == "2026-05-22T01:02:03+00:00"
    assert weekly_payload["week_start"] == "2026-05-18"
    assert DailyDigest.from_json(daily.to_json()) == daily
    assert WeeklyDigest.from_json(weekly.to_json()) == weekly


def test_digest_requires_items_and_iso_dates() -> None:
    with pytest.raises(ValueError, match="items"):
        DailyDigest(digest_date="2026-05-22", items=(), summary="empty", sheet_row_id=None)

    raw = RawTrendItem(
        source_name="Docs",
        source_type="docs",
        title="Agent docs",
        url="https://example.invalid/docs",
        published_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        summary="Docs summary",
        tags=("ai-agent",),
        evidence_urls=("https://example.invalid/docs",),
    )
    scored = ScoredTrendItem(raw_item=raw, relevance_score=5, importance_score=6, rationale="Useful.")

    with pytest.raises(ValueError, match="digest_date"):
        DailyDigest(digest_date="05/22/2026", items=(scored,), summary="summary", sheet_row_id=None)

    with pytest.raises(ValueError, match="week_end"):
        WeeklyDigest(
            week_start="2026-05-18",
            week_end="not-a-date",
            items=(scored,),
            summary="summary",
            sheet_row_id=None,
        )
