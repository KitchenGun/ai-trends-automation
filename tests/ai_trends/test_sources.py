from datetime import datetime, timezone
import json

from ai_trends.models import RawTrendItem
from ai_trends.sources import DEFAULT_TREND_SOURCES, SourceSpec, collect_trend_items, parse_github_releases, parse_rss_feed


def test_parse_rss_feed_maps_entries_to_raw_trend_items() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Example AI Blog</title>
      <item>
        <title>Agent runtime release</title>
        <link>https://example.invalid/blog/agent-runtime</link>
        <guid>https://example.invalid/blog/agent-runtime</guid>
        <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
        <description>Runtime release notes.</description>
        <category>agents</category>
      </item>
    </channel></rss>
    """

    items = parse_rss_feed(
        rss,
        source_name="Example AI Blog",
        source_type="blog",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert items == (
        RawTrendItem(
            source_name="Example AI Blog",
            source_type="blog",
            title="Agent runtime release",
            url="https://example.invalid/blog/agent-runtime",
            published_at=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
            summary="Runtime release notes.",
            tags=("agents",),
            evidence_urls=("https://example.invalid/blog/agent-runtime",),
        ),
    )


def test_parse_rss_feed_ignores_trailing_page_script() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Unreal AI assistant update</title>
        <link href="https://example.invalid/unreal-ai" />
        <updated>2026-05-22T12:00:00Z</updated>
        <summary>Editor AI assistant update.</summary>
      </entry>
    </feed><script>ignored()</script>
    """

    items = parse_rss_feed(
        feed,
        source_name="Unreal Engine News",
        source_type="blog",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert items[0].title == "Unreal AI assistant update"


def test_parse_github_releases_maps_public_api_payload_to_raw_items() -> None:
    payload = json.dumps(
        [
            {
                "name": "v1.2.3",
                "html_url": "https://github.com/acme/agent/releases/tag/v1.2.3",
                "published_at": "2026-05-22T11:00:00Z",
                "body": "Release body for agents.",
                "tag_name": "v1.2.3",
            }
        ]
    )

    items = parse_github_releases(payload, source_name="Acme Agent Releases")

    assert items[0].title == "v1.2.3"
    assert items[0].source_type == "github_release"
    assert items[0].tags == ("github-release", "v1.2.3")
    assert items[0].published_at == datetime(2026, 5, 22, 11, 0, tzinfo=timezone.utc)


def test_collect_trend_items_uses_mocked_public_sources_without_local_dependencies() -> None:
    responses = {
        "https://example.invalid/feed.xml": """<feed xmlns="http://www.w3.org/2005/Atom">
            <entry><title>Model context protocol news</title><link href="https://example.invalid/mcp" />
            <updated>2026-05-22T12:00:00Z</updated><summary>MCP summary.</summary></entry>
        </feed>""",
        "https://api.github.com/repos/acme/agent/releases": json.dumps(
            [
                {
                    "name": "Agent CLI v2",
                    "html_url": "https://github.com/acme/agent/releases/tag/v2",
                    "published_at": "2026-05-22T13:00:00Z",
                    "body": "CLI release notes.",
                    "tag_name": "v2",
                }
            ]
        ),
    }

    def fetcher(url: str, headers: dict[str, str]) -> str:
        assert "User-Agent" in headers
        return responses[url]

    items = collect_trend_items(
        sources=(
            SourceSpec(name="Official Feed", source_type="rss", url="https://example.invalid/feed.xml"),
            SourceSpec(name="GitHub", source_type="github_release", url="https://api.github.com/repos/acme/agent/releases"),
        ),
        fetcher=fetcher,
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert [item.title for item in items] == ["Model context protocol news", "Agent CLI v2"]


def test_default_trend_sources_include_agent_and_game_engine_feeds_without_known_broken_urls() -> None:
    urls = {source.url for source in DEFAULT_TREND_SOURCES}

    assert "https://api.github.com/repos/NousResearch/hermes-agent/releases" in urls
    assert "https://www.unrealengine.com/rss" in urls
    assert "https://blog.unity.com/games/feed" in urls
    assert "https://blog.unity.com/engine-platform/feed" in urls
    assert "https://unity.com/blog/games/rss.xml" not in urls
    assert "https://api.github.com/repos/Unity-Technologies/ml-agents/releases" in urls
    assert "https://www.anthropic.com/news/rss.xml" not in urls
    assert "https://mistral.ai/rss.xml" not in urls


def test_collect_trend_items_skips_failed_sources_and_keeps_working_sources() -> None:
    responses = {
        "https://example.invalid/feed.xml": """<rss version="2.0"><channel><item>
            <title>Agent runtime release</title>
            <link>https://example.invalid/agent-runtime</link>
            <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
            <description>Runtime release notes.</description>
        </item></channel></rss>""",
    }

    def fetcher(url: str, headers: dict[str, str]) -> str:
        if url == "https://example.invalid/broken.xml":
            raise OSError("broken source")
        return responses[url]

    items = collect_trend_items(
        sources=(
            SourceSpec(name="Broken", source_type="rss", url="https://example.invalid/broken.xml"),
            SourceSpec(name="Official Feed", source_type="rss", url="https://example.invalid/feed.xml"),
        ),
        fetcher=fetcher,
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert [item.title for item in items] == ["Agent runtime release"]


def test_collect_trend_items_adds_github_auth_header_when_token_is_available() -> None:
    seen_headers: list[dict[str, str]] = []

    def fetcher(url: str, headers: dict[str, str]) -> str:
        seen_headers.append(headers)
        return json.dumps(
            [
                {
                    "name": "Agent CLI v2",
                    "html_url": "https://github.com/acme/agent/releases/tag/v2",
                    "published_at": "2026-05-22T13:00:00Z",
                    "body": "CLI release notes.",
                    "tag_name": "v2",
                }
            ]
        )

    collect_trend_items(
        sources=(
            SourceSpec(
                name="GitHub",
                source_type="github_release",
                url="https://api.github.com/repos/acme/agent/releases",
            ),
        ),
        fetcher=fetcher,
        github_token="github-token-from-gh-cli",
    )

    assert seen_headers[0]["Authorization"] == "Bearer github-token-from-gh-cli"


def test_collect_trend_items_includes_x_only_when_bearer_token_is_supplied() -> None:
    called_urls: list[str] = []

    def fetcher(url: str, headers: dict[str, str]) -> str:
        called_urls.append(url)
        assert headers["Authorization"] == "Bearer token-123"
        return json.dumps(
            {
                "data": [
                    {
                        "id": "1",
                        "text": "Official docs mention a new AI agent release https://example.invalid/docs",
                        "created_at": "2026-05-22T14:00:00Z",
                    }
                ]
            }
        )

    without_x = collect_trend_items(sources=(), fetcher=fetcher, x_bearer_token=None)
    with_x = collect_trend_items(sources=(), fetcher=fetcher, x_bearer_token="token-123")

    assert without_x == ()
    assert len(with_x) == 1
    assert with_x[0].source_type == "x_weak_signal"
    assert called_urls == ["https://api.twitter.com/2/tweets/search/recent?query=AI%20agent%20release%20OR%20MCP%20OR%20LLM%20tooling&max_results=10&tweet.fields=created_at"]
