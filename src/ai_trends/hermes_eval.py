"""Hermes Agent scoring for AI trend candidates."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import shutil
import subprocess
from typing import Callable, Mapping

from ai_trends.models import RawTrendItem, ScoredTrendItem

HermesRequester = Callable[[str], str]
LOGGER = logging.getLogger(__name__)

AGENT_TREND_TERMS = (
    "agent",
    "agents",
    "agentic",
    "autonomous",
    "mcp",
    "tool use",
    "tool-use",
    "developer tool",
    "developer tools",
    "coding agent",
    "code review",
    "model routing",
    "orchestration",
    "workflow automation",
    "assistant",
    "copilot",
)


class HermesEvaluationError(ValueError):
    """Raised when Hermes scoring cannot be requested or parsed."""


class HermesEvaluationTimeoutError(HermesEvaluationError):
    """Raised when Hermes scoring exceeds the per-item subprocess deadline."""


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

    Direct item scoring intentionally requires a Hermes response with rationale;
    batch scoring handles isolation and deterministic fallback.
    """

    if not is_likely_agent_trend(item):
        return _fallback_scored_item(item, "irrelevant_prefilter")

    prompt = build_evaluation_prompt(item)
    hermes_requester = requester or _request_hermes_cli
    try:
        response = hermes_requester(prompt)
    except HermesEvaluationError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise HermesEvaluationTimeoutError(f"Hermes evaluation timed out after {exc.timeout}s") from exc
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
    """Evaluate multiple trend items while isolating per-candidate failures."""

    scored_items: list[ScoredTrendItem] = []
    for item in items:
        try:
            scored_items.append(evaluate_trend_item(item, requester=requester))
        except HermesEvaluationError as exc:
            LOGGER.warning(
                "Hermes trend evaluation failed; using fallback score",
                extra={
                    "source_name": item.source_name,
                    "title": item.title,
                    "url": item.url,
                    "error_type": exc.__class__.__name__,
                },
            )
            scored_items.append(_fallback_scored_item(item, _fallback_reason(exc)))
    return tuple(scored_items)


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


def is_likely_agent_trend(item: RawTrendItem) -> bool:
    """Return whether a candidate is worth spending Hermes CLI time on."""

    haystack = " ".join((item.title, item.summary, " ".join(item.tags))).lower()
    return any(term in haystack for term in AGENT_TREND_TERMS)


def _fallback_scored_item(item: RawTrendItem, reason: str) -> ScoredTrendItem:
    relevance_score, importance_score = _deterministic_scores(item)
    return ScoredTrendItem(
        raw_item=item,
        relevance_score=relevance_score,
        importance_score=importance_score,
        rationale=f"Fallback({reason}): deterministic AI-agent relevance screening used without Hermes CLI judgment.",
    )


def _deterministic_scores(item: RawTrendItem) -> tuple[int, int]:
    haystack = " ".join((item.title, item.summary, " ".join(item.tags))).lower()
    matches = sum(1 for term in AGENT_TREND_TERMS if term in haystack)
    if matches <= 0:
        return 1, 1
    relevance_score = min(6, 2 + matches)
    importance_score = min(5, 2 + matches // 2)
    return relevance_score, importance_score


def _fallback_reason(exc: HermesEvaluationError) -> str:
    if isinstance(exc, HermesEvaluationTimeoutError):
        return "hermes_cli_timeout"
    return exc.__class__.__name__.lower()


def _request_hermes_cli(prompt: str) -> str:
    timeout_seconds = _hermes_eval_timeout_seconds()
    try:
        completed = subprocess.run(
            [_hermes_bin(), "-z", prompt, "-t", "safe", "--ignore-rules"],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesEvaluationTimeoutError(f"Hermes evaluation timed out after {timeout_seconds}s") from exc
    return completed.stdout.strip()


def _hermes_eval_timeout_seconds() -> int:
    raw_value = os.environ.get("AI_TRENDS_HERMES_EVAL_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return 180
    try:
        return max(30, int(raw_value))
    except ValueError:
        return 180


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
