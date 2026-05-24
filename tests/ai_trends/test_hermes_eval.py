from datetime import datetime, timezone
import json

import pytest

from ai_trends.hermes_eval import HermesEvaluationError, evaluate_trend_item, parse_hermes_evaluation
from ai_trends.models import RawTrendItem, ScoredTrendItem


def _item() -> RawTrendItem:
    return RawTrendItem(
        source_name="Official Blog",
        source_type="blog",
        title="Hermes adds autonomous code review",
        url="https://example.invalid/hermes-code-review",
        published_at=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
        summary="Release notes describing new AI agent review workflow.",
        tags=("ai-agent", "code-review"),
        evidence_urls=("https://example.invalid/hermes-code-review",),
    )


def test_parse_hermes_evaluation_extracts_scores_and_rationale_from_json() -> None:
    payload = json.dumps(
        {
            "relevance_score": 9,
            "importance_score": 8,
            "rationale": "Directly affects AI agent engineering workflows.",
        }
    )

    result = parse_hermes_evaluation(payload)

    assert result.relevance_score == 9
    assert result.importance_score == 8
    assert result.rationale == "Directly affects AI agent engineering workflows."


def test_parse_hermes_evaluation_rejects_keyword_only_or_missing_rationale() -> None:
    with pytest.raises(HermesEvaluationError, match="rationale"):
        parse_hermes_evaluation('{"relevance_score": 5, "importance_score": 5, "rationale": ""}')

    with pytest.raises(HermesEvaluationError, match="integer"):
        parse_hermes_evaluation('{"relevance_score": "ai", "importance_score": 5, "rationale": "Reasoned."}')


def test_evaluate_trend_item_uses_injected_hermes_requester_and_returns_scored_item() -> None:
    prompts: list[str] = []

    def requester(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "relevance_score": 10,
                "importance_score": 7,
                "rationale": "Official release with concrete workflow impact and evidence URL.",
            }
        )

    scored = evaluate_trend_item(_item(), requester=requester)

    assert isinstance(scored, ScoredTrendItem)
    assert scored.relevance_score == 10
    assert scored.importance_score == 7
    assert "keyword" in prompts[0].lower()
    assert "Hermes adds autonomous code review" in prompts[0]


def test_evaluate_trend_item_wraps_invalid_hermes_response() -> None:
    with pytest.raises(HermesEvaluationError, match="valid JSON"):
        evaluate_trend_item(_item(), requester=lambda _prompt: "not-json")
