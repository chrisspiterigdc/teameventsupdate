"""
check_results.py

Reads completed Premier League fixture JSON from stdin (Opticodds v3 format),
generates a ~200-word editorial "current situation" blurb for each team via
Claude, and prints one JSON object per line to stdout for the Slack connector
to post.

Usage:
    echo '<fixtures_json>' | python check_results.py

Input: Opticodds envelope {"data": [...]} or bare array of fixture objects.
Output: newline-delimited JSON, one object per team message:
    {"team": "Arsenal FC", "message": "..."}

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


def result_label(team_score: int, opp_score: int) -> str:
    if team_score > opp_score:
        return "WIN"
    if team_score < opp_score:
        return "LOSS"
    return "DRAW"


def build_prompt(team: str, opponent: str, team_score: int, opp_score: int,
                 venue: str, match_date: str) -> str:
    result = result_label(team_score, opp_score)
    home_away = "at home" if venue else ""
    return f"""Write a short editorial piece (~200 words, 4 paragraphs) for {team}'s section on a sports betting website.

Match just played ({match_date}): {team} {team_score}–{opp_score} {opponent} {home_away} — {result}

The piece should cover:
1. The result and what it means for the team right now
2. Their broader season situation (form, league position, any cup runs)
3. Historical or contextual detail that's relevant
4. A forward-looking line about what comes next

Tone: authoritative football journalist, engaging but factual.
Format: Start with the heading "Latest {team} News" on its own line, then a punchy one-line sub-headline (question or statement), then 3–4 short paragraphs.
Constraint: Only include facts you are genuinely confident are accurate. Do not fabricate statistics, scorelines, or events."""


def generate_blurb(claude: anthropic.Anthropic, team: str, opponent: str,
                   team_score: int, opp_score: int, venue: str, match_date: str) -> str:
    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": build_prompt(team, opponent, team_score, opp_score, venue, match_date),
        }],
    )
    return msg.content[0].text.strip()


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: no fixture data on stdin.", file=sys.stderr)
        sys.exit(1)

    fixtures = load_fixtures(raw)
    if not fixtures:
        print("No fixtures found in input.", file=sys.stderr)
        sys.exit(0)

    claude = anthropic.Anthropic()

    for match in fixtures:
        home = match.get("home_team_display", "")
        away = match.get("away_team_display", "")
        scores = match.get("result", {}).get("scores", {})
        hs = scores.get("home", {}).get("total", 0)
        as_ = scores.get("away", {}).get("total", 0)
        venue = match.get("venue_name", "")
        match_date = (match.get("start_date") or "")[:10]

        for team, opponent, ts, os_, at_home in [
            (home, away, hs, as_, True),
            (away, home, as_, hs, False),
        ]:
            print(f"Generating: {team}", file=sys.stderr, flush=True)
            blurb = generate_blurb(
                claude, team, opponent, ts, os_,
                venue if at_home else "",
                match_date,
            )
            print(json.dumps({"team": team, "message": blurb}))


if __name__ == "__main__":
    main()
