from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("src", "tests", "docs", "jobs")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml"}


SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "google_api_key": re.compile(r"\bAI" + r"za[0-9A-Za-z_-]{35}\b"),
    "discord_webhook": re.compile(
        r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]+"
    ),
}

LOCAL_DEPENDENCY_PATTERNS = {
    "operator_download_or_desktop_path": re.compile(
        r"(/|\\)(Downloads|Desktop)(/|\\)|\b(Downloads|Desktop)(/|\\)", re.IGNORECASE
    ),
    "browser_profile_or_cookie_dependency": re.compile(
        r"Chrome/Default|Firefox/Profiles|User Data/Default|cookies?\.sqlite",
        re.IGNORECASE,
    ),
    "cache_only_path": re.compile(
        r"(/|\\)\.cache(/|\\)|(/|\\)__pycache__(/|\\)|cache-only",
        re.IGNORECASE,
    ),
    "hardcoded_pc_absolute_path": re.compile(
        r"(^|[\s\"'`])([A-Za-z]:\\|/mnt/[a-z]/|/home/[^\s\"'`]+/(?:Downloads|Desktop|Documents))"
    ),
}

ALLOWLISTED_NEGATIVE_POLICY = re.compile(
    r"forbidden_fragments|assert fragment not in combined|Do not |Does not |does not "
    r"|No browser|not require|not read|not use|source policy|secret scan|local dependency",
    re.IGNORECASE,
)


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        scan_root = ROOT / root_name
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            if path.suffix in TEXT_SUFFIXES:
                files.append(path)
    files.extend(path for path in (ROOT / "README.md", ROOT / "pyproject.toml") if path.exists())
    return sorted(files)


def _redacted_location(path: Path, line_number: int, pattern_name: str) -> str:
    return f"{path.relative_to(ROOT)}:{line_number} matched {pattern_name}"


def test_repository_text_files_do_not_contain_secret_like_values() -> None:
    findings: list[str] = []

    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(_redacted_location(path, line_number, pattern_name))

    assert findings == []


def test_repository_has_no_forbidden_local_runtime_dependencies() -> None:
    findings: list[str] = []

    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, pattern in LOCAL_DEPENDENCY_PATTERNS.items():
                if not pattern.search(line):
                    continue
                if path.name in {"test_jobs.py", "test_dependency_hygiene.py"}:
                    continue
                if ALLOWLISTED_NEGATIVE_POLICY.search(line):
                    continue
                findings.append(_redacted_location(path, line_number, pattern_name))

    assert findings == []
