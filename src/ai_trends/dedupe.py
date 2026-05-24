"""Deduplication helpers for AI trend candidates."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ai_trends.models import RawTrendItem

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_NAMES = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def dedupe_trend_items(items: list[RawTrendItem] | tuple[RawTrendItem, ...]) -> tuple[RawTrendItem, ...]:
    """Return items de-duplicated by canonical URL, then title within source.

    URL matches win first across all sources. If URLs differ, normalized title matches
    are considered duplicates only inside the same ``source_name`` so legitimate
    cross-source collisions remain available as corroborating evidence.
    """

    seen_urls: set[str] = set()
    seen_title_source_keys: set[tuple[str, str]] = set()
    deduped_items: list[RawTrendItem] = []

    for item in items:
        canonical_url = canonicalize_url(item.url)
        if canonical_url in seen_urls:
            continue

        title_source_key = (_normalize_source_name(item.source_name), normalize_title(item.title))
        if title_source_key in seen_title_source_keys:
            continue

        seen_urls.add(canonical_url)
        seen_title_source_keys.add(title_source_key)
        deduped_items.append(item)

    return tuple(deduped_items)


def canonicalize_url(url: str) -> str:
    """Normalize URL enough for public-source duplicate detection."""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query_pairs = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_name(name)
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def normalize_title(title: str) -> str:
    """Normalize title case, punctuation, and whitespace for duplicate matching."""

    words_only = _NON_WORD_RE.sub(" ", title.casefold())
    return _SPACE_RE.sub(" ", words_only).strip()


def _normalize_source_name(source_name: str) -> str:
    return _SPACE_RE.sub(" ", source_name.casefold()).strip()


def _is_tracking_query_name(name: str) -> bool:
    normalized = name.casefold()
    return normalized in _TRACKING_QUERY_NAMES or normalized.startswith(_TRACKING_QUERY_PREFIXES)
