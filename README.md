# AI Trends Automation

AI Trends Automation collects public AI-agent trend signals into Google Sheets
hourly, then scores selected items while posting daily/weekly summaries to
Discord through Hermes cron jobs.

## Documentation

Operator documentation lives in `docs/ai-trends/`:

- `spreadsheet_columns.md` — required `raw_items`, `daily_digest`, and
  `weekly_digest` tab schemas.
- `discord_templates.md` — daily and weekly Discord message formats.
- `cron_operations.md` — Hermes cron job IDs, schedules, scripts,
  manual run/pause/resume commands, troubleshooting, and secret handling.
- `source_policy.md` — source selection rules and X-as-signal-only policy.
- `verification.md` — automated checks, manual checks, and local independence
  checklist.

Required environment variable names are documented in the operator docs. Do not
commit real secret values.
