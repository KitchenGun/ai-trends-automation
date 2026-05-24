# AI Trends Discord Templates

The automation sends plain Discord webhook messages. Messages are Markdown text
only, capped at 1900 characters so they stay below Discord content limits.

## Delivery contract

- The Discord webhook URL comes from `AI_TRENDS_DISCORD_WEBHOOK_URL`.
- The webhook URL is never written to logs, spreadsheet status columns, or docs.
- A successful webhook response marks the digest row `sent` and records
  `discord_sent_at`.
- A failed webhook response marks the digest row `failed` and records a safe error
  such as `Discord webhook returned HTTP 500: upstream discord error`.

## Daily message / 일간 보고

Template:

```text
## 일간 AI 트렌드 보고 — <digest_date>
<summary>

1. **<item title>**
   링크: <item url>
   점수: 관련성 <relevance_score>/10; 중요도 <importance_score>/10
   근거: <score_rationale>
2. **<item title>**
   링크: <item url>
   점수: 관련성 <relevance_score>/10; 중요도 <importance_score>/10
   근거: <score_rationale>
```

Example:

```text
## 일간 AI 트렌드 보고 — 2026-05-22
일간 AI 에이전트 트렌드 보고: 총 2개 항목을 다룹니다. 주요 항목: Agent framework release, MCP tool update.

1. **Agent framework release**
   링크: https://example.invalid/agent-framework-release
   점수: 관련성 9/10; 중요도 8/10
   근거: Official release with concrete workflow impact for agent builders.
2. **MCP tool update**
   링크: https://example.invalid/mcp-tool-update
   점수: 관련성 8/10; 중요도 7/10
   근거: Adds integration surface that affects agent tooling adoption.
```

## Weekly message / 주간 보고

Template:

```text
## 주간 AI 트렌드 보고 — <week_start> ~ <week_end>
<summary>

1. **<item title>**
   링크: <item url>
   점수: 관련성 <relevance_score>/10; 중요도 <importance_score>/10
   근거: <score_rationale>
2. **<item title>**
   링크: <item url>
   점수: 관련성 <relevance_score>/10; 중요도 <importance_score>/10
   근거: <score_rationale>
```

Example:

```text
## 주간 AI 트렌드 보고 — 2026-05-18 ~ 2026-05-24
이번 주는 AI 에이전트 개발자를 위한 에이전트 오케스트레이션, 도구 상호운용성, 운영 안정성 개선에 초점을 맞췄습니다.

1. **Agent orchestration release**
   링크: https://example.invalid/orchestration-release
   점수: 관련성 10/10; 중요도 9/10
   근거: Official release directly changes how teams coordinate autonomous agents.
2. **Reliability postmortem**
   링크: https://example.invalid/reliability-postmortem
   점수: 관련성 8/10; 중요도 8/10
   근거: Public incident details provide operational lessons for agent deployments.
```

## Message quality checklist

Before enabling live delivery, confirm:

- Each item includes title, link, relevance score, importance score, and rationale.
- The summary is useful without opening the spreadsheet.
- Messages do not include raw webhook URLs, API tokens, spreadsheet secrets, or
  operator-local paths.
- Messages remain readable when truncated with an ellipsis.
- Discord failure text is safe to store in `discord_error`.
- User-facing daily/weekly headings must stay Korean (`일간 AI 트렌드 보고`, `주간 AI 트렌드 보고`).
