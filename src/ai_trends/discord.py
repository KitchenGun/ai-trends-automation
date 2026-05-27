"""Discord webhook rendering and delivery helpers for AI trends digests."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_trends.config import ConfigError, DISCORD_WEBHOOK_URL_ENV
from ai_trends.models import DailyDigest, ScoredTrendItem, WeeklyDigest

DISCORD_CONTENT_LIMIT = 1900
_HTTP_TIMEOUT_SECONDS = 30

DiscordTransport = Callable[[str, dict[str, str], bytes], tuple[int, str]]


@dataclass(frozen=True)
class DiscordSendResult:
    """Safe, secret-free status from a Discord webhook attempt."""

    ok: bool
    status_code: int | None
    response_body: str = ""
    error: str = ""

    def __repr__(self) -> str:
        return (
            "DiscordSendResult("
            f"ok={self.ok!r}, status_code={self.status_code!r}, "
            f"response_body={self.response_body!r}, error={self.error!r}"
            ")"
        )

    def to_status_payload(self) -> dict[str, str]:
        """Return fields suitable for ``daily_digest``/``weekly_digest`` status columns."""

        if self.ok:
            return {"discord_status": "sent", "discord_error": ""}
        return {"discord_status": "failed", "discord_error": self.safe_error_message()}

    def safe_error_message(self) -> str:
        """Build a failure message without including webhook URL or request body."""

        if self.error:
            return self.error
        if self.status_code is None:
            return "Discord webhook request failed"
        detail = self.response_body.strip()
        if detail:
            return f"Discord webhook returned HTTP {self.status_code}: {detail}"
        return f"Discord webhook returned HTTP {self.status_code}"


def render_daily_digest_message(digest: DailyDigest) -> str:
    """Render a daily digest Discord markdown message within safe content limits."""

    lines = [
        f"## 일간 AI 트렌드 보고 — {digest.digest_date}",
        _digest_summary(digest.summary, item_count=len(digest.items), period_label="일간"),
        "",
        *_item_lines(digest.items),
    ]
    return _truncate_message("\n".join(lines))


def render_weekly_digest_message(digest: WeeklyDigest) -> str:
    """Render a weekly digest Discord markdown message within safe content limits."""

    lines = [
        f"## 주간 AI 트렌드 보고 — {digest.week_start} ~ {digest.week_end}",
        _digest_summary(digest.summary, item_count=len(digest.items), period_label="주간"),
        "",
        *_item_lines(digest.items),
    ]
    return _truncate_message("\n".join(lines))


def send_discord_webhook(
    webhook_url: str | None,
    content: str,
    *,
    transport: DiscordTransport | None = None,
) -> DiscordSendResult:
    """Send markdown content to Discord through an injectable transport.

    When ``webhook_url`` is omitted, the URL is loaded from
    ``AI_TRENDS_DISCORD_WEBHOOK_URL`` from the environment. The returned
    status object intentionally excludes the webhook URL.
    """

    resolved_webhook_url = _webhook_url(webhook_url)
    payload = json.dumps({"content": _truncate_message(content)}, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "HermesAITrendsBot/1.0"}
    active_transport = transport or _post_json
    attempts = _webhook_attempts()
    last_error = ""
    for attempt in range(attempts):
        try:
            status_code, response_body = active_transport(resolved_webhook_url, headers, payload)
        except OSError:
            last_error = "Discord webhook request failed"
            if attempt + 1 < attempts:
                time.sleep(_webhook_backoff_seconds(attempt))
                continue
            return DiscordSendResult(ok=False, status_code=None, error=last_error)

        ok = 200 <= status_code < 300
        if ok or status_code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
            return DiscordSendResult(ok=ok, status_code=status_code, response_body=response_body)
        time.sleep(_webhook_backoff_seconds(attempt))

    return DiscordSendResult(ok=False, status_code=None, error=last_error or "Discord webhook request failed")


def _webhook_attempts() -> int:
    raw_value = os.environ.get("AI_TRENDS_DISCORD_WEBHOOK_ATTEMPTS", "").strip()
    if not raw_value:
        return 2
    try:
        return max(1, min(4, int(raw_value)))
    except ValueError:
        return 2


def _webhook_backoff_seconds(attempt: int) -> float:
    return min(4.0, 0.5 * (attempt + 1))


def _item_lines(items: tuple[ScoredTrendItem, ...]) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        raw = item.raw_item
        lines.extend(
            [
                f"{index}. **{raw.title}**",
                f"   링크: {raw.url}",
                f"   점수: 관련성 {item.relevance_score}/10; 중요도 {item.importance_score}/10",
                f"   새 기능/변경점: {_feature_note(item)}",
                f"   선정 이유: {_selection_reason(item)}",
                f"   근거: {_evidence_note(item)}",
                f"   내 환경에서의 활용: {_environment_use(item)}",
            ]
        )
    return lines


def _short_text(value: str, *, limit: int = 180) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _digest_summary(value: str, *, item_count: int, period_label: str) -> str:
    summary = _short_text(value, limit=260)
    if _looks_korean(summary):
        return summary
    return (
        f"{period_label} AI 에이전트 트렌드 보고: 총 {item_count}개 항목을 다룹니다. "
        "주요 변화와 운영 영향은 아래 항목별 한국어 해설을 확인하세요."
    )


def _feature_note(item: ScoredTrendItem) -> str:
    raw = item.raw_item
    summary = _short_text(_strip_agent_prefix(raw.summary), limit=180)
    if _looks_korean(summary):
        return summary

    haystack = " ".join((raw.title, raw.summary, raw.source_type, " ".join(raw.tags))).lower()
    if raw.source_type == "x_rss_signal":
        return "공개 X RSS에서 포착된 AI 에이전트 관련 조기 신호입니다."
    if "mcp" in haystack:
        return "MCP 기반 도구 연결과 에이전트 오케스트레이션에 관련된 변경 신호입니다."
    if "hermes" in haystack:
        return "Hermes Agent 운영과 자동화 흐름에 참고할 만한 변경 신호입니다."
    if any(keyword in haystack for keyword in ("langchain", "ai sdk", "tool calling", "orchestration", "agent")):
        return "AI 에이전트 도구 호출, 오케스트레이션, 자동화 설계와 관련된 변경입니다."
    if raw.source_type in {"github_release", "release"}:
        return "에이전트 생태계 의존성 릴리스에서 유지보수 또는 호환성 변화를 확인했습니다."
    return "AI 에이전트 트렌드 후보로 추적할 만한 변화가 확인됐습니다."


def _selection_reason(item: ScoredTrendItem) -> str:
    rationale = _clean_rationale(item.rationale)
    if _is_internal_fallback(item.rationale) or not rationale:
        reason = "자동 예비 평가 기준으로 선별됨"
    elif _looks_korean(rationale):
        reason = _short_text(rationale, limit=140)
    else:
        reason = _generic_korean_reason(item)
    score_note = _score_note(item)
    if score_note:
        return f"{reason}. {score_note}"
    return reason


def _clean_rationale(rationale: str) -> str:
    text = _strip_agent_prefix(rationale)
    text = re.sub(r"Fallback\([^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"hermes_cli_timeout|hermesevaluationerror", "", text, flags=re.IGNORECASE)
    return _short_text(text.strip(" -—:;.,"), limit=140)


def _is_internal_fallback(rationale: str) -> bool:
    normalized = rationale.lower().replace("_", "")
    return "fallback(" in normalized or "hermesevaluationerror" in normalized or "hermesclitimeout" in normalized


def _strip_agent_prefix(value: str) -> str:
    return re.sub(r"^\s*Hermes agent:\s*", "", value.strip(), flags=re.IGNORECASE)


def _looks_korean(text: str) -> bool:
    return any("가" <= character <= "힣" for character in text)


def _generic_korean_reason(item: ScoredTrendItem) -> str:
    raw = item.raw_item
    haystack = " ".join((raw.title, raw.summary, raw.source_type, " ".join(raw.tags))).lower()
    if any(keyword in haystack for keyword in ("hermes", "mcp", "langchain", "ai sdk", "agent", "orchestration")):
        return "AI 에이전트 자동화와 도구 오케스트레이션 흐름에 직접 연결되어 선별됨"
    if raw.source_type in {"github_release", "release"}:
        return "유지보수/호환성/생태계 추적 가치가 있는 릴리스라 선별됨"
    return "AI 트렌드 후보로 포착되어 변화 추이를 추적할 가치가 있어 선별됨"


def _score_note(item: ScoredTrendItem) -> str:
    if item.relevance_score <= 4 or item.importance_score <= 4:
        return "낮은 점수이지만 후보로 포착되어 영향은 제한적으로 검토합니다."
    if item.raw_item.source_type in {"github_release", "release"}:
        return "단순 릴리스라도 유지보수/호환성/생태계 추적 가치가 있어 포함했습니다."
    return ""


def _evidence_note(item: ScoredTrendItem) -> str:
    raw = item.raw_item
    source_type = raw.source_type.lower()
    if source_type == "x_rss_signal":
        return "공개 X RSS 기반 조기 신호 — 공개 소셜 신호라 보조 근거로만 사용"
    if source_type == "github_release":
        return "GitHub release 기반 공개 자료로 판단"
    if source_type == "release":
        return "공개 릴리스 노트 기반으로 판단"
    if source_type in {"blog", "rss", "atom", "official_site"}:
        return f"{raw.source_name} 공개 출처 기반으로 판단"
    if source_type == "x_weak_signal":
        return "공개 X 검색 기반 약한 신호라 보조 근거로만 사용"
    return f"{raw.source_name} 공개 자료 기반으로 판단"


def _environment_use(item: ScoredTrendItem) -> str:
    raw = item.raw_item
    haystack = " ".join((raw.title, raw.summary, raw.source_type, " ".join(raw.tags))).lower()
    if "hermes" in haystack or "mcp" in haystack:
        return "personal-hermes-agent, Hermes cron, Codex 작업큐의 도구 연결과 자동화 안정성 개선에 참고할 수 있습니다."
    if "langchain" in haystack or "ai sdk" in haystack or "agent" in haystack or "orchestration" in haystack:
        return "AI Trends 수집/점수화/보고 자동화와 에이전트 오케스트레이션 설계 개선에 참고할 수 있습니다."
    if raw.source_type in {"github_release", "release"}:
        return "의존성 업데이트와 호환성 점검 후보로 추적할 수 있습니다."
    return "AI Trends 후보군의 우선순위 조정과 후속 모니터링에 참고할 수 있습니다."


def _truncate_message(message: str) -> str:
    if len(message) <= DISCORD_CONTENT_LIMIT:
        return message
    return f"{message[: DISCORD_CONTENT_LIMIT - 1].rstrip()}…"


def _webhook_url(webhook_url: str | None) -> str:
    if webhook_url is not None and webhook_url.strip():
        return webhook_url.strip()
    configured_webhook_url = os.environ.get(DISCORD_WEBHOOK_URL_ENV, "").strip()
    if configured_webhook_url:
        return configured_webhook_url
    raise ConfigError(f"Missing required environment variables: {DISCORD_WEBHOOK_URL_ENV}")


def _post_json(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 - URL comes from explicit env config.
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
