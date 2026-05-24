"""Public-source collection for AI trend candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import re
from typing import Callable, Mapping
from urllib.parse import quote
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
        if self.source_type not in {"rss", "atom", "github_release"}:
            raise ValueError("source_type must be rss, atom, or github_release")
        if not self.url.strip().startswith(("http://", "https://")):
            raise ValueError("url must be an absolute http(s) URL")


DEFAULT_TREND_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(name="OpenAI News", source_type="rss", url="https://openai.com/news/rss.xml"),
    SourceSpec(name="Google AI Blog", source_type="rss", url="https://blog.google/technology/ai/rss/"),
    SourceSpec(name="Hugging Face Blog", source_type="rss", url="https://huggingface.co/blog/feed.xml"),
    SourceSpec(name="Microsoft AI Blog", source_type="rss", url="https://blogs.microsoft.com/ai/feed/"),
    SourceSpec(name="NVIDIA Generative AI Blog", source_type="rss", url="https://developer.nvidia.com/blog/category/generative-ai/feed/"),
    SourceSpec(name="Unreal Engine News", source_type="rss", url="https://www.unrealengine.com/rss"),
    SourceSpec(name="Unity Games Blog", source_type="rss", url="https://blog.unity.com/games/feed"),
    SourceSpec(name="Unity Engine Platform Blog", source_type="rss", url="https://blog.unity.com/engine-platform/feed"),
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
) -> tuple[RawTrendItem, ...]:
    """Collect trend candidates from approved public endpoints.

    X is collected only when an explicit bearer token is supplied and is marked as
    a weak signal rather than primary evidence.
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
        except Exception:
            continue

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
    with urlopen(request, timeout=30) as response:  # noqa: S310 - caller supplies public endpoints.
        return response.read().decode("utf-8")


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
    return RawTrendItem(
        source_name=source_name,
        source_type=source_type,
        title=_clean_summary(title),
        url=url,
        published_at=published_at,
        summary=_clean_summary(summary),
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


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean_summary(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


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
