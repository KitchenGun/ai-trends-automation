from datetime import datetime, timezone

from ai_trends.dedupe import dedupe_trend_items, normalize_title
from ai_trends.models import RawTrendItem


def _item(*, title: str, url: str, source_name: str = "Official Blog") -> RawTrendItem:
    return RawTrendItem(
        source_name=source_name,
        source_type="blog",
        title=title,
        url=url,
        published_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        summary="A public source summary.",
        tags=("ai-agent",),
        evidence_urls=(url,),
    )


def test_dedupe_removes_url_duplicate_before_title_matching() -> None:
    original = _item(title="Agent release", url="https://example.invalid/releases/1?utm_source=x")
    duplicate = _item(title="Completely different syndication headline", url="https://example.invalid/releases/1")

    result = dedupe_trend_items([original, duplicate])

    assert result == (original,)


def test_dedupe_removes_same_normalized_title_from_same_source() -> None:
    original = _item(title="Hermes Agent 2.0: New MCP Support!", url="https://example.invalid/a")
    duplicate = _item(title=" hermes agent 2 0 new mcp support ", url="https://example.invalid/b")

    result = dedupe_trend_items([original, duplicate])

    assert result == (original,)


def test_dedupe_keeps_same_title_from_different_sources_as_collision() -> None:
    blog = _item(title="Claude Code adds hooks", url="https://example.invalid/blog", source_name="Official Blog")
    github = _item(title="Claude Code adds hooks", url="https://github.com/example/project/releases/1", source_name="GitHub Releases")

    result = dedupe_trend_items([blog, github])

    assert result == (blog, github)


def test_dedupe_keeps_distinct_urls_when_title_collision_is_only_cross_source() -> None:
    paper = _item(title="AgentBench update", url="https://arxiv.org/abs/2605.00001", source_name="arXiv")
    docs = _item(title="AgentBench update", url="https://docs.example.invalid/agentbench", source_name="Docs")

    result = dedupe_trend_items([paper, docs])

    assert len(result) == 2
    assert {item.url for item in result} == {paper.url, docs.url}


def test_normalize_title_removes_case_punctuation_and_extra_space() -> None:
    assert normalize_title("  AI-Agent: MCP   Release!! ") == "ai agent mcp release"
