# AI Trends Cron Operations

AI Trends는 Hermes Cron의 `no_agent` 스크립트 작업 3개로 운영됩니다. 작업은 Hermes Cron 레지스트리(`$HERMES_HOME/cron/jobs.json`)에 등록되어 있고, 실제 실행은 `$HERMES_HOME/scripts/` 아래 wrapper script가 담당합니다.

사용자에게 보이는 운영 상태와 복구 절차는 한국어로 기록합니다. 문서와 로그에는 token, webhook URL, spreadsheet ID 같은 secret 값을 넣지 마세요. 필요한 경우 환경 변수 이름과 `SET`/`MISSING` 상태만 기록합니다.

## 현재 등록된 Cron 작업

2026-05-24 검증 기준 등록 상태입니다.

| 용도 | Job ID | Stable name | Schedule | Timezone | Script | Hermes Cron 설정 | 기대 동작 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 시간별 수집 | `be16c2abaa41` | `시간별 AI 트렌드 수집` | `0 * * * *` | `HERMES_TIMEZONE` 또는 Hermes 기본 timezone | `ai-trends-hourly-collector.sh` | `enabled=true`, `no_agent=true`, `deliver=local`, profile 기본값, workdir 기본값 | 공개 AI-agent trend source를 수집/중복제거하고 `raw_items`에 저장합니다. Hermes 평가와 Discord 보고는 하지 않습니다. |
| 일간 보고 | `6b96123e2af9` | `일간 AI 트렌드 보고` | `0 8 * * *` | `HERMES_TIMEZONE` 또는 Hermes 기본 timezone | `ai-trends-daily.sh` | `enabled=true`, `no_agent=true`, `deliver=local`, profile 기본값, workdir 기본값 | 최근 raw item을 일간 digest로 저장한 뒤 Discord에 `일간 AI 트렌드 보고` 메시지를 보냅니다. |
| 주간 보고 | `f612ac984202` | `주간 AI 트렌드 보고` | `0 9 * * 1` | `HERMES_TIMEZONE` 또는 Hermes 기본 timezone | `ai-trends-weekly.sh` | `enabled=true`, `no_agent=true`, `deliver=local`, profile 기본값, workdir 기본값 | 주간 digest를 저장한 뒤 Discord에 `주간 AI 트렌드 보고` 메시지를 보냅니다. |

Script 경로는 Hermes Cron registry의 `script` 값 기준입니다. 현재 값은 파일명만 저장되어 있으므로 Hermes는 `$HERMES_HOME/scripts/<script>`로 실행합니다.

관련 schedule 선언 파일은 repository 안에 유지됩니다.

- `jobs/hourly/hourly_ai_agent_trend_collector.yaml`
- `jobs/daily/daily_ai_agent_trend_collector.yaml`
- `jobs/weekly/weekly_ai_agent_trend_digest.yaml`

## Wrapper script가 하는 일

세 wrapper는 같은 운영 패턴을 따릅니다.

1. `HERMES_HOME`을 기본값 `$HOME/.hermes`로 설정합니다.
2. `AI_TRENDS_REPO_DIR`이 없으면 `$HERMES_HOME/jobs/repos/ai-trends`를 project directory로 사용합니다.
3. `HERMES_JOBS_ENV`가 있으면 그 파일을, 없으면 `$HERMES_HOME/.env`를 로드합니다.
4. 필수 환경 변수가 없으면 secret 값을 출력하지 않고 `NEEDS_USER_INPUT`과 필요한 변수명만 출력합니다.
5. `PYTHONPATH`에 project `src`를 추가합니다.
6. `HERMES_TIMEZONE` 기본값을 `Asia/Seoul`로 둡니다.
7. 가능한 경우 `$HERMES_HOME/hermes-agent/venv/bin/python`을 사용해 Python module을 실행합니다.

Wrapper별 Python entrypoint:

```bash
# 시간별
python -m ai_trends.collector

# 일간
python -m ai_trends.daily

# 주간
python -m ai_trends.weekly
```

## Required environment variables

Cron profile에 아래 이름을 등록합니다. 값은 문서, job YAML, git tracked file, Kanban handoff에 기록하지 마세요.

| Name | Required | Notes |
| --- | --- | --- |
| `AI_TRENDS_SPREADSHEET_ID` | Yes | Google Sheets spreadsheet ID. 실제 값은 secret입니다. |
| `AI_TRENDS_DISCORD_WEBHOOK_URL` | Yes for daily/weekly | Discord webhook URL. 실제 값은 secret입니다. |
| `HERMES_TIMEZONE` | Recommended | IANA timezone. 미설정 시 wrapper는 `Asia/Seoul`을 사용합니다. |
| `HERMES_HOME` | Runtime default | 기본값은 `$HOME/.hermes`입니다. Scheduler와 수동 실행에서 같은 값을 쓰는지 확인합니다. |
| `AI_TRENDS_REPO_DIR` | Optional | 기본값은 `$HERMES_HOME/jobs/repos/ai-trends`입니다. Repository를 다른 위치에서 실행할 때만 설정합니다. |
| `HERMES_JOBS_ENV` | Optional | 기본값은 `$HERMES_HOME/.env`입니다. 별도 env file을 쓸 때만 설정합니다. |
| `HERMES_BIN` | Recommended when scoring/summarizing with Hermes CLI | Hermes CLI 실행 파일의 안전한 절대 경로입니다. Scheduler 환경에서 `hermes`가 잘못 resolve되면 시간별/주간 실행이 실패할 수 있습니다. |
| `HERMES_PYTHON` | Optional | Python 실행 파일 override. 기본 Hermes venv Python이 있으면 wrapper가 자동 사용합니다. |
| `AI_TRENDS_X_BEARER_TOKEN` | Optional | X를 weak signal source로 승인했을 때만 설정합니다. |
| `AI_TRENDS_X_RSS_FEEDS_JSON` | Optional | 공개 RSS/Atom feed URL 목록을 JSON으로 직접 지정할 때만 설정합니다. Secret을 넣지 않습니다. |
| `AI_TRENDS_X_RSS_FEEDS_FILE` | Optional | 공개 RSS/Atom feed URL 목록 파일 경로입니다. VM 기본값은 `/home/ubuntu/.hermes/jobs/config/ai-trends-x-rss-feeds.json`입니다. |
| `AI_TRENDS_X_RSS_FEED_TIMEOUT_SECONDS` | Optional | feed별 fetch timeout입니다. |
| `AI_TRENDS_X_RSS_TOTAL_BUDGET_SECONDS` | Optional | X RSS 전체 fetch budget입니다. |
| `AI_TRENDS_X_RSS_FEED_LIMIT` | Optional | feed별 최대 항목 수입니다. |
| `AI_TRENDS_GITHUB_TOKEN` | Optional | GitHub API rate limit 때문에 인증 read가 필요할 때만 설정합니다. 미설정 시 cron runtime의 `gh auth token`을 사용할 수 있습니다. |
| `GOOGLE_APPLICATION_CREDENTIALS` 또는 `GOOGLE_SERVICE_ACCOUNT_JSON` | Optional, environment-dependent | Google Sheets adapter가 service account를 요구할 때 사용합니다. OAuth 기반 Google Workspace integration을 쓰면 없을 수 있습니다. |

2026-05-24 handoff의 redacted readiness: `AI_TRENDS_SPREADSHEET_ID=SET`, `AI_TRENDS_DISCORD_WEBHOOK_URL=SET`, `GOOGLE_APPLICATION_CREDENTIALS=MISSING`, `GOOGLE_SERVICE_ACCOUNT_JSON=MISSING`, `HERMES_HOME=SET(runtime default)`.

## Hermes Cron 운영 명령

아래 명령은 secret 값을 출력하지 않습니다. job 상세를 공유할 때도 spreadsheet ID, webhook URL, token 값은 제거하세요.

List all jobs, including paused jobs:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron list --all
```

Check scheduler health:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron status
```

Run one job on the next scheduler tick:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron run be16c2abaa41
HERMES_HOME=/home/kang/.hermes hermes cron run 6b96123e2af9
HERMES_HOME=/home/kang/.hermes hermes cron run f612ac984202
```

Pause a job:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron pause be16c2abaa41
HERMES_HOME=/home/kang/.hermes hermes cron pause 6b96123e2af9
HERMES_HOME=/home/kang/.hermes hermes cron pause f612ac984202
```

Resume a job:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron resume be16c2abaa41
HERMES_HOME=/home/kang/.hermes hermes cron resume 6b96123e2af9
HERMES_HOME=/home/kang/.hermes hermes cron resume f612ac984202
```

Remove a superseded duplicate only after confirming it is not one of the canonical IDs above:

```bash
HERMES_HOME=/home/kang/.hermes hermes cron remove <duplicate-job-id>
```

## 수동 wrapper 실행

Scheduler 문제인지 application 문제인지 분리할 때 wrapper를 직접 실행합니다.

```bash
HERMES_HOME=/home/kang/.hermes \
AI_TRENDS_REPO_DIR=/home/kang/.hermes/jobs/repos/ai-trends \
/home/kang/.hermes/scripts/ai-trends-hourly-collector.sh
```

```bash
HERMES_HOME=/home/kang/.hermes \
AI_TRENDS_REPO_DIR=/home/kang/.hermes/jobs/repos/ai-trends \
/home/kang/.hermes/scripts/ai-trends-daily.sh
```

```bash
HERMES_HOME=/home/kang/.hermes \
AI_TRENDS_REPO_DIR=/home/kang/.hermes/jobs/repos/ai-trends \
/home/kang/.hermes/scripts/ai-trends-weekly.sh
```

Expected output:

- 시간별: 성공 시 raw item 저장 로그가 출력되고 별도 Discord 상태는 없습니다. score 컬럼은 비워 둡니다.
- 일간: 성공 또는 dry-run/skip 상태에서 `일간 AI 트렌드 보고 완료: Discord 상태=<status>` 형식의 한국어 완료 문구가 출력됩니다.
- 주간: 성공 또는 skip 상태에서 `주간 AI 트렌드 보고` 관련 완료/상태 문구가 출력됩니다.
- 필수 환경 변수가 없으면 `NEEDS_USER_INPUT`과 변수명만 출력됩니다. Secret 값은 출력되면 안 됩니다.

## 등록되어 있지만 실행되지 않을 때 복구 체크리스트

아래 순서대로 확인합니다.

1. Job이 canonical ID로 한 번씩만 등록되어 있는지 확인합니다.

   ```bash
   HERMES_HOME=/home/kang/.hermes hermes cron list --all
   ```

   기대값:
   - `be16c2abaa41` / `시간별 AI 트렌드 수집` / `0 * * * *` / enabled
   - `6b96123e2af9` / `일간 AI 트렌드 보고` / `0 8 * * *` / enabled
   - `f612ac984202` / `주간 AI 트렌드 보고` / `0 9 * * 1` / enabled

2. Paused/disabled 상태인지 확인합니다.
   - `enabled=false`이면 `hermes cron resume <job-id>`로 복구합니다.
   - 중복 job이 있으면 canonical ID가 아닌 job만 제거하거나 pause합니다.

3. Scheduler/gateway 상태를 확인합니다.

   ```bash
   HERMES_HOME=/home/kang/.hermes hermes cron status
   HERMES_HOME=/home/kang/.hermes hermes gateway status
   ```

   Gateway 또는 cron ticker가 꺼져 있으면 scheduled window를 놓친 뒤 다음 실행 시간이 fast-forward될 수 있습니다. 이 경우 gateway를 재시작하고 다음 due time 또는 `hermes cron run <job-id>`로 검증합니다.

4. Cron script timeout을 확인합니다.
   - 시간별 수집은 source fetch와 Hermes 평가 때문에 기본 120초를 넘을 수 있습니다.
   - 현재 repair 값은 `/home/kang/.hermes/config.yaml`의 `cron.script_timeout_seconds: 300`입니다.
   - timeout error가 다시 발생하면 runtime을 줄이거나 timeout을 조정합니다. 예: `AI_TRENDS_COLLECTION_ITEM_LIMIT`를 낮추거나 evaluator 호출 수를 줄입니다.

5. Script path와 실행 권한을 확인합니다.

   ```bash
   bash -n /home/kang/.hermes/scripts/ai-trends-hourly-collector.sh
   bash -n /home/kang/.hermes/scripts/ai-trends-daily.sh
   bash -n /home/kang/.hermes/scripts/ai-trends-weekly.sh
   test -x /home/kang/.hermes/scripts/ai-trends-hourly-collector.sh
   test -x /home/kang/.hermes/scripts/ai-trends-daily.sh
   test -x /home/kang/.hermes/scripts/ai-trends-weekly.sh
   ```

6. Workdir/profile/env mismatch를 확인합니다.
   - Cron registry의 현재 AI Trends job은 `workdir=null`, `profile=null`, `deliver=local`, `no_agent=true`입니다.
   - Wrapper가 `AI_TRENDS_REPO_DIR` 또는 `$HERMES_HOME/jobs/repos/ai-trends`를 사용하므로 scheduler와 수동 실행의 `HERMES_HOME`이 같아야 합니다.
   - Cron profile에서 `.env` 또는 `HERMES_JOBS_ENV`가 읽히는지 확인합니다. 값은 출력하지 말고 `SET`/`MISSING`만 기록합니다.

7. Hermes CLI path 문제를 확인합니다.
   - 시간별 scoring과 주간 summary는 내부에서 Hermes CLI를 호출할 수 있습니다.
   - `PermissionError: [Errno 13] Permission denied: 'hermes'`가 보이면 scheduler 환경의 `HERMES_BIN` 또는 `PATH`가 잘못된 것입니다.
   - 복구: `HERMES_BIN`을 실행 가능한 Hermes CLI 절대 경로로 설정합니다. 예: operator 환경에서 `command -v hermes`로 확인한 실행 파일 경로를 env에 등록합니다.
   - 값 검증은 `test -x "$HERMES_BIN"`처럼 실행 가능 여부만 확인하고 경로에 secret이 포함되지 않게 합니다.

8. Logs를 확인합니다.
   - Hermes cron/gateway 로그: `/home/kang/.hermes/logs/`
   - Application 출력은 `hermes cron list --all`의 `last_status`, `last_error`, `last_run_at`, `next_run_at`과 함께 확인합니다.
   - 로그 공유 시 webhook URL, spreadsheet ID, OAuth token, bearer token, browser cookie/cache path를 제거합니다.

## Operational failure policy

- 시간별 수집기는 `raw_items`만 쓰며 Hermes scoring이나 별도 Discord 보고를 보내지 않습니다.
- 일간 AI 트렌드 보고의 스프레드시트 쓰기는 일간 Discord 전송보다 먼저 실행됩니다.
- 주간 AI 트렌드 보고의 스프레드시트 쓰기는 주간 Discord 전송보다 먼저 실행됩니다.
- User-facing daily/weekly Discord headings must stay Korean: `일간 AI 트렌드 보고`, `주간 AI 트렌드 보고`.
- Spreadsheet failures abort before Discord, so no Discord message should claim a digest that was not stored.
- Discord failures leave spreadsheet rows in place and update only the Discord status/error fields.
- Error fields must contain safe operational text, not webhook URLs or token values.

## Local-machine independence checklist

A production cron run must be independent of an operator's local PC state:

- Does not require an open browser session.
- Does not read browser cookies.
- Does not depend on files manually downloaded by an operator.
- Does not depend on an operator-specific download folder.
- Does not depend on a local cache directory being warm.
- Does not use absolute paths from a developer workstation.
- Uses environment variables and service/API credentials registered for the cron-running profile.
- Can be run after a clean checkout plus secret registration.
