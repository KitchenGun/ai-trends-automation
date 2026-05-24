# AI Trends Spreadsheet Columns

The AI trends automation writes to one Google Spreadsheet with three tabs:
`raw_items`, `daily_digest`, and `weekly_digest`. Create the tabs with the
exact names below and add the header row in the exact order shown.

## Environment used by spreadsheet writes

Required environment variables:

| Name | Purpose |
| --- | --- |
| `AI_TRENDS_SPREADSHEET_ID` | Spreadsheet identifier used for all append/read/update operations. |
| `AI_TRENDS_DISCORD_WEBHOOK_URL` | Discord webhook used after spreadsheet writes succeed. |
| `HERMES_TIMEZONE` | IANA timezone used to interpret cron schedules and run dates. |

Optional environment variables:

| Name | Purpose |
| --- | --- |
| `AI_TRENDS_X_BEARER_TOKEN` | Enables X recent-search collection as weak signal input only. |
| `AI_TRENDS_GITHUB_TOKEN` | Reserved for GitHub API access when authenticated release fetches are needed. If unset, GitHub CLI auth may be used via `gh auth token`. |

Store secret values in the operator secret store or Hermes environment file, not
in repository files or documentation.

## `raw_items`

One row per collected trend candidate after collection and de-duplication.
Hourly collection leaves score columns blank; daily/weekly reporting can score
selected rows when building digests.

| Column | Type/format | Description |
| --- | --- | --- |
| `source_name` | string | Human-readable source label, such as an official blog or GitHub releases endpoint. |
| `source_type` | string | Normalized source type. Current values include `blog`, `atom`, `github_release`, and `x_weak_signal`. |
| `title` | string | Candidate title after feed/API normalization. |
| `url` | absolute http(s) URL | Primary link for the candidate. |
| `published_at` | timezone-aware ISO datetime | Publication timestamp normalized from the source. Missing feed dates use fetch time. |
| `summary` | string | Source summary/body text with HTML stripped. |
| `tags_json` | JSON array of strings | Source tags/categories. Empty list is stored as `[]`. |
| `evidence_urls_json` | JSON array of absolute URLs | Evidence links supporting the item. |
| `relevance_score` | integer string, 1-10, or blank | Hermes relevance score for AI-agent builders. Blank means collected but not scored yet. |
| `importance_score` | integer string, 1-10, or blank | Hermes importance score for market/product impact. Blank means collected but not scored yet. |
| `score_rationale` | string or blank | Short rationale for both scores. Blank means collected but not scored yet. |

Header row:

```csv
source_name,source_type,title,url,published_at,summary,tags_json,evidence_urls_json,relevance_score,importance_score,score_rationale
```

## `daily_digest`

One row per daily run. The daily job reads `raw_items`, scores selected unscored
rows for the digest, appends the digest row with Discord status `pending`, and
finally Discord delivery updates the status columns.

| Column | Type/format | Description |
| --- | --- | --- |
| `digest_date` | ISO date, `YYYY-MM-DD` | Date covered by the daily digest. |
| `summary` | string | One-paragraph daily summary. |
| `item_count` | integer string | Number of scored items included. |
| `top_titles_json` | JSON array of strings | Item titles included in the digest. |
| `top_links_json` | JSON array of URLs | Item links included in the digest. |
| `score_rationales_json` | JSON array of strings | Score rationales for the included items. |
| `items_json` | JSON object string | Full serialized `DailyDigest` payload. |
| `discord_status` | `pending`, `sent`, or `failed` | Discord delivery state for this digest row. |
| `discord_error` | string | Safe error message when delivery fails. Must not include webhook URL or token values. |
| `discord_sent_at` | timezone-aware ISO datetime or blank | Run timestamp when Discord delivery succeeds. Blank on pending/failed. |
| `sheet_row_id` | string or blank | Optional external row identifier if a Sheets adapter supplies one. |

Header row:

```csv
digest_date,summary,item_count,top_titles_json,top_links_json,score_rationales_json,items_json,discord_status,discord_error,discord_sent_at,sheet_row_id
```

## `weekly_digest`

One row per weekly run. The weekly job reads `raw_items`, filters the configured
week window, de-duplicates, asks Hermes for a concise summary, appends this row,
and then attempts Discord delivery.

| Column | Type/format | Description |
| --- | --- | --- |
| `week_start` | ISO date, `YYYY-MM-DD` | First date included in the weekly window. |
| `week_end` | ISO date, `YYYY-MM-DD` | Last date included in the weekly window. |
| `summary` | string | Weekly summary clustered around themes and concrete impact. |
| `item_count` | integer string | Number of scored items included after de-duplication. |
| `top_titles_json` | JSON array of strings | Item titles included in the digest. |
| `top_links_json` | JSON array of URLs | Item links included in the digest. |
| `score_rationales_json` | JSON array of strings | Score rationales for the included items. |
| `items_json` | JSON object string | Full serialized `WeeklyDigest` payload. |
| `discord_status` | `pending`, `sent`, or `failed` | Discord delivery state for this digest row. |
| `discord_error` | string | Safe error message when delivery fails. Must not include webhook URL or token values. |
| `discord_sent_at` | timezone-aware ISO datetime or blank | Run timestamp when Discord delivery succeeds. Blank on pending/failed. |
| `sheet_row_id` | string or blank | Optional external row identifier if a Sheets adapter supplies one. |

Header row:

```csv
week_start,week_end,summary,item_count,top_titles_json,top_links_json,score_rationales_json,items_json,discord_status,discord_error,discord_sent_at,sheet_row_id
```

## Failure behavior

- Spreadsheet append failures abort the run before Discord is attempted.
- Discord failures do not remove spreadsheet rows. The digest row remains and the
  Discord status columns are updated to `failed` with a safe, secret-free error.
- Retry notification-only failures by using the existing digest row payload rather
  than re-appending duplicate raw items.
