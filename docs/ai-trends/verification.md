# AI Trends Verification

Use these checks before enabling or changing the AI trends cron jobs.

## Automated checks

From the project root:

```bash
python -m compileall -q src tests
pytest -q
```

Expected result: all tests pass. Current test coverage includes:

- Environment-only configuration and secret redaction behavior.
- Job YAML schedules, environment names, outputs, and failure policy.
- Spreadsheet row mapping and Discord status updates.
- Daily and weekly workflow failure ordering.
- Discord message rendering, truncation, and safe error payloads.
- Public source parsing and X weak-signal behavior.

## Schema checks

Confirm the spreadsheet tabs and headers match
`docs/ai-trends/spreadsheet_columns.md` exactly:

- `raw_items`
- `daily_digest`
- `weekly_digest`

Manual spot-checks:

- `raw_items.published_at` values are timezone-aware ISO datetimes.
- JSON columns parse as JSON arrays or objects as documented.
- Score values are integers from 1 to 10.
- `discord_status` is only `pending`, `sent`, or `failed`.
- `discord_error` never includes webhook URLs or token values.

## Manual setup checks

Spreadsheet and sharing:

- The spreadsheet exists and has all three required tabs.
- The cron-running Google identity can append, read, and update rows.
- `AI_TRENDS_SPREADSHEET_ID` is registered for the cron profile.

Secrets and tokens:

- `AI_TRENDS_DISCORD_WEBHOOK_URL` is registered for the cron profile.
- `HERMES_TIMEZONE` is registered and is a valid IANA timezone.
- `AI_TRENDS_X_BEARER_TOKEN` is registered only if X weak-signal collection is
  approved.
- `AI_TRENDS_GITHUB_TOKEN` is registered only if authenticated GitHub reads are
  needed and GitHub CLI auth is not available to the cron runtime.
- No secret values appear in repository files, job YAML, docs, logs, or test
  fixtures.

Webhook validation:

- A test Discord webhook POST returns a 2xx status.
- The validation command does not print the webhook URL.
- The target Discord channel receives the validation message.

Cron registration:

- `hermes cron list --all` shows the hourly job `be16c2abaa41` named
  `시간별 AI 트렌드 수집` on `0 * * * *`.
- `hermes cron list --all` shows the daily job `6b96123e2af9` named
  `일간 AI 트렌드 보고` on `0 8 * * *`.
- `hermes cron list --all` shows the weekly job `f612ac984202` named
  `주간 AI 트렌드 보고` on `0 9 * * 1`.
- All three jobs are enabled, non-duplicated, `no_agent=true`, and
  `deliver=local`.
- The registered scripts are `ai-trends-hourly-collector.sh`,
  `ai-trends-daily.sh`, and `ai-trends-weekly.sh` under `$HERMES_HOME/scripts/`.
- `hermes cron run <job-id>` can trigger a controlled test run.
- `hermes cron pause <job-id>` and `hermes cron resume <job-id>` work as
  expected.
- For registered-but-not-running failures, follow the checklist in
  `docs/ai-trends/cron_operations.md`: enabled state, scheduler/gateway
  health, script timeout, script path/permissions, workdir/profile/env,
  `HERMES_BIN`, duplicates, and logs.

## Local dependency-free checklist

A scheduled run is production-ready only when all items are true:

- It succeeds after a clean checkout and environment registration.
- It does not require a browser to be open.
- It does not read browser cookies.
- It does not require manual file downloads.
- It does not read an operator download folder.
- It does not require a pre-populated local cache.
- It does not use workstation-specific absolute paths.
- It does not rely on clipboard contents, screenshots, or manually exported data.
- It can run under the Hermes cron scheduler with the local operator logged out.
- All external access is through RSS, Atom, public APIs, Google Sheets, Discord
  webhook, X bearer token when enabled, or GitHub token when needed.

## Safe test data

Use placeholder domains such as `https://example.invalid/...` in tests and docs.
Never use live webhook URLs, spreadsheet links, bearer tokens, or personal local
paths as test data.
