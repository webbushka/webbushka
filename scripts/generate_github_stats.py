#!/usr/bin/env python3
import json
import os
import sys
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://api.github.com"
PALETTE = ["#22d3ee", "#34d399", "#f59e0b", "#f43f5e", "#a78bfa", "#60a5fa"]


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


def percentage(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(part / total) * 100:.1f}%"


def build_svg(
    name: str,
    stats: list[tuple[str, str]],
    languages: list[tuple[str, int]],
    top_repos: list[tuple[str, int]],
) -> str:
    width = 880
    height = 740
    tile_y = 96
    tile_h = 92
    section_lang_y = 236
    lang_bar_y = 268
    lang_legend_start = 312
    section_repo_y = 486
    repo_row_start = 526
    repo_row_step = 42

    stat_tiles: list[str] = []
    tile_w = 152
    for i, (label, value) in enumerate(stats):
        x = 36 + i * (tile_w + 12)
        stat_tiles.append(
            f'<rect class="tile" x="{x}" y="{tile_y}" width="{tile_w}" height="{tile_h}" rx="10"/>'
            f'<text class="tile-label" x="{x + 12}" y="{tile_y + 30}">{escape(label)}</text>'
            f'<text class="tile-value" x="{x + 12}" y="{tile_y + 64}">{escape(value)}</text>'
        )

    lang_total = sum(count for _, count in languages)
    lang_rows: list[str] = []
    lang_x = 36
    lang_y = lang_bar_y
    lang_w = width - 72
    cursor = 0.0
    for i, (language, count) in enumerate(languages[:6]):
        color = PALETTE[i % len(PALETTE)]
        segment_w = (count / lang_total) * lang_w if lang_total else 0
        lang_rows.append(
            f'<rect x="{lang_x + cursor:.2f}" y="{lang_y}" width="{segment_w:.2f}" height="20" fill="{color}" rx="2"/>'
        )
        legend_y = lang_legend_start + i * 26
        lang_rows.append(
            f'<circle cx="{lang_x + 8}" cy="{legend_y - 4}" r="5" fill="{color}"/>'
            f'<text class="legend" x="{lang_x + 22}" y="{legend_y}">{escape(language)} - {percentage(count, lang_total)}</text>'
        )
        cursor += segment_w

    if not languages:
        lang_rows.append('<text class="muted" x="36" y="266">No language data available yet.</text>')

    bars: list[str] = []
    if top_repos:
        max_stars = max(stars for _, stars in top_repos) or 1
        for i, (repo, stars) in enumerate(top_repos):
            y = repo_row_start + i * repo_row_step
            label = repo if len(repo) <= 26 else f"{repo[:23]}..."
            bar_w = (stars / max_stars) * 550
            bars.append(
                f'<text class="repo" x="36" y="{y}">{escape(label)}</text>'
                f'<rect class="bar-bg" x="260" y="{y - 16}" width="550" height="16" rx="8"/>'
                f'<rect class="bar" x="260" y="{y - 16}" width="{bar_w:.2f}" height="16" rx="8"/>'
                f'<text class="bar-value" x="836" y="{y}">{n(stars)}</text>'
            )
    else:
        bars.append(f'<text class="muted" x="36" y="{repo_row_start}">No starred repositories yet.</text>')

    stats_svg = "\n  ".join(stat_tiles)
    languages_svg = "\n  ".join(lang_rows)
    bars_svg = "\n  ".join(bars)

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">GitHub profile stats for {escape(name)}</title>\n'
        '  <desc id="desc">Profile summary with language and top repository charts generated from the GitHub API.</desc>\n'
        "  <style>\n"
        "    .bg { fill: #0b1220; stroke: #334155; stroke-width: 1; }\n"
        "    .title { fill: #e2e8f0; font: 700 30px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .section { fill: #cbd5e1; font: 700 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; letter-spacing: 0.03em; text-transform: uppercase; }\n"
        "    .tile { fill: #111b2f; stroke: #334155; stroke-width: 1; }\n"
        "    .tile-label { fill: #94a3b8; font: 600 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; letter-spacing: 0.03em; text-transform: uppercase; }\n"
        "    .tile-value { fill: #f8fafc; font: 700 28px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .legend { fill: #cbd5e1; font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .repo { fill: #e2e8f0; font: 600 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .bar-bg { fill: #1e293b; }\n"
        "    .bar { fill: #22d3ee; }\n"
        "    .bar-value { fill: #e2e8f0; font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; text-anchor: end; }\n"
        "    .muted { fill: #64748b; font: 600 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "  </style>\n"
        f'  <rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="14"/>\n'
        f'  <text class="title" x="36" y="58">{escape(name)} - GitHub Stats</text>\n'
        f"  <text class=\"section\" x=\"36\" y=\"{section_lang_y}\">Language Breakdown</text>\n"
        f"  <text class=\"section\" x=\"36\" y=\"{section_repo_y}\">Top Repositories by Stars</text>\n"
        f"  {stats_svg}\n"
        f"  {languages_svg}\n"
        f"  {bars_svg}\n"
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

    language_counts: dict[str, int] = {}
    for repo in repos:
        language = repo.get("language")
        if isinstance(language, str) and language:
            language_counts[language] = language_counts.get(language, 0) + 1

    top_languages = sorted(language_counts.items(), key=lambda item: item[1], reverse=True)[:6]

    repo_stars: list[tuple[str, int]] = []
    for repo in repos:
        name = repo.get("name")
        stars = int(repo.get("stargazers_count", 0) or 0)
        if isinstance(name, str):
            repo_stars.append((name, stars))

    top_repos = sorted(repo_stars, key=lambda item: item[1], reverse=True)[:5]

    stats = [
        ("Followers", n(int(user.get("followers", 0) or 0))),
        ("Following", n(int(user.get("following", 0) or 0))),
        ("Public Repos", n(int(user.get("public_repos", 0) or 0))),
        ("Total Stars", n(total_stars)),
        ("Total Forks", n(total_forks)),
    ]

    display_name = user.get("name") or username
    svg = build_svg(str(display_name), stats, top_languages, top_repos)

    os.makedirs("assets", exist_ok=True)
    output_path = "assets/github-stats.svg"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
