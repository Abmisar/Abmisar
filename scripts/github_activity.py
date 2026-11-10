#!/usr/bin/env python3
"""Render a public GitHub contribution calendar with the standard library."""

import argparse
from datetime import date, datetime, timezone
from html import escape
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays { date weekday contributionCount contributionLevel }
        }
      }
    }
  }
}
"""

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "text": "#c9d1d9",
        "muted": "#8b949e", "accent": "#58a6ff",
        "colors": ["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328",
        "muted": "#59636e", "accent": "#0969da",
        "colors": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
}
LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]


def fetch_calendar(username, token):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": username}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "Abmisar-profile-activity"},
    )
    with urlopen(request, timeout=45) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL: " + "; ".join(e["message"] for e in result["errors"]))
    user = result["data"]["user"]
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")
    return user["contributionsCollection"]["contributionCalendar"]["weeks"]


def calendar_days(weeks, today):
    days = []
    seen = set()
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            day_date = date.fromisoformat(day["date"])
            if day_date > today:
                continue
            if day_date in seen:
                raise ValueError("Contribution dates must be unique")
            seen.add(day_date)
            count = day["contributionCount"]
            if not isinstance(count, int) or count < 0:
                raise ValueError("Invalid contribution count")
            days.append({**day, "week": week_index, "parsed_date": day_date})
    days.sort(key=lambda day: day["parsed_date"])
    if not days or days[-1]["parsed_date"] != today:
        raise ValueError("Calendar must include the current UTC date")
    if any((right["parsed_date"] - left["parsed_date"]).days != 1
           for left, right in zip(days, days[1:])):
        raise ValueError("Contribution dates must be consecutive")
    return days


def statistics(days):
    values = [day["contributionCount"] for day in days]
    best = run = 0
    for value in values:
        run = run + 1 if value else 0
        best = max(best, run)
    # An empty, still-in-progress day does not end yesterday's streak.
    current = 0
    for value in reversed(values[:-1] if not values[-1] else values):
        if not value:
            break
        current += 1
    return {"total": sum(values), "best": best, "current": current,
            "max": max(values), "average": sum(values) / len(values)}


def shade(color, factor):
    channels = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(channel * factor):02x}" for channel in channels)


def render(days, stats, username, theme_name):
    theme = THEMES[theme_name]
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="740" '
        'viewBox="0 0 1120 740" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(username)} — GitHub contribution activity</title>',
        f'<desc id="description">{stats["total"]:,} contributions from {days[0]["date"]} '
        f'to {days[-1]["date"]}. Current streak: {stats["current"]} days; '
        f'best streak in this period: {stats["best"]} days. '
        'Activity includes contributions visible on the public profile.</desc>',
        f'<rect x="1" y="1" width="1118" height="738" rx="10" '
        f'fill="{theme["bg"]}" stroke="{theme["border"]}" stroke-width="2"/>',
        '<g font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif">',
    ]

    def text(x, y, value, size=20, color="text", weight=400, anchor="start"):
        svg.append(f'<text x="{x}" y="{y}" fill="{theme[color]}" '
                   f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
                   f'{escape(str(value))}</text>')

    text(40, 54, "Contributions calendar", 30, "accent", 600)
    text(40, 87, f'{days[0]["date"]} — {days[-1]["date"]}', 17, "muted")
    text(40, 121, f'{stats["total"]:,} contributions', 21)
    text(658, 133, "Contribution streaks", 24, "accent", 500)
    text(658, 174, "Current streak", 21, "muted")
    text(1065, 174, f'{stats["current"]} days', 24, anchor="end")
    text(658, 214, "Best in this period", 21, "muted")
    text(1065, 214, f'{stats["best"]} days', 24, anchor="end")
    text(658, 277, "Contributions per day", 24, "accent", 500)
    text(658, 318, "Highest in a day", 21, "muted")
    text(1065, 318, f'{stats["max"]:,}', 24, anchor="end")
    text(658, 358, "Daily average", 21, "muted")
    text(1065, 358, f'{stats["average"]:.2f}', 24, anchor="end")

    def polygon(points, fill):
        points_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        svg.append(f'<polygon points="{points_text}" fill="{fill}"/>')

    # Draw back to front so the elevated blocks overlap naturally.
    ordered = sorted(days, key=lambda day: day["week"] + day["weekday"])
    for day in ordered:
        x = 155 + day["week"] * 16.8 - day["weekday"] * 16.8
        y = 181 + (day["week"] + day["weekday"]) * 8.4
        count = day["contributionCount"]
        height = 5 + 67 * (count / max(stats["max"], 1)) ** 0.65 if count else 0
        color = theme["colors"][LEVELS.index(day["contributionLevel"])]
        a, b = 8, 4
        svg.append(f'<g><title>{day["date"]}: {count} contributions</title>')
        if height:
            polygon([(x-a, y+b-height), (x, y+2*b-height),
                     (x, y+2*b), (x-a, y+b)], shade(color, 0.66))
            polygon([(x, y+2*b-height), (x+a, y+b-height),
                     (x+a, y+b), (x, y+2*b)], shade(color, 0.82))
        polygon([(x, y-height), (x+a, y+b-height),
                 (x, y+2*b-height), (x-a, y+b-height)], color)
        svg.append('</g>')

    text(40, 713, "Height represents daily contributions · GitHub public profile", 16, "muted")
    text(827, 713, "Less", 16, "muted")
    for index, color in enumerate(theme["colors"]):
        svg.append(f'<rect x="{870 + index * 26}" y="698" width="18" height="18" '
                   f'rx="3" fill="{color}"/>')
    text(1009, 713, "More", 16, "muted")
    svg.extend(['</g>', '</svg>'])
    return "\n".join(svg) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("GITHUB_USER", "Abmisar"))
    parser.add_argument("--output", type=Path, default=Path("assets"))
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        parser.error("GH_TOKEN is required; GitHub Actions supplies its repository token")
    today = datetime.now(timezone.utc).date()
    days = calendar_days(fetch_calendar(args.user, token), today)
    stats = statistics(days)
    # Prepare both images before touching the last successful output.
    images = {name: render(days, stats, args.user, name) for name in THEMES}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, svg in images.items():
        (args.output / f"activity-{name}.svg").write_text(svg, encoding="utf-8")
    print(f"Rendered {len(days)} days of public contribution activity for {args.user}.")


if __name__ == "__main__":
    main()
