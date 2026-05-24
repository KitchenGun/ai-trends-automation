"""Spreadsheet row mapping and client helpers for AI trends digests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, Sequence

from ai_trends.config import ConfigError, SPREADSHEET_ID_ENV
from ai_trends.models import DailyDigest, RawTrendItem, ScoredTrendItem, WeeklyDigest

RAW_ITEMS_SHEET = "raw_items"
DAILY_DIGEST_SHEET = "daily_digest"
WEEKLY_DIGEST_SHEET = "weekly_digest"

RAW_ITEMS_COLUMNS: tuple[str, ...] = (
    "source_name",
    "source_type",
    "title",
    "url",
    "published_at",
    "summary",
    "tags_json",
    "evidence_urls_json",
    "relevance_score",
    "importance_score",
    "score_rationale",
)
DAILY_DIGEST_COLUMNS: tuple[str, ...] = (
    "digest_date",
    "summary",
    "item_count",
    "top_titles_json",
    "top_links_json",
    "score_rationales_json",
    "items_json",
    "discord_status",
    "discord_error",
    "discord_sent_at",
    "sheet_row_id",
)
WEEKLY_DIGEST_COLUMNS: tuple[str, ...] = (
    "week_start",
    "week_end",
    "summary",
    "item_count",
    "top_titles_json",
    "top_links_json",
    "score_rationales_json",
    "items_json",
    "discord_status",
    "discord_error",
    "discord_sent_at",
    "sheet_row_id",
)

_SCHEMA_BY_SHEET: dict[str, tuple[str, ...]] = {
    RAW_ITEMS_SHEET: RAW_ITEMS_COLUMNS,
    DAILY_DIGEST_SHEET: DAILY_DIGEST_COLUMNS,
    WEEKLY_DIGEST_SHEET: WEEKLY_DIGEST_COLUMNS,
}
def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser().resolve()


GOOGLE_API = hermes_home() / "hermes-agent" / "skills" / "productivity" / "google-workspace" / "scripts" / "google_api.py"
GOOGLE_TOKEN = Path(os.environ.get("GOOGLE_TOKEN_PATH", str(hermes_home() / "google_token.json"))).expanduser().resolve()
GOOGLE_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class SheetsClient(Protocol):
    """Small testable adapter surface for Google Sheets value operations."""

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> object:
        """Append rows to a sheet range."""
        ...

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        """Read rows from a sheet range."""
        ...

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> object:
        """Update rows in a sheet range."""
        ...


class GwsSheetsClient:
    """Google Workspace adapter backed by Hermes' local google_api.py."""

    def __init__(self, google_api: str | Path | None = None, timeout: int = 60) -> None:
        self.google_api = Path(google_api) if google_api is not None else GOOGLE_API
        self.timeout = timeout

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> object:
        if not values:
            return {"updatedCells": 0, "updatedRange": ""}
        self._ensure_sheet_header(spreadsheet_id, range_name)
        next_row = len(self.get_values(spreadsheet_id, range_name)) + 1
        result = self._run("append", spreadsheet_id, range_name, values)
        if "updatedRange" not in result:
            sheet_name = range_name.split("!", 1)[0]
            last_column = _column_letter(max(len(row) for row in values))
            last_row = next_row + len(values) - 1
            result = {**result, "updatedRange": f"{sheet_name}!A{next_row}:{last_column}{last_row}"}
        return result

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        self._ensure_sheet_header(spreadsheet_id, range_name)
        cmd = [sys.executable, str(self.google_api), "sheets", "get", spreadsheet_id, range_name]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=self.timeout)
        if completed.returncode != 0:
            raise RuntimeError("Google Sheets get failed")
        payload = json.loads(completed.stdout or "[]")
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise RuntimeError("Google Sheets get returned an invalid payload")
        return payload

    def update_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> object:
        self._ensure_sheet(spreadsheet_id, _sheet_name(range_name))
        return self._run("update", spreadsheet_id, range_name, values)

    def _run(self, command: str, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> dict[str, object]:
        cmd = [
            sys.executable,
            str(self.google_api),
            "sheets",
            command,
            spreadsheet_id,
            range_name,
            "--values",
            json.dumps(values, ensure_ascii=False),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=self.timeout)
        if completed.returncode != 0:
            raise RuntimeError(f"Google Sheets {command} failed")
        payload = json.loads(completed.stdout or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Google Sheets {command} returned an invalid payload")
        return payload

    def _ensure_sheet_header(self, spreadsheet_id: str, range_name: str) -> None:
        sheet_name = _sheet_name(range_name)
        schema = _SCHEMA_BY_SHEET.get(sheet_name)
        if schema is None:
            return
        self._ensure_sheet(spreadsheet_id, sheet_name)
        header_range = f"{sheet_name}!A1:{_column_letter(len(schema))}1"
        cmd = [sys.executable, str(self.google_api), "sheets", "get", spreadsheet_id, header_range]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=self.timeout)
        if completed.returncode == 0:
            try:
                values = json.loads(completed.stdout or "[]")
            except json.JSONDecodeError:
                values = []
            if values is None:
                values = []
            if values:
                return
        self._run("update", spreadsheet_id, header_range, [list(schema)])

    def _ensure_sheet(self, spreadsheet_id: str, sheet_name: str) -> None:
        service = _build_sheets_service()
        metadata = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties.title",
        ).execute()
        titles = {sheet["properties"]["title"] for sheet in metadata.get("sheets", [])}
        if sheet_name in titles:
            return
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()

def raw_item_row(item: ScoredTrendItem) -> list[str]:
    """Map one scored trend item to the documented ``raw_items`` column order."""

    raw = item.raw_item
    return [
        raw.source_name,
        raw.source_type,
        raw.title,
        raw.url,
        raw.published_at.isoformat(),
        raw.summary,
        _json_list(raw.tags),
        _json_list(raw.evidence_urls),
        str(item.relevance_score),
        str(item.importance_score),
        item.rationale,
    ]


def collected_raw_item_row(item: RawTrendItem) -> list[str]:
    """Map one unscored collected item to the documented ``raw_items`` columns."""

    return [
        item.source_name,
        item.source_type,
        item.title,
        item.url,
        item.published_at.isoformat(),
        item.summary,
        _json_list(item.tags),
        _json_list(item.evidence_urls),
        "",
        "",
        "",
    ]


def daily_digest_row(
    digest: DailyDigest,
    *,
    discord_status: str = "pending",
    discord_error: str = "",
    discord_sent_at: str = "",
) -> list[str]:
    """Map a daily digest to the documented ``daily_digest`` column order."""

    _validate_discord_status(discord_status)
    return [
        digest.digest_date,
        digest.summary,
        str(len(digest.items)),
        _json_list(item.raw_item.title for item in digest.items),
        _json_list(item.raw_item.url for item in digest.items),
        _json_list(item.rationale for item in digest.items),
        digest.to_json(),
        discord_status,
        discord_error,
        discord_sent_at,
        digest.sheet_row_id or "",
    ]


def weekly_digest_row(
    digest: WeeklyDigest,
    *,
    discord_status: str = "pending",
    discord_error: str = "",
    discord_sent_at: str = "",
) -> list[str]:
    """Map a weekly digest to the documented ``weekly_digest`` column order."""

    _validate_discord_status(discord_status)
    return [
        digest.week_start,
        digest.week_end,
        digest.summary,
        str(len(digest.items)),
        _json_list(item.raw_item.title for item in digest.items),
        _json_list(item.raw_item.url for item in digest.items),
        _json_list(item.rationale for item in digest.items),
        digest.to_json(),
        discord_status,
        discord_error,
        discord_sent_at,
        digest.sheet_row_id or "",
    ]


def append_raw_items(
    client: SheetsClient,
    items: Sequence[ScoredTrendItem],
    *,
    spreadsheet_id: str | None = None,
) -> object:
    """Append scored raw items with an injected Sheets client."""

    rows = [raw_item_row(item) for item in items]
    return client.append_values(_spreadsheet_id(spreadsheet_id), _append_range(RAW_ITEMS_SHEET), rows)


def append_collected_raw_items(
    client: SheetsClient,
    items: Sequence[RawTrendItem],
    *,
    spreadsheet_id: str | None = None,
) -> object:
    """Append unscored raw collection rows with an injected Sheets client."""

    rows = [collected_raw_item_row(item) for item in items]
    return client.append_values(_spreadsheet_id(spreadsheet_id), _append_range(RAW_ITEMS_SHEET), rows)


def append_daily_digest(
    client: SheetsClient,
    digest: DailyDigest,
    *,
    spreadsheet_id: str | None = None,
    discord_status: str = "pending",
    discord_error: str = "",
    discord_sent_at: str = "",
) -> object:
    """Append one daily digest row with an injected Sheets client."""

    row = daily_digest_row(
        digest,
        discord_status=discord_status,
        discord_error=discord_error,
        discord_sent_at=discord_sent_at,
    )
    return client.append_values(_spreadsheet_id(spreadsheet_id), _append_range(DAILY_DIGEST_SHEET), [row])


def append_weekly_digest(
    client: SheetsClient,
    digest: WeeklyDigest,
    *,
    spreadsheet_id: str | None = None,
    discord_status: str = "pending",
    discord_error: str = "",
    discord_sent_at: str = "",
) -> object:
    """Append one weekly digest row with an injected Sheets client."""

    row = weekly_digest_row(
        digest,
        discord_status=discord_status,
        discord_error=discord_error,
        discord_sent_at=discord_sent_at,
    )
    return client.append_values(_spreadsheet_id(spreadsheet_id), _append_range(WEEKLY_DIGEST_SHEET), [row])


def read_sheet_rows(
    client: SheetsClient,
    sheet_name: str,
    *,
    spreadsheet_id: str | None = None,
) -> list[dict[str, str]]:
    """Read a known AI trends sheet as dictionaries keyed by its schema columns."""

    columns = _schema_for(sheet_name)
    raw_rows = client.get_values(_spreadsheet_id(spreadsheet_id), _append_range(sheet_name))
    if not raw_rows:
        return []

    data_rows = raw_rows[1:] if tuple(raw_rows[0]) == columns else raw_rows
    normalized_rows: list[dict[str, str]] = []
    for row in data_rows:
        padded = [*row, *("" for _ in range(max(0, len(columns) - len(row))))]
        normalized_rows.append(dict(zip(columns, padded[: len(columns)], strict=True)))
    return normalized_rows


def update_discord_status(
    client: SheetsClient,
    sheet_name: str,
    *,
    row_number: int,
    status: str,
    error: str = "",
    sent_at: str = "",
    spreadsheet_id: str | None = None,
) -> object:
    """Update Discord status/error/sent timestamp columns for a digest row."""

    if row_number < 1:
        raise ValueError("row_number must be a positive one-based sheet row")
    columns = _schema_for(sheet_name)
    if "discord_status" not in columns or "discord_error" not in columns or "discord_sent_at" not in columns:
        raise ValueError(f"Sheet {sheet_name!r} does not contain Discord status columns")
    _validate_discord_status(status)

    status_column = _column_letter(columns.index("discord_status") + 1)
    sent_at_column = _column_letter(columns.index("discord_sent_at") + 1)
    range_name = f"{sheet_name}!{status_column}{row_number}:{sent_at_column}{row_number}"
    return client.update_values(_spreadsheet_id(spreadsheet_id), range_name, [[status, error, sent_at]])


def _sheet_name(range_name: str) -> str:
    return range_name.split("!", 1)[0].strip("'")


def _build_sheets_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not GOOGLE_TOKEN.exists():
        raise RuntimeError("Google Sheets credentials are missing")
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GOOGLE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError("Google Sheets credentials are invalid")
    return build("sheets", "v4", credentials=creds)


def _spreadsheet_id(spreadsheet_id: str | None) -> str:
    if spreadsheet_id is not None and spreadsheet_id.strip():
        return spreadsheet_id.strip()
    configured_spreadsheet_id = os.environ.get(SPREADSHEET_ID_ENV, "").strip()
    if configured_spreadsheet_id:
        return configured_spreadsheet_id
    raise ConfigError(f"Missing required environment variables: {SPREADSHEET_ID_ENV}")


def _schema_for(sheet_name: str) -> tuple[str, ...]:
    try:
        return _SCHEMA_BY_SHEET[sheet_name]
    except KeyError as exc:
        known = ", ".join(sorted(_SCHEMA_BY_SHEET))
        raise ValueError(f"Unknown AI trends sheet {sheet_name!r}; expected one of: {known}") from exc


def _append_range(sheet_name: str) -> str:
    columns = _schema_for(sheet_name)
    return f"{sheet_name}!A:{_column_letter(len(columns))}"


def _column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be positive")
    letters = ""
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        letters = f"{chr(65 + remainder)}{letters}"
    return letters


def _json_list(values: Iterable[str]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _validate_discord_status(status: str) -> None:
    if status not in {"pending", "sent", "failed"}:
        raise ValueError("discord_status must be pending, sent, or failed")
