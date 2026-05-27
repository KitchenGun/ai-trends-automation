"""Public-source collection for AI trend candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import os
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Sequence
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from ai_trends.models import RawTrendItem

FetchText = Callable[[str, dict[str, str]], str]

DEFAULT_USER_AGENT = "HermesAITrendsBot/1.0 (+https://hermes-agent.nousresearch.com)"
X_RECENT_SEARCH_URL = (
    "https://api.twitter.com/2/tweets/search/recent?"
    "query=AI%20agent%20release%20OR%20MCP%20OR%20LLM%20tooling&"
    "max_results=10&tweet.fields=created_at"
)
X_RSS_FEEDS_JSON_ENV = "AI_TRENDS_X_RSS_FEEDS_JSON"
X_RSS_FEEDS_FILE_ENV = "AI_TRENDS_X_RSS_FEEDS_FILE"
X_RSS_SOURCE_NAME = "X RSS"
X_RSS_SIGNAL_TAG = "x-rss-signal"
X_RSS_AGENT_SIGNAL_TERMS = (
    "ai agent",
    "ai agents",
    "agentic",
    "autonomous agent",
    "coding agent",
    "mcp",
    "model context protocol",
    "tool use",
    "tool-use",
    "tool calling",
    "function calling",
    "openai agents",
    "agents sdk",
    "computer use",
    "workflow automation",
    "developer tool",
    "developer tools",
    "langgraph",
    "llamaindex",
    "crewai",
    "autogen",
    "copilot",
    "hermes",
    "hermes agent",
    "hermes-agent",
    "hermesagent",
    "nous research",
    "nousresearch",
    "nous portal",
    "openclaw",
)
_URL_RE = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class SourceSpec:
    """A public endpoint to collect trend candidates from."""

    name: str
    source_type: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must be non-blank")
        if self.source_type not in {"rss", "atom", "github_release", "unitysquare_blog"}:
            raise ValueError("source_type must be rss, atom, github_release, or unitysquare_blog")
        if not self.url.strip().startswith(("http://", "https://")):
            raise ValueError("url must be an absolute http(s) URL")


DEFAULT_TREND_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(name="OpenAI News", source_type="rss", url="https://openai.com/news/rss.xml"),
    SourceSpec(name="Google AI Blog", source_type="rss", url="https://blog.google/technology/ai/rss/"),
    SourceSpec(name="Hugging Face Blog", source_type="rss", url="https://huggingface.co/blog/feed.xml"),
    SourceSpec(name="Microsoft AI Blog", source_type="rss", url="https://blogs.microsoft.com/ai/feed/"),
    SourceSpec(name="NVIDIA Generative AI Blog", source_type="rss", url="https://developer.nvidia.com/blog/category/generative-ai/feed/"),
    SourceSpec(name="Unreal Engine Official Feed", source_type="atom", url="https://www.unrealengine.com/rss"),
    SourceSpec(
        name="Unity Square Korea Blog",
        source_type="unitysquare_blog",
        url="https://unitysquare.co.kr/growwith/unityblog/unityWebinarList?page=1&search_sort=desc",
    ),
    SourceSpec(name="Hermes Agent Releases", source_type="github_release", url="https://api.github.com/repos/NousResearch/hermes-agent/releases"),
    SourceSpec(name="OpenAI Agents SDK Releases", source_type="github_release", url="https://api.github.com/repos/openai/openai-agents-python/releases"),
    SourceSpec(name="LangChain Releases", source_type="github_release", url="https://api.github.com/repos/langchain-ai/langchain/releases"),
    SourceSpec(name="LlamaIndex Releases", source_type="github_release", url="https://api.github.com/repos/run-llama/llama_index/releases"),
    SourceSpec(name="Vercel AI SDK Releases", source_type="github_release", url="https://api.github.com/repos/vercel/ai/releases"),
    SourceSpec(name="MCP TypeScript SDK Releases", source_type="github_release", url="https://api.github.com/repos/modelcontextprotocol/typescript-sdk/releases"),
    SourceSpec(name="MCP Python SDK Releases", source_type="github_release", url="https://api.github.com/repos/modelcontextprotocol/python-sdk/releases"),
    SourceSpec(name="Microsoft AutoGen Releases", source_type="github_release", url="https://api.github.com/repos/microsoft/autogen/releases"),
    SourceSpec(name="CrewAI Releases", source_type="github_release", url="https://api.github.com/repos/crewAIInc/crewAI/releases"),
    SourceSpec(name="Unity ML-Agents Releases", source_type="github_release", url="https://api.github.com/repos/Unity-Technologies/ml-agents/releases"),
)


def collect_trend_items(
    *,
    sources: tuple[SourceSpec, ...] | list[SourceSpec],
    fetcher: FetchText | None = None,
    now: datetime | None = None,
    x_bearer_token: str | None = None,
    github_token: str | None = None,
    x_rss_feed_urls: Sequence[str] | None = None,
    x_rss_feeds_json: str | None = None,
    x_rss_feeds_file: str | None = None,
) -> tuple[RawTrendItem, ...]:
    """Collect trend candidates from approved public endpoints.

    X is collected only when an explicit bearer token or public RSS feed list is
    supplied and is marked as a weak signal rather than primary evidence.
    """

    active_fetcher = fetcher or _fetch_text
    fetched_at = _ensure_aware_utc(now or datetime.now(timezone.utc))
    items: list[RawTrendItem] = []

    for source in sources:
        headers = {"User-Agent": DEFAULT_USER_AGENT, **dict(source.headers)}
        if source.source_type == "github_release" and github_token is not None and github_token.strip():
            headers.setdefault("Authorization", f"Bearer {github_token.strip()}")
        try:
            payload = active_fetcher(source.url, headers)
            if source.source_type in {"rss", "atom"}:
                items.extend(
                    parse_rss_feed(
                        payload,
                        source_name=source.name,
                        source_type="blog" if source.source_type == "rss" else "atom",
                        fetched_at=fetched_at,
                    )
                )
            elif source.source_type == "github_release":
                items.extend(parse_github_releases(payload, source_name=source.name))
            elif source.source_type == "unitysquare_blog":
                items.extend(parse_unitysquare_blog(payload, source_name=source.name, fetched_at=fetched_at))
        except Exception:
            continue

    resolved_x_rss_feed_urls = resolve_x_rss_feed_urls(
        feed_urls=x_rss_feed_urls,
        feeds_json=x_rss_feeds_json,
        feeds_file=x_rss_feeds_file,
    )
    if resolved_x_rss_feed_urls:
        items.extend(_collect_x_rss_signals(fetcher or _fetch_x_rss_text, resolved_x_rss_feed_urls, fetched_at))

    if x_bearer_token is not None and x_bearer_token.strip():
        items.extend(_collect_x_weak_signals(active_fetcher, x_bearer_token.strip(), fetched_at))

    return tuple(items)


def parse_rss_feed(
    payload: str,
    *,
    source_name: str,
    source_type: str,
    fetched_at: datetime,
) -> tuple[RawTrendItem, ...]:
    """Parse RSS or Atom XML into normalized raw trend items."""

    root = _parse_xml_payload(payload)
    items = _rss_items(root) or _atom_entries(root)
    parsed_items: list[RawTrendItem] = []
    for element in items:
        item = _parse_feed_element(element, source_name, source_type, fetched_at)
        if item is not None:
            parsed_items.append(item)
    return tuple(parsed_items)


def parse_github_releases(payload: str, *, source_name: str) -> tuple[RawTrendItem, ...]:
    """Parse GitHub releases API JSON into raw trend items."""

    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("GitHub releases payload must be a JSON list")

    items: list[RawTrendItem] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        title = _string_field(entry, "name") or _string_field(entry, "tag_name")
        url = _string_field(entry, "html_url")
        published_at = _string_field(entry, "published_at")
        body = _string_field(entry, "body")
        tag_name = _string_field(entry, "tag_name")
        if title is None or url is None or published_at is None:
            continue
        summary = body or title
        tags = ("github-release", tag_name) if tag_name is not None else ("github-release",)
        items.append(
            RawTrendItem(
                source_name=source_name,
                source_type="github_release",
                title=title,
                url=url,
                published_at=_parse_datetime(published_at),
                summary=_clean_summary(summary),
                tags=tags,
                evidence_urls=(url,),
            )
        )
    return tuple(items)


def parse_unitysquare_blog(
    payload: str,
    *,
    source_name: str,
    fetched_at: datetime,
) -> tuple[RawTrendItem, ...]:
    """Parse UnitySquare Korea blog list JSON into normalized raw trend items."""

    data = json.loads(payload)
    body = data.get("data") if isinstance(data, Mapping) else None
    list_html = body.get("list_html") if isinstance(body, Mapping) else None
    if not isinstance(list_html, str):
        raise ValueError("UnitySquare payload must include data.list_html")

    items: list[RawTrendItem] = []
    for match in re.finditer(r"<a\s+href=\"(?P<href>[^\"]+)\">(?P<body>.*?)</a>", list_html, re.DOTALL):
        block = match.group("body")
        title = _html_fragment_text(_first_match(r"<div class=\"p_name\">(?P<value>.*?)</div>", block))
        date_text = _html_fragment_text(_first_match(r"<span class=\"date\">(?P<value>.*?)</span>", block))
        href = html.unescape(match.group("href")).strip()
        if title is None or not href:
            continue
        url = urljoin("https://unitysquare.co.kr", href)
        tags = _unitysquare_tags(block)
        summary = title if not tags else f"{title} Tags: {', '.join(tags)}"
        items.append(
            RawTrendItem(
                source_name=source_name,
                source_type="official_site",
                title=title,
                url=url,
                published_at=_parse_unitysquare_date(date_text, fetched_at),
                summary=summary,
                tags=tags,
                evidence_urls=(url,),
            )
        )
    return tuple(items)


def resolve_x_rss_feed_urls(
    *,
    feed_urls: Sequence[str] | None = None,
    feeds_json: str | None = None,
    feeds_file: str | None = None,
) -> tuple[str, ...]:
    """Resolve configured X RSS feed URLs from explicit values or environment."""

    candidates: list[str] = []
    if feed_urls is not None:
        candidates.extend(feed_urls)

    raw_json = feeds_json if feeds_json is not None else os.environ.get(X_RSS_FEEDS_JSON_ENV)
    if raw_json is not None and raw_json.strip():
        try:
            candidates.extend(_feed_urls_from_json(raw_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    raw_file = feeds_file if feeds_file is not None else os.environ.get(X_RSS_FEEDS_FILE_ENV)
    if raw_file is not None and raw_file.strip():
        try:
            candidates.extend(_feed_urls_from_json(Path(raw_file).read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    return _dedupe_feed_urls(candidates)


def parse_x_rss_feed(
    payload: str,
    *,
    feed_url: str,
    fetched_at: datetime,
) -> tuple[RawTrendItem, ...]:
    """Parse a public X RSS/Atom feed into weak-signal raw trend items."""

    root = _parse_xml_payload(payload)
    elements = _rss_items(root) or _atom_entries(root)
    parsed_items: list[RawTrendItem] = []
    for element in elements:
        base_item = _parse_feed_element(element, X_RSS_SOURCE_NAME, "x_rss_signal", fetched_at)
        if base_item is None:
            continue
        author = _feed_author(element) or _handle_from_url(base_item.url) or _handle_from_text(base_item.title)
        summary = _x_rss_summary(base_item.summary, author)
        haystack = " ".join((base_item.title, summary, " ".join(base_item.tags), author or ""))
        if not _is_agent_related_x_signal(haystack):
            continue
        tags = _x_rss_tags(base_item.tags, author)
        parsed_items.append(
            RawTrendItem(
                source_name=X_RSS_SOURCE_NAME,
                source_type="x_rss_signal",
                title=base_item.title,
                url=base_item.url,
                published_at=base_item.published_at,
                summary=summary,
                tags=tags,
                evidence_urls=(base_item.url or feed_url,),
            )
        )
    return tuple(parsed_items)


def _collect_x_rss_signals(
    fetcher: FetchText,
    feed_urls: Sequence[str],
    fetched_at: datetime,
) -> tuple[RawTrendItem, ...]:
    deadline = time.monotonic() + _x_rss_total_budget_seconds()
    items: list[RawTrendItem] = []
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    for feed_url in tuple(feed_urls)[: _x_rss_feed_limit()]:
        if time.monotonic() >= deadline:
            break
        try:
            payload = fetcher(feed_url, headers)
            items.extend(parse_x_rss_feed(payload, feed_url=feed_url, fetched_at=fetched_at))
        except Exception:
            continue
    return tuple(items)


def _feed_urls_from_json(payload: str) -> tuple[str, ...]:
    data = json.loads(payload)
    if isinstance(data, list):
        return tuple(value for value in data if isinstance(value, str))
    if isinstance(data, Mapping):
        for key in ("feeds", "feed_urls", "urls", "x_rss_feeds"):
            values = data.get(key)
            if isinstance(values, list):
                return tuple(value for value in values if isinstance(value, str))
    raise ValueError("X RSS feeds must be a JSON list or an object with a feed list")


def _dedupe_feed_urls(feed_urls: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for feed_url in feed_urls:
        cleaned = feed_url.strip()
        if not _is_absolute_http_url(cleaned) or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return tuple(out)


def _is_absolute_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_agent_related_x_signal(value: str) -> bool:
    haystack = value.casefold()
    return any(term in haystack for term in X_RSS_AGENT_SIGNAL_TERMS)


def _x_rss_summary(summary: str, author: str | None) -> str:
    cleaned = _clean_summary(summary)
    if author is None or author.casefold() in cleaned.casefold():
        return cleaned
    return f"{author}: {cleaned}"


def _x_rss_tags(tags: tuple[str, ...], author: str | None) -> tuple[str, ...]:
    values = [X_RSS_SIGNAL_TAG]
    values.extend(tag for tag in tags if tag != X_RSS_SIGNAL_TAG)
    if author is not None:
        values.append(f"x-author:{author}")
    return tuple(dict.fromkeys(value for value in values if value.strip()))


def _feed_author(element: ET.Element) -> str | None:
    for descendant in element.iter():
        if descendant is element:
            continue
        if _local_name(descendant.tag) not in {"author", "creator", "name"}:
            continue
        if descendant.text is None:
            continue
        cleaned = _clean_summary(descendant.text)
        if cleaned:
            return _normalize_handle(cleaned)
    return None


def _handle_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if not (host.endswith("twitter.com") or host.endswith("x.com") or "nitter" in host):
        return None
    segment = parsed.path.strip("/").split("/", 1)[0]
    if not segment or segment in {"i", "search", "share"}:
        return None
    return _normalize_handle(segment)


def _handle_from_text(value: str) -> str | None:
    at_match = re.search(r"@[A-Za-z0-9_]{1,15}", value)
    if at_match is not None:
        return _normalize_handle(at_match.group(0))
    prefix_match = re.match(r"(?P<handle>[A-Za-z0-9_]{1,15})\s*:", value)
    if prefix_match is not None:
        return _normalize_handle(prefix_match.group("handle"))
    return None


def _normalize_handle(value: str) -> str:
    cleaned = value.strip().split()[0].lstrip("@")
    return f"@{cleaned}" if cleaned else "@unknown"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _collect_x_weak_signals(
    fetcher: FetchText,
    bearer_token: str,
    fetched_at: datetime,
) -> tuple[RawTrendItem, ...]:
    payload = fetcher(
        X_RECENT_SEARCH_URL,
        {"User-Agent": DEFAULT_USER_AGENT, "Authorization": f"Bearer {bearer_token}"},
    )
    data = json.loads(payload)
    records = data.get("data") if isinstance(data, Mapping) else None
    if not isinstance(records, list):
        return ()

    items: list[RawTrendItem] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        text = _string_field(record, "text")
        tweet_id = _string_field(record, "id")
        if text is None or tweet_id is None:
            continue
        evidence_url = _first_url(text) or f"https://twitter.com/i/web/status/{quote(tweet_id)}"
        created_at = _string_field(record, "created_at")
        items.append(
            RawTrendItem(
                source_name="X Recent Search",
                source_type="x_weak_signal",
                title=_clean_summary(text)[:120],
                url=evidence_url,
                published_at=_parse_datetime(created_at) if created_at is not None else fetched_at,
                summary=_clean_summary(text),
                tags=("x-weak-signal",),
                evidence_urls=(evidence_url,),
            )
        )
    return tuple(items)


def _fetch_text(url: str, headers: dict[str, str]) -> str:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=_source_timeout_seconds()) as response:  # noqa: S310 - caller supplies public endpoints.
        return response.read().decode("utf-8")


def _fetch_x_rss_text(url: str, headers: dict[str, str]) -> str:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=_x_rss_feed_timeout_seconds()) as response:  # noqa: S310 - caller supplies configured public RSS endpoints.
        return response.read().decode("utf-8")


def _source_timeout_seconds() -> int:
    raw_value = os.environ.get("AI_TRENDS_SOURCE_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return 8
    try:
        return max(2, min(30, int(raw_value)))
    except ValueError:
        return 8


def _x_rss_feed_timeout_seconds() -> int:
    raw_value = os.environ.get("AI_TRENDS_X_RSS_FEED_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return 8
    try:
        return max(1, min(8, int(raw_value)))
    except ValueError:
        return 8


def _x_rss_total_budget_seconds() -> float:
    raw_value = os.environ.get("AI_TRENDS_X_RSS_TOTAL_BUDGET_SECONDS", "").strip()
    if not raw_value:
        return 40.0
    try:
        return max(1.0, min(120.0, float(raw_value)))
    except ValueError:
        return 40.0


def _x_rss_feed_limit() -> int:
    raw_value = os.environ.get("AI_TRENDS_X_RSS_FEED_LIMIT", "").strip()
    if not raw_value:
        return 20
    try:
        return max(1, min(100, int(raw_value)))
    except ValueError:
        return 20


def _parse_xml_payload(payload: str) -> ET.Element:
    trimmed = _trim_after_closing_root(payload)
    try:
        return ET.fromstring(trimmed)
    except ET.ParseError:
        escaped = re.sub(
            r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)",
            "&amp;",
            trimmed,
        )
        return ET.fromstring(escaped)


def _trim_after_closing_root(payload: str) -> str:
    lower_payload = payload.lower()
    for closing_tag in ("</rss>", "</feed>"):
        index = lower_payload.find(closing_tag)
        if index >= 0:
            return payload[: index + len(closing_tag)]
    return payload


def _rss_items(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//channel/item")


def _atom_entries(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//{http://www.w3.org/2005/Atom}entry") + root.findall(".//entry")


def _parse_feed_element(
    element: ET.Element,
    source_name: str,
    source_type: str,
    fetched_at: datetime,
) -> RawTrendItem | None:
    title = _child_text(element, "title")
    url = _feed_url(element)
    summary = _child_text(element, "description") or _child_text(element, "summary") or title
    published_text = _child_text(element, "pubDate") or _child_text(element, "published") or _child_text(element, "updated")
    if title is None or url is None or summary is None:
        return None
    published_at = _parse_datetime(published_text) if published_text is not None else fetched_at
    cleaned_title = _clean_summary(title)
    cleaned_summary = _clean_summary(summary) or cleaned_title
    return RawTrendItem(
        source_name=source_name,
        source_type=source_type,
        title=cleaned_title,
        url=url,
        published_at=published_at,
        summary=cleaned_summary,
        tags=tuple(_feed_categories(element)),
        evidence_urls=(url,),
    )


def _child_text(element: ET.Element, local_name: str) -> str | None:
    child = element.find(local_name)
    if child is None:
        child = element.find(f"{{http://www.w3.org/2005/Atom}}{local_name}")
    if child is None or child.text is None:
        return None
    cleaned = child.text.strip()
    return cleaned or None


def _feed_url(element: ET.Element) -> str | None:
    link_text = _child_text(element, "link")
    if link_text is not None:
        return link_text
    link = element.find("{http://www.w3.org/2005/Atom}link")
    if link is None:
        link = element.find("link")
    if link is None:
        return None
    href = link.attrib.get("href")
    return href.strip() if href is not None and href.strip() else None


def _feed_categories(element: ET.Element) -> list[str]:
    tags: list[str] = []
    for category in element.findall("category") + element.findall("{http://www.w3.org/2005/Atom}category"):
        label = category.attrib.get("term") or category.text
        if label is not None and label.strip():
            tags.append(label.strip())
    return tags


def _parse_datetime(value: str) -> datetime:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        return _ensure_aware_utc(datetime.fromisoformat(cleaned))
    except ValueError:
        return _ensure_aware_utc(parsedate_to_datetime(value))


def _parse_unitysquare_date(value: str | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    try:
        return datetime.strptime(value.strip(), "%Y.%m.%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean_summary(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _html_fragment_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _clean_summary(value)
    return cleaned or None


def _first_match(pattern: str, value: str) -> str | None:
    match = re.search(pattern, value, re.DOTALL)
    if match is None:
        return None
    return match.group("value")


def _unitysquare_tags(block: str) -> tuple[str, ...]:
    detail_match = re.search(r"<div class=\"p_detail\">(?P<value>.*?)</div>\s*</div>\s*$", block, re.DOTALL)
    detail = detail_match.group("value") if detail_match is not None else block
    tags = []
    for tag in re.findall(r"<div>(?P<value>.*?)</div>", detail, re.DOTALL):
        cleaned = _html_fragment_text(tag)
        if cleaned is not None:
            tags.append(cleaned.lstrip("#"))
    return tuple(tags)


def _string_field(payload: Mapping[object, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_url(value: str) -> str | None:
    match = _URL_RE.search(value)
    if match is None:
        return None
    return match.group(0).rstrip(".,)")
