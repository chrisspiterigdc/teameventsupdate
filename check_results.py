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
ANTHROPIC_AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN")
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
    """Known real results keyed by date; empty list for unknown dates."""
    known = {
        "2026-04-21": [
            {
                "homeTeam": {"name": "Brighton & Hove Albion"},
                "awayTeam": {"name": "Chelsea"},
                "score": {"fullTime": {"home": 3, "away": 0}, "halfTime": {"home": 1, "away": 0}},
                "status": "FINISHED",
                "utcDate": f"{today}T15:00:00Z",
                "context": {
                    "Brighton & Hove Albion": (
                        "Result lifted Brighton above Chelsea into 6th place on 50 points "
                        "with four games remaining. Now firmly in the European conversation — "
                        "a Europa League spot is realistic, and a Champions League place is "
                        "still mathematically possible if Aston Villa win the Europa League "
                        "while finishing in the top five. Goals from Ferdi Kadioglu, Jack "
                        "Hinshelwood and substitute Danny Welbeck."
                    ),
                    "Chelsea": (
                        "Defeat leaves Chelsea 7th on 48 points and could drop them as far "
                        "as 11th once matchweek 34 concludes. Champions League qualification "
                        "hopes have significantly diminished. It is a fifth straight Premier "
                        "League game without scoring — Chelsea's worst scoreless top-flight "
                        "run since 1912 — and the pressure on head coach Liam Rosenior is mounting."
                    ),
                },
            },
        ],
    }
    matches = known.get(today, [])
    if not matches:
        print(f"No known mock data for {today} — no matches returned.\n")
    return matches


def generate_team_news(team: str, match: dict, client: anthropic.Anthropic) -> str:
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
        result = "win"
    elif team_goals == opp_goals:
        result = "draw"
    else:
        result = "defeat"

    team_context = (match.get("context") or {}).get(team, "")
    context_block = (
        f"\nLeague context for {team}:\n{team_context}\n"
        if team_context else ""
    )

    prompt = (
        f"Write a 'Latest {team} News' blurb for a football betting information website, "
        f"in the style of the example below.\n\n"
        "EXAMPLE (Brighton, 3-0 win vs Chelsea):\n"
        "Brighton's 3-0 win over Chelsea wasn't just a statement result - it saw them leapfrog "
        "their opponents in the Premier League table and firmly strengthen their push for European qualification.\n"
        "Leading at the break and dominant throughout, the Seagulls showed they belong in the conversation for a top-seven finish.\n"
        "Fabian Hürzeler's side continues to impress with their attacking structure and composure, "
        "and a clean sheet against a direct rival boosts their credentials further.\n"
        "With momentum on their side and confidence growing, Brighton are right in the mix for Europe, "
        "and look well equipped to stay there as we reach the business end of the season.\n\n"
        "NOW WRITE FOR:\n"
        f"Team: {team}\n"
        f"Result: {('won' if result == 'win' else 'drew' if result == 'draw' else 'lost')} "
        f"{team_goals}-{opp_goals} {venue} vs {opponent} (HT: {ht_h if is_home else ht_a}-{ht_a if is_home else ht_h})\n"
        f"Context: {team_context}\n\n"
        "Style rules: short punchy sentences, narrative-led not stat-led, present tense, "
        "optimistic or honest depending on result, 3-4 short paragraphs of 1-2 sentences each. "
        "Weave in the table/European angle naturally — don't list raw points totals. "
        "Use the team's common short name. No headers, bullets, emoji, or first-person language."
    )
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    blurb = msg.content[0].text.strip()
    return f"*Latest {team} News*\n{blurb}"


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
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = date.today().strftime("%Y-%m-%d")
    print(f"Premier League results check — {target_date}")
    print(f"Tracking {len(PREMIER_LEAGUE_TEAMS)} clubs\n")

    if not ANTHROPIC_API_KEY and not ANTHROPIC_AUTH_TOKEN:
        print("Error: set CLAUDE_API_KEY, ANTHROPIC_API_KEY, or ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
        sys.exit(1)

    if ANTHROPIC_AUTH_TOKEN:
        claude = anthropic.Anthropic(auth_token=ANTHROPIC_AUTH_TOKEN)
    else:
        claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    slack = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

    if slack is None:
        print("SLACK_BOT_TOKEN not set — printing to stdout instead.\n")

    matches = fetch_todays_matches(target_date)

    if not matches:
        msg = f"No completed Premier League matches on {target_date}."
        print(msg)
        post(msg, slack)
        return

    print(f"Found {len(matches)} completed fixture(s).\n")

    post(f":soccer: *Premier League Results — {target_date}*", slack)

    count = 0
    for match in matches:
        home = canonical(match["homeTeam"]["name"])
        away = canonical(match["awayTeam"]["name"])

        for team in (home, away):
            if team not in PREMIER_LEAGUE_TEAMS:
                continue
            print(f"Generating summary for {team} ...")
            try:
                summary = generate_team_news(team, match, claude)
                post(summary, slack)
                count += 1
            except Exception as exc:
                print(f"  !! Error for {team}: {exc}")

    post(
        f"_Checked {len(PREMIER_LEAGUE_TEAMS)} Premier League clubs · "
        f"{count} summaries generated_",
        slack,
    )
    print(f"\nDone — {count} summaries generated.")


if __name__ == "__main__":
    main()
