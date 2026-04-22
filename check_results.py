"""
check_results.py

Reads completed Premier League fixture JSON from stdin, generates a short
Claude summary for each match, and prints a formatted Slack message to stdout.

Usage:
    echo '<fixtures_json>' | python check_results.py

The input JSON should be either:
  - An array of fixture objects, or
  - An object with a "data" key containing the array (Opticodds envelope).

Fixture objects are expected in the Opticodds v3 format:
  home_team_display, away_team_display, result.scores.home.total, result.scores.away.total

Required environment variables:
  ANTHROPIC_API_KEY  (or ANTHROPIC_BASE_URL if already configured)
"""

import json
import sys
from datetime import date

import anthropic


def load_fixtures(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", [])
    return []


def result_emoji(home: int, away: int) -> str:
    if home > away:
        return ":blue_circle:"
    if home < away:
        return ":red_circle:"
    return ":white_circle:"


def generate_summary(claude: anthropic.Anthropic, home: str, away: str, hs: int, as_: int) -> str:
    if hs > as_:
        outcome = f"{home} won"
    elif hs < as_:
        outcome = f"{away} won"
    else:
        outcome = "The match ended in a draw"

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Write a punchy 2-3 sentence Premier League match summary:\n\n"
                f"  {home} {hs} – {as_} {away}\n"
                f"  Outcome: {outcome}\n\n"
                f"Be enthusiastic and concise. Mention both teams and the scoreline."
            ),
        }],
    )
    return msg.content[0].text.strip()


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: no fixture data on stdin.", file=sys.stderr)
        sys.exit(1)

    fixtures = load_fixtures(raw)
    today = date.today().isoformat()
    claude = anthropic.Anthropic()

    if not fixtures:
        print(f":soccer: *Premier League Results — {today}*\n\nNo completed matches found.")
        return

    print(f"Generating summaries for {len(fixtures)} match(es)...", file=sys.stderr, flush=True)

    lines = [f":soccer: *Premier League Results — {today}*\n"]
    for match in fixtures:
        home = match.get("home_team_display", "Home")
        away = match.get("away_team_display", "Away")
        scores = match.get("result", {}).get("scores", {})
        hs = scores.get("home", {}).get("total", 0)
        as_ = scores.get("away", {}).get("total", 0)

        print(f"  {home} {hs}–{as_} {away}", file=sys.stderr, flush=True)
        summary = generate_summary(claude, home, away, hs, as_)
        lines.append(f"{result_emoji(hs, as_)} *{home} {hs}–{as_} {away}*\n{summary}")

    print("\n\n".join(lines))


if __name__ == "__main__":
    main()
