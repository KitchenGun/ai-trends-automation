"""Hermes Agent scoring for AI trend candidates."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shutil
import subprocess
from typing import Callable, Mapping

from ai_trends.models import RawTrendItem, ScoredTrendItem

HermesRequester = Callable[[str], str]


class HermesEvaluationError(ValueError):
    """Raised when Hermes scoring cannot be requested or parsed."""


@dataclass(frozen=True)
class HermesEvaluation:
    """Parsed Hermes scoring response."""

    relevance_score: int
    importance_score: int
    rationale: str


def evaluate_trend_item(
    item: RawTrendItem,
    *,
    requester: HermesRequester | None = None,
) -> ScoredTrendItem:
    """Request Hermes relevance/importance scoring and return a scored item.

    The scoring path intentionally requires a Hermes response with rationale; it
    does not fall back to keyword counts or other local heuristic scoring.
    """

    prompt = build_evaluation_prompt(item)
    hermes_requester = requester or _request_hermes_cli
    try:
        response = hermes_requester(prompt)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HermesEvaluationError("Failed to request Hermes evaluation") from exc

    evaluation = parse_hermes_evaluation(response)
    return ScoredTrendItem(
        raw_item=item,
        relevance_score=evaluation.relevance_score,
        importance_score=evaluation.importance_score,
        rationale=evaluation.rationale,
    )


def evaluate_trend_items(
    items: list[RawTrendItem] | tuple[RawTrendItem, ...],
    *,
    requester: HermesRequester | None = None,
) -> tuple[ScoredTrendItem, ...]:
    """Evaluate multiple trend items with Hermes."""

    return tuple(evaluate_trend_item(item, requester=requester) for item in items)


def build_evaluation_prompt(item: RawTrendItem) -> str:
    """Build the structured prompt sent to Hermes Agent for scoring."""

    evidence = "\n".join(f"- {url}" for url in item.evidence_urls)
    tags = ", ".join(item.tags) if item.tags else "none"
    return (
        "Evaluate this AI-agent trend candidate for a Hermes AI trends digest.\n"
        "Return ONLY valid JSON with integer relevance_score (1-10), integer "
        "importance_score (1-10), and a short rationale string.\n"
        "Use the official/public evidence, recency, source quality, and concrete "
        "impact on AI agent builders. Do not score solely by keyword counts.\n\n"
        f"Source: {item.source_name} ({item.source_type})\n"
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Published: {item.published_at.isoformat()}\n"
        f"Summary: {item.summary}\n"
        f"Tags: {tags}\n"
        f"Evidence URLs:\n{evidence}\n"
    )


def parse_hermes_evaluation(response: str) -> HermesEvaluation:
    """Parse Hermes JSON output into validated score fields."""

    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise HermesEvaluationError("Hermes evaluation must be valid JSON") from exc

    if not isinstance(payload, Mapping):
        raise HermesEvaluationError("Hermes evaluation must be a JSON object")

    relevance_score = _require_score(payload, "relevance_score")
    importance_score = _require_score(payload, "importance_score")
    rationale = _require_rationale(payload)
    return HermesEvaluation(
        relevance_score=relevance_score,
        importance_score=importance_score,
        rationale=rationale,
    )


def _request_hermes_cli(prompt: str) -> str:
    completed = subprocess.run(
        [_hermes_bin(), "-z", prompt],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout.strip()


def _hermes_bin() -> str:
    return os.environ.get("HERMES_BIN") or shutil.which("hermes") or "hermes"


def _require_score(payload: Mapping[object, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HermesEvaluationError(f"{field_name} must be an integer from 1 to 10")
    if not 1 <= value <= 10:
        raise HermesEvaluationError(f"{field_name} must be an integer from 1 to 10")
    return value


def _require_rationale(payload: Mapping[object, object]) -> str:
    value = payload.get("rationale")
    if not isinstance(value, str) or not value.strip():
        raise HermesEvaluationError("rationale must be a non-blank string")
    return value.strip()
