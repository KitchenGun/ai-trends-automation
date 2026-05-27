from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DAILY_JOB = ROOT / "jobs" / "daily" / "daily_ai_agent_trend_collector.yaml"
HOURLY_JOB = ROOT / "jobs" / "hourly" / "hourly_ai_agent_trend_collector.yaml"
WEEKLY_JOB = ROOT / "jobs" / "weekly" / "weekly_ai_agent_trend_digest.yaml"
X_RSS_ENV_NAMES = {
    "AI_TRENDS_X_RSS_FEEDS_JSON",
    "AI_TRENDS_X_RSS_FEEDS_FILE",
    "AI_TRENDS_X_RSS_FEED_TIMEOUT_SECONDS",
    "AI_TRENDS_X_RSS_TOTAL_BUDGET_SECONDS",
    "AI_TRENDS_X_RSS_FEED_LIMIT",
}
REQUIRED_ENV_NAMES = {
    "AI_TRENDS_SPREADSHEET_ID",
    "AI_TRENDS_DISCORD_WEBHOOK_URL",
    "AI_TRENDS_GITHUB_TOKEN",
    "HERMES_TIMEZONE",
} | X_RSS_ENV_NAMES
COLLECTOR_ENV_NAMES = {
    "AI_TRENDS_SPREADSHEET_ID",
    "AI_TRENDS_GITHUB_TOKEN",
    "HERMES_TIMEZONE",
} | X_RSS_ENV_NAMES


def _load_job(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_daily_job_yaml_parses_and_declares_schedule_env_outputs_and_failure_policy() -> None:
    job = _load_job(DAILY_JOB)

    assert job["name"] == "daily_ai_agent_trend_digest"
    assert job["schedule"]["cron"] == "0 8 * * *"
    assert job["schedule"]["timezone_env"] == "HERMES_TIMEZONE"
    assert set(job["env"]) == REQUIRED_ENV_NAMES
    assert job["outputs"] == ["daily_digest", "discord_daily_summary"]
    assert job["failure_policy"]["spreadsheet_before_discord"] is True
    assert "Discord 전송 전에 중단" in job["failure_policy"]["on_spreadsheet_failure"]
    assert "Discord 전송 실패" in job["failure_policy"]["on_discord_failure"]


def test_hourly_job_yaml_parses_and_declares_schedule_env_outputs_and_failure_policy() -> None:
    job = _load_job(HOURLY_JOB)

    assert job["name"] == "hourly_ai_agent_trend_collector"
    assert job["schedule"]["cron"] == "0 * * * *"
    assert job["schedule"]["timezone_env"] == "HERMES_TIMEZONE"
    assert set(job["env"]) == COLLECTOR_ENV_NAMES
    assert job["outputs"] == ["raw_items"]
    assert job["failure_policy"]["spreadsheet_before_discord"] is True
    assert "다음 시간별 실행에서 재시도" in job["failure_policy"]["on_spreadsheet_failure"]


def test_weekly_job_yaml_parses_and_declares_schedule_env_outputs_and_failure_policy() -> None:
    job = _load_job(WEEKLY_JOB)

    assert job["name"] == "weekly_ai_agent_trend_digest"
    assert job["schedule"]["cron"] == "0 9 * * 1"
    assert job["schedule"]["timezone_env"] == "HERMES_TIMEZONE"
    assert set(job["env"]) == REQUIRED_ENV_NAMES
    assert job["outputs"] == ["weekly_digest", "discord_weekly_summary"]
    assert job["failure_policy"]["spreadsheet_before_discord"] is True
    assert "Discord 전송 전에 중단" in job["failure_policy"]["on_spreadsheet_failure"]
    assert "Discord 전송 실패" in job["failure_policy"]["on_discord_failure"]


def test_job_yaml_does_not_commit_secret_values_or_local_paths() -> None:
    combined = DAILY_JOB.read_text(encoding="utf-8") + HOURLY_JOB.read_text(encoding="utf-8") + WEEKLY_JOB.read_text(encoding="utf-8")
    forbidden_fragments = [
        "discord.com" + "/api/" + "webhooks",
        "discordapp.com" + "/api/" + "webhooks",
        "AI" + "za",
        "sk" + "-",
        "ghp" + "_",
        "github" + "_pat_",
        "Bearer" + " ",
        "docs.google.com" + "/spreadsheets",
        "Downloads" + "/",
        "/" + "Downloads",
        "Desktop" + "/",
        "/" + "Desktop",
        ".cache" + "/",
        "/" + ".cache",
    ]

    for fragment in forbidden_fragments:
        assert fragment not in combined
