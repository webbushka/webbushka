#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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

    # Keep profile output focused on the requested username only.
    filtered: list[dict] = []
    for repo in repos:
        owner = repo.get("owner")
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        if owner_login == username:
            filtered.append(repo)
    if filtered:
        return filtered
    return repos


def n(value: int) -> str:
    return f"{value:,}"


def percentage(part: int, total: int) -> str:
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


def donut_svg(
    cx: int,
    cy: int,
    data: list[tuple[str, int]],
    colors: list[str],
    radius: int = 42,
    width: int = 13,
) -> tuple[str, str]:
    total = sum(v for _, v in data)
    if total <= 0:
        empty = (
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#1e293b" stroke-width="{width}"/>'
            f'<text class="donut-total" x="{cx}" y="{cy + 5}">0</text>'
        )
        return empty, ""

    circumference = 2 * 3.141592653589793 * radius
    offset = 0.0
    arcs: list[str] = []
    legend: list[str] = []
    for i, (label, value) in enumerate(data):
        if value <= 0:
            continue
        frac = value / total
        seg = circumference * frac
        color = colors[i % len(colors)]
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-dasharray="{seg:.2f} {circumference:.2f}" stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        legend.append(
            f'<circle cx="{cx - 54}" cy="{cy + 74 + i * 18}" r="4" fill="{color}"/>'
            f'<text class="legend" x="{cx - 44}" y="{cy + 78 + i * 18}">{escape(label)} {percentage(value, total)}</text>'
        )
        offset += seg

    arcs.append(f'<text class="donut-total" x="{cx}" y="{cy + 5}">{n(total)}</text>')
    return "".join(arcs), "".join(legend)


def build_svg(
    name: str,
    stats: list[tuple[str, str]],
    donut_sets: list[tuple[str, list[tuple[str, int]]]],
    private_mode: bool,
) -> str:
    width = 760
    height = 660
    tile_y = 78
    tile_h = 78
    section_donut_y = 198

    stat_tiles: list[str] = []
    tile_w = 124
    tile_gap = 10
    for i, (label, value) in enumerate(stats):
        x = 36 + i * (tile_w + tile_gap)
        stat_tiles.append(
            f'<rect class="tile" x="{x}" y="{tile_y}" width="{tile_w}" height="{tile_h}" rx="10"/>'
            f'<text class="tile-label" x="{x + 10}" y="{tile_y + 26}">{escape(label)}</text>'
            f'<text class="tile-value" x="{x + 10}" y="{tile_y + 56}">{escape(value)}</text>'
        )

    donuts: list[str] = []
    if donut_sets:
        positions = [(210, 285), (550, 285), (210, 485), (550, 485)]
        for i, (title, data) in enumerate(donut_sets[:4]):
            cx, cy = positions[i]
            donut_arcs, donut_legend = donut_svg(cx, cy, data, PALETTE)
            donuts.append(
                f'<text class="donut-title" x="{cx}" y="{cy - 60}">{escape(title)}</text>'
                f"{donut_arcs}"
                f"{donut_legend}"
            )
    else:
        donuts.append('<text class="muted" x="36" y="310">No breakdown data available yet.</text>')

    stats_svg = "\n  ".join(stat_tiles)
    donuts_svg = "\n  ".join(donuts)
    breakdown_section = "Private Work Breakdown" if private_mode else "Project Breakdown"
    tip_line = (
        ""
        if private_mode
        else '  <text class="muted" x="36" y="638">Tip: add PRIVATE_STATS_TOKEN to include anonymized private-work aggregates.</text>\n'
    )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">GitHub profile stats for {escape(name)}</title>\n'
        '  <desc id="desc">Profile summary with anonymized private-work aggregates generated from the GitHub API.</desc>\n'
        "  <style>\n"
        "    .bg { fill: #0b1220; stroke: #334155; stroke-width: 1; }\n"
        "    .title { fill: #e2e8f0; font: 700 26px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .section { fill: #cbd5e1; font: 700 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; letter-spacing: 0.03em; text-transform: uppercase; }\n"
        "    .tile { fill: #111b2f; stroke: #334155; stroke-width: 1; }\n"
        "    .tile-label { fill: #94a3b8; font: 600 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; letter-spacing: 0.03em; text-transform: uppercase; }\n"
        "    .tile-value { fill: #f8fafc; font: 700 23px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .legend { fill: #cbd5e1; font: 600 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "    .donut-title { fill: #e2e8f0; font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; text-anchor: middle; }\n"
        "    .donut-total { fill: #f8fafc; font: 700 16px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; text-anchor: middle; }\n"
        "    .muted { fill: #64748b; font: 600 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "  </style>\n"
        f'  <rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="14"/>\n'
        f'  <text class="title" x="36" y="52">{escape(name)} - GitHub Stats</text>\n'
        f"  <text class=\"section\" x=\"36\" y=\"{section_donut_y}\">{breakdown_section}</text>\n"
        f"  {stats_svg}\n"
        f"  {donuts_svg}\n"
        f"{tip_line}"
        "</svg>\n"
    )


def main() -> int:
    username = os.getenv("GITHUB_USERNAME")
    if not username:
        print("GITHUB_USERNAME is required", file=sys.stderr)
        return 2

    token = os.getenv("PRIVATE_STATS_TOKEN") or os.getenv("GITHUB_TOKEN")
    user = fetch_user(username, token)
    repos = fetch_repos(username, token)

    public_repos = [repo for repo in repos if not bool(repo.get("private", False))]
    private_repos = [repo for repo in repos if bool(repo.get("private", False))]
    has_private_data = len(private_repos) > 0
    total_stars = sum(int(repo.get("stargazers_count", 0) or 0) for repo in public_repos)

    language_counts: dict[str, int] = {}
    language_source = private_repos if has_private_data else repos
    for repo in language_source:
        language = repo.get("language")
        if isinstance(language, str) and language:
            language_counts[language] = language_counts.get(language, 0) + 1

    top_languages = sorted(language_counts.items(), key=lambda item: item[1], reverse=True)[:6]

    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)

    repo_recent_updates = 0
    forked_repos = 0
    private_touched_30 = 0

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    breakdown_source = private_repos if has_private_data else repos
    for repo in breakdown_source:
        if bool(repo.get("fork", False)):
            forked_repos += 1
        pushed_at = iso_to_datetime(repo.get("pushed_at"))
        if pushed_at and pushed_at >= ninety_days_ago:
            repo_recent_updates += 1
        if pushed_at and pushed_at >= thirty_days_ago:
            private_touched_30 += 1

    total_repos = len(breakdown_source)
    original_repos = max(total_repos - forked_repos, 0)
    stale_repos = max(total_repos - repo_recent_updates, 0)

    archived_repos = sum(1 for repo in breakdown_source if bool(repo.get("archived", False)))
    active_repos = max(total_repos - archived_repos, 0)

    lang_total = sum(count for _, count in top_languages)
    language_donut: list[tuple[str, int]] = top_languages[:4]
    if lang_total > 0:
        other = lang_total - sum(count for _, count in language_donut)
        if other > 0:
            language_donut.append(("Other", other))

    donut_sets = [
        ("Language Mix", language_donut),
        ("Original vs Forked", [("Original", original_repos), ("Forked", forked_repos)]),
        ("Active in 90 Days", [("Updated", repo_recent_updates), ("Older", stale_repos)]),
        ("Archived vs Active", [("Archived", archived_repos), ("Active", active_repos)]),
    ]

    stats = [
        ("Followers", n(int(user.get("followers", 0) or 0))),
        ("Public Repos", n(len(public_repos))),
        ("Private Repos", n(len(private_repos))),
        ("Touched 30d", n(private_touched_30 if has_private_data else repo_recent_updates)),
        ("Total Stars", n(total_stars)),
    ]

    display_name = user.get("name") or username
    svg = build_svg(str(display_name), stats, donut_sets, has_private_data)

    os.makedirs("assets", exist_ok=True)
    output_path = "assets/github-stats.svg"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
