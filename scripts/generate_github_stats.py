#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://api.github.com"
README_PATH = "README.md"
SECTION_START = "<!-- PRIVATE_WORK_HIGHLIGHTS:START -->"
SECTION_END = "<!-- PRIVATE_WORK_HIGHLIGHTS:END -->"


def fetch_json(url: str, token: str | None) -> dict | list:
    req = Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "profile-stats-generator")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error while requesting {url}: {exc}") from exc


def fetch_user(username: str, token: str | None) -> dict:
    data = fetch_json(f"{API_BASE}/users/{username}", token)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected user payload from GitHub API")
    return data


def fetch_repos(username: str, token: str | None) -> list[dict]:
    repos: list[dict] = []
    page = 1
    if token:
        url_tmpl = (
            f"{API_BASE}/user/repos?per_page=100&visibility=all&sort=updated&page={{page}}"
        )
    else:
        url_tmpl = (
            f"{API_BASE}/users/{username}/repos?per_page=100&type=owner&sort=updated&page={{page}}"
        )

    while True:
        data = fetch_json(url_tmpl.format(page=page), token)
        if not isinstance(data, list):
            raise RuntimeError("Unexpected repos payload from GitHub API")
        if not data:
            break
        repos.extend(repo for repo in data if isinstance(repo, dict))
        page += 1

    if token:
        # With an authenticated token, keep all repos returned by /user/repos so
        # org-owned private repos are included in aggregates.
        deduped: list[dict] = []
        seen: set[str] = set()
        for repo in repos:
            full_name = repo.get("full_name")
            if isinstance(full_name, str) and full_name:
                key = full_name
            else:
                key = str(repo.get("id", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(repo)
        return deduped

    # Public API fallback: keep output focused on the requested username.
    filtered: list[dict] = []
    for repo in repos:
        owner = repo.get("owner")
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        if owner_login == username:
            filtered.append(repo)
    return filtered if filtered else repos


def n(value: int) -> str:
    return f"{value:,}"


def pct(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(part / total) * 100:.1f}%"


def iso_to_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_section(
    username: str,
    display_name: str,
    user: dict,
    repos: list[dict],
    generated_at: datetime,
    token_present: bool,
) -> str:
    public_repos = [repo for repo in repos if not bool(repo.get("private", False))]
    private_repos = [repo for repo in repos if bool(repo.get("private", False))]
    source_repos = repos

    total_stars = sum(int(repo.get("stargazers_count", 0) or 0) for repo in public_repos)
    followers = int(user.get("followers", 0) or 0)

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    touched_30 = 0
    touched_90 = 0
    forked = 0
    archived = 0
    language_counts: dict[str, int] = {}

    for repo in source_repos:
        if bool(repo.get("fork", False)):
            forked += 1
        if bool(repo.get("archived", False)):
            archived += 1

        pushed_at = iso_to_datetime(repo.get("pushed_at"))
        if pushed_at and pushed_at >= thirty_days_ago:
            touched_30 += 1
        if pushed_at and pushed_at >= ninety_days_ago:
            touched_90 += 1

        language = repo.get("language")
        if isinstance(language, str) and language:
            language_counts[language] = language_counts.get(language, 0) + 1

    total_source = len(source_repos)
    original = max(total_source - forked, 0)
    active = max(total_source - archived, 0)

    top_languages = sorted(language_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    lang_total = sum(count for _, count in top_languages)
    if lang_total > 0:
        language_mix = ", ".join(
            f"{lang} ({pct(count, lang_total)})" for lang, count in top_languages
        )
    else:
        language_mix = "No dominant language signal yet"

    if token_present:
        source_label = "repositories you can access (public + private, including org-owned repositories)"
    else:
        source_label = "owned repositories (public only)"
    date_str = generated_at.strftime("%Y-%m-%d")

    return (
        f"{SECTION_START}\n"
        "## Work Highlights (Anonymized)\n\n"
        f"Updated: {date_str} UTC\n\n"
        f"- Scope: Aggregated from {source_label} for **{display_name}** (`@{username}`).\n"
        f"- Repositories touched in last 30 days: **{n(touched_30)}**\n"
        f"- Repositories touched in last 90 days: **{n(touched_90)}**\n"
        f"- Original vs forked repos: **{n(original)} / {n(forked)}**\n"
        f"- Active vs archived repos: **{n(active)} / {n(archived)}**\n"
        f"- Language mix (top 5): {language_mix}\n"
        f"- Repo footprint: **{n(len(public_repos))}** public repos, **{n(len(private_repos))}** private repos\n"
        f"- Public stars/followers: **{n(total_stars)}** stars, **{n(followers)}** followers\n\n"
        "_This section is auto-generated daily from GitHub API aggregates and intentionally excludes repo names, PR titles, and code details._\n"
        f"{SECTION_END}\n"
    )


def upsert_readme_section(readme_path: str, section: str) -> bool:
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            current = f.read()
    else:
        current = "# Profile\n\n"

    start_idx = current.find(SECTION_START)
    end_idx = current.find(SECTION_END)

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        end_idx += len(SECTION_END)
        replacement = current[:start_idx].rstrip() + "\n\n" + section
        if end_idx < len(current):
            tail = current[end_idx:].lstrip("\n")
            if tail:
                replacement += "\n" + tail
        new_content = replacement
    else:
        stripped = current.rstrip()
        if stripped:
            new_content = stripped + "\n\n" + section
        else:
            new_content = section

    if new_content == current:
        return False

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def main() -> int:
    username = os.getenv("GITHUB_USERNAME")
    if not username:
        print("GITHUB_USERNAME is required", file=sys.stderr)
        return 2

    token = os.getenv("PRIVATE_STATS_TOKEN") or os.getenv("GITHUB_TOKEN")
    user = fetch_user(username, token)
    repos = fetch_repos(username, token)
    display_name = str(user.get("name") or username)
    generated_at = datetime.now(timezone.utc)

    section = build_section(
        username, display_name, user, repos, generated_at, token_present=bool(token)
    )
    changed = upsert_readme_section(README_PATH, section)
    if changed:
        print(f"Updated {README_PATH}")
    else:
        print(f"No changes to {README_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
