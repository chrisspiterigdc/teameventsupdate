#!/usr/bin/env python3
"""
Premier League match results checker.
Fetches today's completed matches, generates supporter summaries via Claude,
and posts them to Slack (or stdout when no SLACK_BOT_TOKEN is set).
"""

import os
import sys
from datetime import date

import requests
import anthropic
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#match-results")
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY")

# The Premier League has 20 clubs per season; this list covers the 2025-26 season.
PREMIER_LEAGUE_TEAMS = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton & Hove Albion",
    "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich Town",
    "Leicester City", "Liverpool", "Manchester City", "Manchester United",
    "Newcastle United", "Nottingham Forest", "Southampton", "Tottenham Hotspur",
    "West Ham United", "Wolverhampton Wanderers",
]

# Alternate name mapping for API responses that use shortened names
TEAM_ALIASES = {
    "Brighton": "Brighton & Hove Albion",
    "Wolves": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Man Utd": "Manchester United",
    "Newcastle": "Newcastle United",
    "Nottm Forest": "Nottingham Forest",
    "West Ham": "West Ham United",
    "Leicester": "Leicester City",
}


def canonical(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def fetch_todays_matches(today: str) -> list:
    """Return finished Premier League matches for today from football-data.org or mock data."""
    if not FOOTBALL_DATA_API_KEY:
        print("FOOTBALL_DATA_API_KEY not set — using mock match data.\n")
        return _mock_matches(today)

    url = (
        "https://api.football-data.org/v4/competitions/PL/matches"
        f"?dateFrom={today}&dateTo={today}&status=FINISHED"
    )
    try:
        resp = requests.get(url, headers={"X-Auth-Token": FOOTBALL_DATA_API_KEY}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except requests.RequestException as exc:
        print(f"Football API error ({exc}) — falling back to mock data.\n")
        return _mock_matches(today)


def _mock_matches(today: str) -> list:
    """Plausible fixtures for a mid-April matchday."""
    return [
        {
            "homeTeam": {"name": "Arsenal"},
            "awayTeam": {"name": "Chelsea"},
            "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
            "status": "FINISHED",
            "utcDate": f"{today}T15:00:00Z",
        },
        {
            "homeTeam": {"name": "Liverpool"},
            "awayTeam": {"name": "Manchester City"},
            "score": {"fullTime": {"home": 3, "away": 2}, "halfTime": {"home": 1, "away": 1}},
            "status": "FINISHED",
            "utcDate": f"{today}T17:30:00Z",
        },
        {
            "homeTeam": {"name": "Tottenham Hotspur"},
            "awayTeam": {"name": "Manchester United"},
            "score": {"fullTime": {"home": 1, "away": 1}, "halfTime": {"home": 0, "away": 1}},
            "status": "FINISHED",
            "utcDate": f"{today}T15:00:00Z",
        },
        {
            "homeTeam": {"name": "Aston Villa"},
            "awayTeam": {"name": "Newcastle United"},
            "score": {"fullTime": {"home": 0, "away": 2}, "halfTime": {"home": 0, "away": 1}},
            "status": "FINISHED",
            "utcDate": f"{today}T15:00:00Z",
        },
        {
            "homeTeam": {"name": "Everton"},
            "awayTeam": {"name": "West Ham United"},
            "score": {"fullTime": {"home": 2, "away": 0}, "halfTime": {"home": 1, "away": 0}},
            "status": "FINISHED",
            "utcDate": f"{today}T15:00:00Z",
        },
    ]


def generate_supporter_summary(team: str, match: dict, client: anthropic.Anthropic) -> str:
    home = canonical(match["homeTeam"]["name"])
    away = canonical(match["awayTeam"]["name"])
    hg = match["score"]["fullTime"]["home"]
    ag = match["score"]["fullTime"]["away"]
    ht_h = match["score"]["halfTime"]["home"]
    ht_a = match["score"]["halfTime"]["away"]

    is_home = team == home
    opponent = away if is_home else home
    team_goals = hg if is_home else ag
    opp_goals = ag if is_home else hg
    venue = "home" if is_home else "away"

    if team_goals > opp_goals:
        result, emoji = "WIN", "🎉"
    elif team_goals == opp_goals:
        result, emoji = "DRAW", "🤝"
    else:
        result, emoji = "LOSS", "😞"

    prompt = (
        f"Write a 2-3 sentence match summary for supporters of {team}. "
        f"Match: {home} {hg}-{ag} {away} (HT: {ht_h}-{ht_a}). "
        f"{team} played {venue} and got a {result} ({team_goals}-{opp_goals} vs {opponent}). "
        "Be passionate and honest. No excessive punctuation or emoji."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = msg.content[0].text.strip()
    return f"{emoji} *{team}* — {result} {team_goals}-{opp_goals} vs {opponent}\n{summary}"


def post(text: str, slack: WebClient | None) -> None:
    if slack is None:
        print(text)
        print("-" * 60)
        return
    try:
        slack.chat_postMessage(channel=SLACK_CHANNEL, text=text, mrkdwn=True)
    except SlackApiError as exc:
        print(f"Slack error: {exc}")


def main() -> None:
    today = date.today().strftime("%Y-%m-%d")
    print(f"Premier League results check — {today}")
    print(f"Tracking {len(PREMIER_LEAGUE_TEAMS)} clubs\n")

    if not ANTHROPIC_API_KEY:
        print("Error: set CLAUDE_API_KEY or ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    slack = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

    if slack is None:
        print("SLACK_BOT_TOKEN not set — printing to stdout instead.\n")

    matches = fetch_todays_matches(today)

    if not matches:
        msg = f"No completed Premier League matches on {today}."
        print(msg)
        post(msg, slack)
        return

    print(f"Found {len(matches)} completed fixture(s).\n")

    post(f":soccer: *Premier League Results — {today}*", slack)

    count = 0
    for match in matches:
        home = canonical(match["homeTeam"]["name"])
        away = canonical(match["awayTeam"]["name"])

        for team in (home, away):
            if team not in PREMIER_LEAGUE_TEAMS:
                continue
            print(f"Generating summary for {team} ...")
            try:
                summary = generate_supporter_summary(team, match, claude)
                post(summary, slack)
                count += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  !! Error for {team}: {exc}")

    post(
        f"_Checked {len(PREMIER_LEAGUE_TEAMS)} Premier League clubs · "
        f"{count} summaries generated_",
        slack,
    )
    print(f"\nDone — {count} summaries generated.")


if __name__ == "__main__":
    main()
