# VM Migration Record

2026-05-25 기준 AI Trends cron을 로컬 PC 없이 VM에서 실행하도록 이식했다.

## Copied to VM

- `/home/ubuntu/.hermes/jobs/repos/ai-trends/`
- `/home/ubuntu/.hermes/scripts/ai-trends-hourly-collector.sh`
- `/home/ubuntu/.hermes/scripts/ai-trends-daily.sh`
- `/home/ubuntu/.hermes/scripts/ai-trends-weekly.sh`

## VM environment keys

`/home/ubuntu/.hermes/.env`에는 값이 아니라 아래 key 이름만 운영 문서에 남긴다.

- `AI_TRENDS_SPREADSHEET_ID`
- `AI_TRENDS_DISCORD_WEBHOOK_URL`
- `HERMES_TIMEZONE`
- `HERMES_BIN`

`AI_TRENDS_X_BEARER_TOKEN`, `AI_TRENDS_GITHUB_TOKEN`은 VM에 값이 없으면 optional로 둔다.
GitHub releases는 unauthenticated public API로도 수집 가능하고, X는 token이 있을 때만 weak signal로 수집된다.

## Cron registry changes

Added canonical AI Trends jobs:

- `be16c2abaa41` 시간별 AI 트렌드 수집
- `6b96123e2af9` 일간 AI 트렌드 보고
- `f612ac984202` 주간 AI 트렌드 보고

Paused superseded VM AI trend jobs:

- `39a06670ef7e` Daily AI Agent Trend Collector
- `9c4077153688` Weekly AI Agent Trend Digest

Preserved existing VM-only jobs:

- `274ed1bdf2e5` weekly workout routine draft
- `4eebb276e9b7` queue-watchdog-safe

## Verification

- VM cron gateway: running.
- VM AI Trends scripts: executable.
- VM AI Trends repo: present.
- `pytest tests/ai_trends -q`: 54 passed.
- Manual hourly VM run with `AI_TRENDS_COLLECTION_ITEM_LIMIT=1`: succeeded and appended one row.
