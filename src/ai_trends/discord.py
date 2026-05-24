"""Discord webhook rendering and delivery helpers for AI trends digests."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
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
        digest.summary,
        "",
        *_item_lines(digest.items),
    ]
    return _truncate_message("\n".join(lines))


def render_weekly_digest_message(digest: WeeklyDigest) -> str:
    """Render a weekly digest Discord markdown message within safe content limits."""

    lines = [
        f"## 주간 AI 트렌드 보고 — {digest.week_start} ~ {digest.week_end}",
        digest.summary,
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
    try:
        status_code, response_body = active_transport(resolved_webhook_url, headers, payload)
    except OSError:
        return DiscordSendResult(ok=False, status_code=None, error="Discord webhook request failed")

    ok = 200 <= status_code < 300
    return DiscordSendResult(ok=ok, status_code=status_code, response_body=response_body)


def _item_lines(items: tuple[ScoredTrendItem, ...]) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        raw = item.raw_item
        lines.extend(
            [
                f"{index}. **{raw.title}**",
                f"   링크: {raw.url}",
                f"   점수: 관련성 {item.relevance_score}/10; 중요도 {item.importance_score}/10",
                f"   근거: {item.rationale}",
            ]
        )
    return lines


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
