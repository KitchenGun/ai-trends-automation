"""Shared data models for AI trends collection and digests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
from typing import Any, Mapping, Self
from urllib.parse import urlparse

MIN_SCORE = 1
MAX_SCORE = 10


@dataclass(frozen=True)
class RawTrendItem:
    """A normalized trend candidate from a public source."""

    source_name: str
    source_type: str
    title: str
    url: str
    published_at: datetime
    summary: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    evidence_urls: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_non_blank("source_name", self.source_name)
        _require_non_blank("source_type", self.source_type)
        _require_non_blank("title", self.title)
        _require_non_blank("url", self.url)
        _require_non_blank("summary", self.summary)
        _require_url("url", self.url)
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        _require_non_empty_strings("tags", self.tags)
        _require_non_empty_strings("evidence_urls", self.evidence_urls, require_url=True)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["published_at"] = self.published_at.isoformat()
        payload["tags"] = list(self.tags)
        payload["evidence_urls"] = list(self.evidence_urls)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            source_name=_expect_str(payload, "source_name"),
            source_type=_expect_str(payload, "source_type"),
            title=_expect_str(payload, "title"),
            url=_expect_str(payload, "url"),
            published_at=_parse_datetime(_expect_str(payload, "published_at")),
            summary=_expect_str(payload, "summary"),
            tags=tuple(_expect_str_sequence(payload, "tags")),
            evidence_urls=tuple(_expect_str_sequence(payload, "evidence_urls")),
        )


@dataclass(frozen=True)
class ScoredTrendItem:
    """A trend item after Hermes relevance and importance evaluation."""

    raw_item: RawTrendItem
    relevance_score: int
    importance_score: int
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.raw_item, RawTrendItem):
            raise ValueError("raw_item must be a RawTrendItem")
        _require_score("relevance_score", self.relevance_score)
        _require_score("importance_score", self.importance_score)
        _require_non_blank("rationale", self.rationale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_item": self.raw_item.to_dict(),
            "relevance_score": self.relevance_score,
            "importance_score": self.importance_score,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        raw_payload = payload.get("raw_item")
        if not isinstance(raw_payload, Mapping):
            raise ValueError("raw_item must be an object")
        return cls(
            raw_item=RawTrendItem.from_dict(raw_payload),
            relevance_score=_expect_int(payload, "relevance_score"),
            importance_score=_expect_int(payload, "importance_score"),
            rationale=_expect_str(payload, "rationale"),
        )


@dataclass(frozen=True)
class DailyDigest:
    """Daily digest row payload for spreadsheet and Discord rendering."""

    digest_date: str
    items: tuple[ScoredTrendItem, ...]
    summary: str
    sheet_row_id: str | None = None

    def __post_init__(self) -> None:
        _require_iso_date("digest_date", self.digest_date)
        _require_items(self.items)
        _require_non_blank("summary", self.summary)
        if self.sheet_row_id is not None:
            _require_non_blank("sheet_row_id", self.sheet_row_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_date": self.digest_date,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
            "sheet_row_id": self.sheet_row_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> Self:
        data = json.loads(payload)
        if not isinstance(data, Mapping):
            raise ValueError("DailyDigest JSON must be an object")
        items_payload = data.get("items")
        if not isinstance(items_payload, list):
            raise ValueError("items must be a list")
        sheet_row_id = data.get("sheet_row_id")
        if sheet_row_id is not None and not isinstance(sheet_row_id, str):
            raise ValueError("sheet_row_id must be a string or null")
        return cls(
            digest_date=_expect_str(data, "digest_date"),
            items=tuple(_scored_items_from_payload(items_payload)),
            summary=_expect_str(data, "summary"),
            sheet_row_id=sheet_row_id,
        )


@dataclass(frozen=True)
class WeeklyDigest:
    """Weekly digest row payload for spreadsheet and Discord rendering."""

    week_start: str
    week_end: str
    items: tuple[ScoredTrendItem, ...]
    summary: str
    sheet_row_id: str | None = None

    def __post_init__(self) -> None:
        _require_iso_date("week_start", self.week_start)
        _require_iso_date("week_end", self.week_end)
        if date.fromisoformat(self.week_end) < date.fromisoformat(self.week_start):
            raise ValueError("week_end must be on or after week_start")
        _require_items(self.items)
        _require_non_blank("summary", self.summary)
        if self.sheet_row_id is not None:
            _require_non_blank("sheet_row_id", self.sheet_row_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
            "sheet_row_id": self.sheet_row_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> Self:
        data = json.loads(payload)
        if not isinstance(data, Mapping):
            raise ValueError("WeeklyDigest JSON must be an object")
        items_payload = data.get("items")
        if not isinstance(items_payload, list):
            raise ValueError("items must be a list")
        sheet_row_id = data.get("sheet_row_id")
        if sheet_row_id is not None and not isinstance(sheet_row_id, str):
            raise ValueError("sheet_row_id must be a string or null")
        return cls(
            week_start=_expect_str(data, "week_start"),
            week_end=_expect_str(data, "week_end"),
            items=tuple(_scored_items_from_payload(items_payload)),
            summary=_expect_str(data, "summary"),
            sheet_row_id=sheet_row_id,
        )


def _require_non_blank(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")


def _require_url(field_name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL")


def _require_non_empty_strings(
    field_name: str,
    values: tuple[str, ...],
    *,
    require_url: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple of strings")
    for value in values:
        _require_non_blank(field_name, value)
        if require_url:
            _require_url(field_name, value)


def _require_score(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_SCORE <= value <= MAX_SCORE:
        raise ValueError(f"{field_name} must be an integer from {MIN_SCORE} to {MAX_SCORE}")


def _require_iso_date(field_name: str, value: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date in YYYY-MM-DD format") from exc


def _require_items(items: tuple[ScoredTrendItem, ...]) -> None:
    if not items:
        raise ValueError("items must contain at least one scored trend item")
    for item in items:
        if not isinstance(item, ScoredTrendItem):
            raise ValueError("items must contain only ScoredTrendItem values")


def _expect_str(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _expect_int(payload: Mapping[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _expect_str_sequence(payload: Mapping[str, Any], field_name: str) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return value


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must be timezone-aware")
    return parsed


def _scored_items_from_payload(items_payload: list[Any]) -> list[ScoredTrendItem]:
    scored_items: list[ScoredTrendItem] = []
    for item_payload in items_payload:
        if not isinstance(item_payload, Mapping):
            raise ValueError("items must contain objects")
        scored_items.append(ScoredTrendItem.from_dict(item_payload))
    return scored_items
