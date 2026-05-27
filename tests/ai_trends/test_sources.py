from datetime import datetime, timezone
import json

from ai_trends.models import RawTrendItem
from ai_trends.sources import (
    DEFAULT_TREND_SOURCES,
    SourceSpec,
    collect_trend_items,
    parse_github_releases,
    parse_rss_feed,
    parse_x_rss_feed,
    resolve_x_rss_feed_urls,
    parse_unitysquare_blog,
)


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


def test_parse_unitysquare_blog_maps_ajax_payload_to_raw_items() -> None:
    payload = json.dumps(
        {
            "status": "success",
            "data": {
                "list_html": """
                <div class="project_box">
                  <a href="/growwith/unityblog/webinarView?id=779">
                    <div class="text_box">
                      <div class="p_txt_wrap"><span class="date">2026.05.14</span></div>
                      <div class="p_name">Unity Vector update</div>
                      <div class="p_detail"><div>#Unity</div><div>#Vector</div></div>
                    </div>
                  </a>
                </div>
                """
            },
        }
    )

    items = parse_unitysquare_blog(
        payload,
        source_name="Unity Square Korea Blog",
        fetched_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    assert items == (
        RawTrendItem(
            source_name="Unity Square Korea Blog",
            source_type="official_site",
            title="Unity Vector update",
            url="https://unitysquare.co.kr/growwith/unityblog/webinarView?id=779",
            published_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
            summary="Unity Vector update Tags: Unity, Vector",
            tags=("Unity", "Vector"),
            evidence_urls=("https://unitysquare.co.kr/growwith/unityblog/webinarView?id=779",),
        ),
    )


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
    assert "https://unitysquare.co.kr/growwith/unityblog/unityWebinarList?page=1&search_sort=desc" in urls
    assert "https://blog.unity.com/games/feed" not in urls
    assert "https://blog.unity.com/engine-platform/feed" not in urls
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


def test_collect_trend_items_includes_x_only_when_bearer_token_is_supplied(monkeypatch) -> None:
    monkeypatch.delenv("AI_TRENDS_X_RSS_FEEDS_JSON", raising=False)
    monkeypatch.delenv("AI_TRENDS_X_RSS_FEEDS_FILE", raising=False)
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


def test_parse_x_rss_feed_maps_agent_related_posts_to_weak_signal() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Alice on X</title>
      <item>
        <title>@alice: New MCP agent runtime shipped</title>
        <link>https://x.com/alice/status/123</link>
        <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
        <description>New MCP agent runtime shipped with tool calling support.</description>
        <dc:creator>@alice</dc:creator>
      </item>
    </channel></rss>
    """

    items = parse_x_rss_feed(
        rss,
        feed_url="https://rss.example.invalid/alice.xml",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert items == (
        RawTrendItem(
            source_name="X RSS",
            source_type="x_rss_signal",
            title="@alice: New MCP agent runtime shipped",
            url="https://x.com/alice/status/123",
            published_at=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc),
            summary="@alice: New MCP agent runtime shipped with tool calling support.",
            tags=("x-rss-signal", "x-author:@alice"),
            evidence_urls=("https://x.com/alice/status/123",),
        ),
    )


def test_parse_x_rss_feed_filters_low_relevance_chatter() -> None:
    rss = """<rss version="2.0"><channel><item>
        <title>@alice: Lunch notes</title>
        <link>https://x.com/alice/status/124</link>
        <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
        <description>Lunch was nice.</description>
    </item></channel></rss>"""

    assert parse_x_rss_feed(
        rss,
        feed_url="https://rss.example.invalid/alice.xml",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    ) == ()


def test_collect_trend_items_adds_x_rss_feeds_and_skips_failed_feeds() -> None:
    responses = {
        "https://rss.example.invalid/alice.xml": """<rss version="2.0"><channel><item>
            <title>@alice: Agentic workflow automation update</title>
            <link>https://x.com/alice/status/125</link>
            <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
            <description>Agentic workflow automation update for builders.</description>
        </item></channel></rss>""",
    }

    def fetcher(url: str, _headers: dict[str, str]) -> str:
        if url == "https://rss.example.invalid/broken.xml":
            raise TimeoutError("feed timed out")
        return responses[url]

    items = collect_trend_items(
        sources=(),
        fetcher=fetcher,
        now=datetime(2026, 5, 22, tzinfo=timezone.utc),
        x_rss_feed_urls=(
            "https://rss.example.invalid/broken.xml",
            "https://rss.example.invalid/alice.xml",
        ),
    )

    assert len(items) == 1
    assert items[0].source_type == "x_rss_signal"
    assert "x-rss-signal" in items[0].tags


def test_resolve_x_rss_feed_urls_accepts_json_and_file(tmp_path, monkeypatch) -> None:
    feed_file = tmp_path / "feeds.json"
    feed_file.write_text(json.dumps({"feeds": ["https://rss.example.invalid/bob.xml"]}))
    monkeypatch.setenv("AI_TRENDS_X_RSS_FEEDS_JSON", json.dumps(["https://rss.example.invalid/alice.xml", "not-a-url"]))
    monkeypatch.setenv("AI_TRENDS_X_RSS_FEEDS_FILE", str(feed_file))

    assert resolve_x_rss_feed_urls() == (
        "https://rss.example.invalid/alice.xml",
        "https://rss.example.invalid/bob.xml",
    )


def test_fetch_text_uses_configurable_timeout(monkeypatch) -> None:
    from io import BytesIO
    from ai_trends import sources as sources_module

    seen: list[int] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b"ok"

    def fake_urlopen(_request, *, timeout: int):
        seen.append(timeout)
        return Response()

    monkeypatch.setenv("AI_TRENDS_SOURCE_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(sources_module, "urlopen", fake_urlopen)

    assert sources_module._fetch_text("https://example.invalid/feed.xml", {}) == "ok"
    assert seen == [3]

def test_parse_x_rss_feed_keeps_hermes_agent_posts() -> None:
    rss = """<rss version="2.0"><channel><item>
        <title>Nous Research ships Hermes Agent self-evolution</title>
        <link>https://nitter.net/NousResearch/status/2050000000000000000#m</link>
        <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
        <description>Hermes Agent can now improve skills from prior runs.</description>
        <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">@NousResearch</dc:creator>
    </item></channel></rss>"""

    items = parse_x_rss_feed(
        rss,
        feed_url="https://nitter.net/NousResearch/rss",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].source_type == "x_rss_signal"
    assert "x-author:@NousResearch" in items[0].tags

def test_parse_x_rss_feed_falls_back_to_title_when_description_cleans_empty() -> None:
    rss = """<rss version="2.0"><channel><item>
        <title>Hermes Agent release notes</title>
        <link>https://nitter.net/NousResearch/status/2050000000000000001#m</link>
        <pubDate>Fri, 22 May 2026 10:00:00 GMT</pubDate>
        <description><![CDATA[<p></p>]]></description>
        <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">@NousResearch</dc:creator>
    </item></channel></rss>"""

    items = parse_x_rss_feed(
        rss,
        feed_url="https://nitter.net/NousResearch/rss",
        fetched_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].summary == "@NousResearch: Hermes Agent release notes"

