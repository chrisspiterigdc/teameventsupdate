"""
Check today's completed Premier League matches, generate fan summaries via Claude,
and post them to Slack.

Required environment variables:
  ANTHROPIC_API_KEY   - Anthropic API key
  FOOTBALL_API_KEY    - football-data.org API key (free tier: https://www.football-data.org)
  SLACK_BOT_TOKEN     - Slack bot OAuth token
  SLACK_CHANNEL       - Slack channel to post to (e.g. #match-results)
"""

import os
import sys
from datetime import date

import anthropic
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#match-results")

PREMIER_LEAGUE_TEAMS = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton & Hove Albion",
    "Chelsea",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Ipswich Town",
    "Leicester City",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Southampton",
    "Tottenham Hotspur",
    "West Ham United",
    "Wolverhampton Wanderers",
]


def check_env():
    missing = []
    for var in ("FOOTBALL_API_KEY", "SLACK_BOT_TOKEN"):
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print(f"Error: missing required environment variables: {', '.join(missing)}")
        sys.exit(1)


def get_todays_completed_matches() -> list[dict]:
    today = date.today().isoformat()
    url = "https://api.football-data.org/v4/competitions/PL/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    params = {"dateFrom": today, "dateTo": today, "status": "FINISHED"}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    if resp.status_code == 401:
        print("Error: invalid FOOTBALL_API_KEY")
        sys.exit(1)
    resp.raise_for_status()

    matches = resp.json().get("matches", [])
    print(f"Found {len(matches)} completed Premier League match(es) today ({today}).")
    return matches


def generate_supporter_summary(match: dict, team_name: str) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_score = match["score"]["fullTime"]["home"]
    away_score = match["score"]["fullTime"]["away"]
    side = "home" if team_name == home else "away"
    opponent = away if side == "home" else home
    team_score = home_score if side == "home" else away_score
    opp_score = away_score if side == "home" else home_score

    if team_score > opp_score:
        result_context = f"{team_name} won {team_score}-{opp_score}"
    elif team_score < opp_score:
        result_context = f"{team_name} lost {team_score}-{opp_score}"
    else:
        result_context = f"it finished {team_score}-{opp_score}, a draw"

    prompt = (
        f"You are a passionate {team_name} supporter writing a short reaction post "
        f"on the club's fan forum after today's Premier League match.\n\n"
        f"Match: {home} {home_score}–{away_score} {away} (Premier League)\n"
        f"Your team ({team_name}) played {side} against {opponent}, and {result_context}.\n\n"
        f"Write 2–3 sentences in the voice of a genuine supporter: "
        f"celebrate a win enthusiastically, commiserate honestly after a loss, "
        f"or give a measured take on a draw. Keep it conversational and authentic."
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def post_to_slack(slack: WebClient, text: str):
    try:
        slack.chat_postMessage(channel=SLACK_CHANNEL, text=text)
    except SlackApiError as e:
        print(f"  Slack error: {e.response['error']}")


def format_slack_message(match: dict, team_name: str, summary: str) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    home_score = match["score"]["fullTime"]["home"]
    away_score = match["score"]["fullTime"]["away"]
    header = f"*{team_name} fans react* · {home} {home_score}–{away_score} {away}"
    return f"{header}\n{summary}"


def main():
    check_env()

    print(f"Checking Premier League results for {date.today().isoformat()}...\n")
    matches = get_todays_completed_matches()

    if not matches:
        print("No completed matches today — nothing to post.")
        return

    slack = WebClient(token=SLACK_BOT_TOKEN)
    posted = 0

    for match in matches:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        print(f"\n{home} {home_score}–{away_score} {away}")

        for team_name in (home, away):
            if team_name not in PREMIER_LEAGUE_TEAMS:
                # Fuzzy membership check for alternate name spellings
                match_in_list = any(
                    team_name.lower() in t.lower() or t.lower() in team_name.lower()
                    for t in PREMIER_LEAGUE_TEAMS
                )
                if not match_in_list:
                    print(f"  Skipping {team_name} (not in PL team list)")
                    continue

            print(f"  Generating summary for {team_name} supporters...", end=" ", flush=True)
            summary = generate_supporter_summary(match, team_name)
            print("done.")

            message = format_slack_message(match, team_name, summary)
            post_to_slack(slack, message)
            print(f"  Posted to Slack ({SLACK_CHANNEL}).")
            posted += 1

    print(f"\nDone. Posted {posted} supporter reaction(s) to {SLACK_CHANNEL}.")


if __name__ == "__main__":
    main()
