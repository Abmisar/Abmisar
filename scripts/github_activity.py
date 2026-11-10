#!/usr/bin/env python3
"""Render a public GitHub contribution calendar with the standard library."""

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import os
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import Request, urlopen


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


class PublicCalendar(HTMLParser):
    """Read exact counts from GitHub's accessible contribution tooltips."""

    def __init__(self):
        super().__init__()
        self.tiles = {}
        self.tooltips = {}
        self.active_tooltip = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-date") and "data-level" in attrs:
            self.tiles[attrs["id"]] = attrs
        if tag == "tool-tip" and attrs.get("for"):
            self.active_tooltip = attrs["for"]
            self.tooltips[self.active_tooltip] = ""

    def handle_data(self, text):
        if self.active_tooltip:
            self.tooltips[self.active_tooltip] += text

    def handle_endtag(self, tag):
        if tag == "tool-tip":
            self.active_tooltip = None


def fetch_calendar(username):
    # Fetch without credentials: only counts already visible on the public
    # profile are used. This also supports manual updates without a token.
    request = Request(
        f"https://github.com/users/{quote(username, safe='')}/contributions",
        headers={"Accept-Language": "en-US", "User-Agent": "Abmisar-profile-activity"},
    )
    with urlopen(request, timeout=45) as response:
        html = response.read().decode("utf-8")
    parser = PublicCalendar()
    parser.feed(html)
    if not parser.tiles:
        raise ValueError("GitHub's public calendar contains no contribution days")
    days = []
    for tile_id, tile in parser.tiles.items():
        tooltip = parser.tooltips.get(tile_id, "").strip()
        match = re.match(r"^(No|[\d,]+) contributions?\b", tooltip)
        if not match:
            raise ValueError(f"Cannot read contribution count for {tile['data-date']}")
        count = 0 if match[1] == "No" else int(match[1].replace(",", ""))
        day_date = date.fromisoformat(tile["data-date"])
        days.append({"date": tile["data-date"], "weekday": (day_date.weekday() + 1) % 7,
                     "contributionCount": count,
                     "contributionLevel": LEVELS[int(tile["data-level"])]})
    return [{"contributionDays": days}]


def calendar_days(weeks, today):
    days = []
    seen = set()
    oldest = today - timedelta(days=364)
    first_sunday = oldest - timedelta(days=(oldest.weekday() + 1) % 7)
    for week in weeks:
        for day in week["contributionDays"]:
            day_date = date.fromisoformat(day["date"])
            if day_date > today or day_date < oldest:
                continue
            if day_date in seen:
                raise ValueError("Contribution dates must be unique")
            seen.add(day_date)
            count = day["contributionCount"]
            if not isinstance(count, int) or count < 0:
                raise ValueError("Invalid contribution count")
            days.append({**day, "week": (day_date - first_sunday).days // 7,
                         "parsed_date": day_date})
    days.sort(key=lambda day: day["parsed_date"])
    if len(days) != 365 or days[-1]["parsed_date"] != today:
        raise ValueError("Calendar must contain all 365 days through the current UTC date")
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
    today = datetime.now(timezone.utc).date()
    days = calendar_days(fetch_calendar(args.user), today)
    stats = statistics(days)
    # Prepare both images before touching the last successful output.
    images = {name: render(days, stats, args.user, name) for name in THEMES}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, svg in images.items():
        (args.output / f"activity-{name}.svg").write_text(svg, encoding="utf-8")
    print(f"Rendered {len(days)} days of public contribution activity for {args.user}.")


if __name__ == "__main__":
    main()
