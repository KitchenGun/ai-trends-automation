from dataclasses import replace
from datetime import datetime, timezone
import json
import subprocess

import pytest

from ai_trends.hermes_eval import HermesEvaluationError, _request_hermes_cli, evaluate_trend_item, evaluate_trend_items, parse_hermes_evaluation
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


def test_request_hermes_cli_uses_safe_toolset_and_configurable_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout='{"relevance_score":1,"importance_score":1,"rationale":"ok"}', stderr="")

    monkeypatch.setenv("HERMES_BIN", "/usr/local/bin/hermes-test")
    monkeypatch.setenv("AI_TRENDS_HERMES_EVAL_TIMEOUT_SECONDS", "180")
    monkeypatch.setattr(subprocess, "run", fake_run)

    response = _request_hermes_cli("score this")

    assert response == '{"relevance_score":1,"importance_score":1,"rationale":"ok"}'
    assert calls == [
        {
            "cmd": ["/usr/local/bin/hermes-test", "-z", "score this", "-t", "safe", "--ignore-rules"],
            "check": True,
            "capture_output": True,
            "text": True,
            "stdin": subprocess.DEVNULL,
            "timeout": 180,
        }
    ]


def test_evaluate_trend_item_wraps_invalid_hermes_response() -> None:
    with pytest.raises(HermesEvaluationError, match="valid JSON"):
        evaluate_trend_item(_item(), requester=lambda _prompt: "not-json")



def test_evaluate_trend_items_isolates_timeout_with_fallback_score() -> None:
    timed_out = _item()
    ok_item = replace(
        _item(),
        title="Hermes MCP coding agent tools",
        url="https://example.invalid/hermes-mcp-tools",
        summary="Release notes for AI agent MCP developer tools.",
    )
    calls = 0

    def requester(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(cmd=["hermes"], timeout=1)
        return json.dumps(
            {
                "relevance_score": 9,
                "importance_score": 8,
                "rationale": "Official agent tooling release.",
            }
        )

    scored = evaluate_trend_items((timed_out, ok_item), requester=requester)

    assert len(scored) == 2
    assert scored[0].raw_item == timed_out
    assert scored[0].relevance_score >= 1
    assert "Fallback(hermes_cli_timeout)" in scored[0].rationale
    assert scored[1].raw_item == ok_item
    assert scored[1].relevance_score == 9


def test_irrelevant_candidate_is_prefiltered_without_hermes_request() -> None:
    item = replace(
        _item(),
        title="Community investments in Missouri",
        url="https://example.invalid/missouri-programs",
        summary="Workforce and energy programs for a state community investment.",
        tags=("infrastructure", "community"),
    )

    scored = evaluate_trend_item(item, requester=lambda _prompt: pytest.fail("Hermes should not be called"))

    assert scored.relevance_score == 1
    assert scored.importance_score == 1
    assert "Fallback(irrelevant_prefilter)" in scored.rationale
