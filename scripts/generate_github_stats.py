#!/usr/bin/env python3
import json
import os
import sys
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE = "https://api.github.com"


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

    while True:
        data = fetch_json(
            f"{API_BASE}/users/{username}/repos?per_page=100&type=owner&sort=updated&page={page}",
            token,
        )
        if not isinstance(data, list):
            raise RuntimeError("Unexpected repos payload from GitHub API")
        if not data:
            break
        repos.extend(repo for repo in data if isinstance(repo, dict))
        page += 1

    return repos


def n(value: int) -> str:
    return f"{value:,}"


def build_svg(name: str, stats: list[tuple[str, str]]) -> str:
    width = 600
    row_height = 56
    top = 88
    left = 36
    right = width // 2 + 8
    height = top + ((len(stats) + 1) // 2) * row_height + 24

    rows = []
    for i, (label, value) in enumerate(stats):
        col_x = left if i % 2 == 0 else right
        row_y = top + (i // 2) * row_height
        rows.append(
            f'''<g transform="translate({col_x},{row_y})">\n'''
            f'''  <text class="label" x="0" y="0">{escape(label)}</text>\n'''
            f'''  <text class="value" x="0" y="30">{escape(value)}</text>\n'''
            f"</g>"
        )

    stats_svg = "\n".join(rows)

    rect_height = height - 1
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">GitHub profile stats for {escape(name)}</title>\n'
        '  <desc id="desc">Snapshot of profile and repository stats generated from the GitHub API.</desc>\n'
        "  <style>\n"
        "    .bg { fill: #0b1220; stroke: #334155; stroke-width: 1; }\n"
        "    .title { fill: #e2e8f0; font: 700 28px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .label { fill: #94a3b8; font: 600 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; letter-spacing: 0.02em; text-transform: uppercase; }\n"
        "    .value { fill: #f8fafc; font: 700 24px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "  </style>\n"
        f'  <rect class="bg" x="0.5" y="0.5" width="599" height="{rect_height}" rx="14"/>\n'
        f'  <text class="title" x="36" y="52">{escape(name)} - GitHub Stats</text>\n'
        f"  {stats_svg}\n"
        "</svg>\n"
    )


def main() -> int:
    username = os.getenv("GITHUB_USERNAME")
    if not username:
        print("GITHUB_USERNAME is required", file=sys.stderr)
        return 2

    token = os.getenv("GITHUB_TOKEN")

    user = fetch_user(username, token)
    repos = fetch_repos(username, token)

    total_stars = sum(int(repo.get("stargazers_count", 0) or 0) for repo in repos)
    total_forks = sum(int(repo.get("forks_count", 0) or 0) for repo in repos)

    stats = [
        ("Followers", n(int(user.get("followers", 0) or 0))),
        ("Following", n(int(user.get("following", 0) or 0))),
        ("Public Repos", n(int(user.get("public_repos", 0) or 0))),
        ("Total Stars", n(total_stars)),
        ("Total Forks", n(total_forks)),
    ]

    display_name = user.get("name") or username
    svg = build_svg(str(display_name), stats)

    os.makedirs("assets", exist_ok=True)
    output_path = "assets/github-stats.svg"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
