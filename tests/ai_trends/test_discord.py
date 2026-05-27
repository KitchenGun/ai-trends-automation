from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError

from ai_trends.discord import (
    DISCORD_CONTENT_LIMIT,
    DiscordSendResult,
    render_daily_digest_message,
    render_weekly_digest_message,
    send_discord_webhook,
)
from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem, WeeklyDigest


def _scored_item(
    title: str = "Hermes autonomous review",
    *,
    source_name: str = "Official Blog",
    source_type: str = "blog",
    url: str = "https://example.invalid/review",
    summary: str = "Hermes adds agentic code review workflows.",
    tags: tuple[str, ...] = ("ai-agent", "code-review"),
    evidence_urls: tuple[str, ...] = ("https://example.invalid/review",),
    relevance_score: int = 9,
    importance_score: int = 8,
    rationale: str = "Official evidence with concrete AI-agent workflow impact.",
) -> ScoredTrendItem:
    raw = RawTrendItem(
        source_name=source_name,
        source_type=source_type,
        title=title,
        url=url,
        published_at=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
        summary=summary,
        tags=tags,
        evidence_urls=evidence_urls,
    )
    return ScoredTrendItem(
        raw_item=raw,
        relevance_score=relevance_score,
        importance_score=importance_score,
        rationale=rationale,
    )


def test_daily_template_includes_scores_rationale_and_links() -> None:
    digest = DailyDigest(
        digest_date="2026-05-22",
        items=(_scored_item(),),
        summary="Daily summary for AI agent builders.",
    )

    message = render_daily_digest_message(digest)

    assert "일간 AI 트렌드 보고 — 2026-05-22" in message
    assert "Daily summary for AI agent builders." in message
    assert "Hermes autonomous review" in message
    assert "관련성 9/10" in message
    assert "중요도 8/10" in message
    assert "새 기능/변경점:" in message
    assert "선정 이유:" in message
    assert "근거:" in message
    assert "내 환경에서의 활용:" in message
    assert "Official evidence with concrete AI-agent workflow impact." not in message
    assert "https://example.invalid/review" in message
    assert len(message) <= DISCORD_CONTENT_LIMIT


def test_weekly_template_includes_range_scores_and_links() -> None:
    digest = WeeklyDigest(
        week_start="2026-05-18",
        week_end="2026-05-24",
        items=(_scored_item(),),
        summary="Weekly summary for AI agent builders.",
    )

    message = render_weekly_digest_message(digest)

    assert "주간 AI 트렌드 보고 — 2026-05-18 ~ 2026-05-24" in message
    assert "Weekly summary for AI agent builders." in message
    assert "관련성 9/10" in message
    assert "https://example.invalid/review" in message
    assert len(message) <= DISCORD_CONTENT_LIMIT


def test_daily_template_renders_korean_explanation_sections_and_hides_internal_rationale() -> None:
    digest = DailyDigest(
        digest_date="2026-05-22",
        items=(
            _scored_item(
                summary="Adds MCP server orchestration and safer cron handoff support.",
                rationale="Hermes agent: Fallback(hermes_cli_timeout) Agent orchestration relevance is high for Hermes cron.",
            ),
        ),
        summary="Daily summary for AI agent builders.",
    )

    message = render_daily_digest_message(digest)

    assert "새 기능/변경점:" in message
    assert "선정 이유:" in message
    assert "근거:" in message
    assert "내 환경에서의 활용:" in message
    assert "Hermes agent:" not in message
    assert "Fallback(hermes_cli_timeout)" not in message
    assert "자동 예비 평가 기준으로 선별됨" in message


def test_weekly_template_renders_same_korean_sections() -> None:
    digest = WeeklyDigest(
        week_start="2026-05-18",
        week_end="2026-05-24",
        items=(_scored_item(summary="LangChain release improves agent tool calling."),),
        summary="Weekly summary for AI agent builders.",
    )

    message = render_weekly_digest_message(digest)

    assert "새 기능/변경점:" in message
    assert "선정 이유:" in message
    assert "근거:" in message
    assert "내 환경에서의 활용:" in message


def test_x_rss_signal_renders_as_public_social_signal_with_caveat() -> None:
    digest = DailyDigest(
        digest_date="2026-05-22",
        items=(
            _scored_item(
                source_name="X RSS Signals",
                source_type="x_rss_signal",
                url="https://nitter.net/NousResearch/status/123",
                evidence_urls=("https://nitter.net/NousResearch/status/123",),
                summary="NousResearch post indicates Hermes Agent workflow changes.",
                rationale="Hermes agent: early signal for Hermes agent users.",
            ),
        ),
        summary="Daily summary for AI agent builders.",
    )

    message = render_daily_digest_message(digest)

    assert "공개 X RSS 기반 조기 신호" in message
    assert "공개 소셜 신호라 보조 근거로만 사용" in message
    assert "Hermes agent:" not in message


def test_daily_template_translates_rationale_and_internal_fallback_into_korean_sections() -> None:
    digest = DailyDigest(
        digest_date="2026-05-22",
        items=(
            _scored_item(
                source_type="github_release",
                summary="MCP orchestration release improves agent tool routing.",
                rationale="Hermes agent: Fallback(hermes_cli_timeout)",
                relevance_score=4,
                importance_score=3,
            ),
        ),
        summary="Daily summary for AI agent builders.",
    )

    message = render_daily_digest_message(digest)

    assert "새 기능/변경점: MCP orchestration release improves agent tool routing." in message
    assert "선정 이유: 자동 예비 평가 기준으로 선별됨" in message
    assert "근거: GitHub release 기반 공개 자료로 판단" in message
    assert "내 환경에서의 활용:" in message
    assert "낮은 점수이지만 후보로 포착되어 영향은 제한적으로 검토합니다." in message
    assert "Hermes agent:" not in message
    assert "Fallback(" not in message


def test_weekly_template_uses_same_korean_sections_for_x_rss_signal() -> None:
    digest = WeeklyDigest(
        week_start="2026-05-18",
        week_end="2026-05-24",
        items=(
            _scored_item(
                title="NousResearch Hermes Agent signal",
                source_name="X RSS",
                source_type="x_rss_signal",
                url="https://nitter.invalid/NousResearch/status/123",
                summary="NousResearch shared early Hermes Agent automation notes.",
                tags=("x-rss-signal", "x-author:@NousResearch"),
                evidence_urls=("https://nitter.invalid/NousResearch/status/123",),
                rationale="Hermes agent: early social signal for agent orchestration.",
            ),
        ),
        summary="Weekly summary for AI agent builders.",
    )

    message = render_weekly_digest_message(digest)

    assert "새 기능/변경점: NousResearch shared early Hermes Agent automation notes." in message
    assert "선정 이유:" in message
    assert "공개 X RSS 기반 조기 신호" in message
    assert "공개 소셜 신호라 보조 근거로만 사용" in message
    assert "내 환경에서의 활용:" in message
    assert "Hermes agent:" not in message


def test_discord_template_truncates_to_safe_content_limit() -> None:
    long_title = "Very important agent release " * 80
    items = tuple(_scored_item(title=f"{index}: {long_title}") for index in range(20))
    digest = DailyDigest(digest_date="2026-05-22", items=items, summary="Long digest summary " * 100)

    message = render_daily_digest_message(digest)

    assert len(message) <= DISCORD_CONTENT_LIMIT
    assert message.endswith("…")


def test_webhook_sender_uses_injected_transport_and_never_leaks_secret_url() -> None:
    webhook_url = "https://example.invalid/webhook-secret-value"
    calls: list[tuple[str, dict[str, str], bytes]] = []

    def transport(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        calls.append((url, headers, body))
        return 204, ""

    result = send_discord_webhook(webhook_url, "hello", transport=transport)

    assert result == DiscordSendResult(ok=True, status_code=204, response_body="")
    assert calls[0][0] == webhook_url
    assert calls[0][1]["Content-Type"] == "application/json"
    assert calls[0][2] == b'{"content":"hello"}'
    assert webhook_url not in repr(result)


def test_default_webhook_url_reads_only_scoped_env(monkeypatch) -> None:
    webhook_url = "https://example.invalid/webhook-secret-value"
    monkeypatch.setenv("AI_TRENDS_DISCORD_WEBHOOK_URL", webhook_url)
    monkeypatch.delenv("AI_TRENDS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    calls: list[str] = []

    def transport(url: str, _headers: dict[str, str], _body: bytes) -> tuple[int, str]:
        calls.append(url)
        return 204, ""

    result = send_discord_webhook(None, "hello", transport=transport)

    assert result.ok is True
    assert calls == [webhook_url]


def test_default_transport_preserves_http_error_status_and_body(monkeypatch) -> None:
    def failing_urlopen(*_args, **_kwargs):
        raise HTTPError(
            "https://example.invalid/webhook-secret-value",
            500,
            "Internal Server Error",
            hdrs=None,
            fp=BytesIO(b"upstream discord error"),
        )

    monkeypatch.setattr("ai_trends.discord.urlopen", failing_urlopen)

    result = send_discord_webhook("https://example.invalid/webhook-secret-value", "hello")

    assert result.status_code == 500
    assert result.to_status_payload() == {
        "discord_status": "failed",
        "discord_error": "Discord webhook returned HTTP 500: upstream discord error",
    }


def test_failed_discord_status_payload_is_safe_and_mockable() -> None:
    webhook_url = "https://example.invalid/webhook-secret-value"

    def transport(_url: str, _headers: dict[str, str], _body: bytes) -> tuple[int, str]:
        return 500, "upstream discord error"

    result = send_discord_webhook(webhook_url, "hello", transport=transport)

    assert result.ok is False
    assert result.status_code == 500
    assert result.to_status_payload() == {
        "discord_status": "failed",
        "discord_error": "Discord webhook returned HTTP 500: upstream discord error",
    }
    assert webhook_url not in repr(result)
    assert webhook_url not in result.to_status_payload()["discord_error"]


def test_webhook_sender_retries_transient_status(monkeypatch) -> None:
    calls: list[int] = []

    def transport(_url: str, _headers: dict[str, str], _body: bytes) -> tuple[int, str]:
        calls.append(1)
        return (503, "temporary") if len(calls) == 1 else (204, "")

    monkeypatch.setattr("ai_trends.discord.time.sleep", lambda _seconds: None)

    result = send_discord_webhook("https://example.invalid/webhook-secret-value", "hello", transport=transport)

    assert result.ok is True
    assert len(calls) == 2
