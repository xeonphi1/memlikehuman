"""Record daily public star-count snapshots and render a dependency-free SVG.

Uses GitHub's automatic Actions token; no personal token or external chart service.
Snapshot history starts at the first successful run, not the repository creation date.
"""

import argparse
import html
import json
import os
import re
import tempfile
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path


def render(repo: str, points: list[dict]) -> str:
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="880" height="300" viewBox="0 0 880 300" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(repo)} star trend</title>',
        '<desc id="desc">Daily GitHub star-count snapshots. History begins at the first successful sample.</desc>',
        '<rect width="880" height="300" rx="18" fill="#0c1828"/>',
        '<g font-family="system-ui, sans-serif" fill="#b8cadd">',
        '<text x="36" y="36" font-size="18" fill="#eaf4ff">GitHub stars · daily snapshots</text>',
    ]
    if not points:
        svg.append(
            '<text x="36" y="150" font-size="16">Waiting for the first GitHub snapshot — no historical data yet.</text>'
        )
    else:
        dates = [date.fromisoformat(p["date"]).toordinal() for p in points]
        maximum = max(1, max(p["stars"] for p in points))
        span = max(1, dates[-1] - dates[0])
        coords = [
            (64 + (d - dates[0]) / span * 760, 230 - p["stars"] / maximum * 150)
            for d, p in zip(dates, points, strict=True)
        ]
        for fraction in (0, 0.5, 1):
            y = 230 - 150 * fraction
            svg += [
                f'<path d="M64 {y} H824" stroke="#23394f"/>',
                f'<text x="36" y="{y + 4}" font-size="11">{maximum * fraction:g}</text>',
            ]
        if len(coords) > 1:
            path = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
            svg.append(f'<polyline points="{path}" fill="none" stroke="#5ee0d0" stroke-width="3"/>')
        for x, y in coords:
            svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#5ee0d0"/>')
        svg += [
            f'<text x="64" y="254" font-size="12">{points[0]["date"]}</text>',
            f'<text x="824" y="254" font-size="12" text-anchor="end">{points[-1]["date"]}</text>',
            f'<text x="824" y="36" font-size="18" fill="#5ee0d0" text-anchor="end">{points[-1]["stars"]} stars</text>',
        ]
    svg.append(
        '<text x="36" y="281" font-size="11">Source: GitHub repository API · sampled counts can rise or fall · no reconstructed history</text></g></svg>'
    )
    return "\n".join(svg) + "\n"


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as file:
        file.write(text)
        temporary = Path(file.name)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", "xeonphi1/memlikehuman")
    )
    parser.add_argument("--data", type=Path, default=Path("docs/assets/stars.json"))
    parser.add_argument("--svg", type=Path, default=Path("docs/assets/star-history.svg"))
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise SystemExit("Invalid repository name")
    data = (
        json.loads(args.data.read_text())
        if args.data.exists()
        else {"repository": args.repository, "points": []}
    )
    if data["repository"] != args.repository:
        data = {"repository": args.repository, "points": []}  # Forks start their own history.
    points = data["points"]
    for point in points:
        date.fromisoformat(point["date"])
        if not isinstance(point["stars"], int) or point["stars"] < 0:
            raise SystemExit("Invalid star history")
    if not args.render_only:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "MemLikeHuman-star-chart"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"https://api.github.com/repos/{args.repository}", headers=headers
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            count = json.load(response)["stargazers_count"]
        if not isinstance(count, int) or count < 0:
            raise SystemExit("Invalid star count returned by GitHub")
        today = datetime.now(UTC).date().isoformat()
        points = [p for p in points if p["date"] != today] + [{"date": today, "stars": count}]
    data["points"] = sorted(points, key=lambda p: p["date"])
    atomic_write(args.svg, render(args.repository, data["points"]))
    atomic_write(args.data, json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main()
