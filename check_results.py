"""
check_results.py

Fetches today's completed Premier League matches from the football-data.org API,
generates a short summary for each via Claude, and posts the results to Slack.

Required environment variables:
  FOOTBALL_DATA_API_KEY  - API token from https://www.football-data.org/
  SLACK_BOT_TOKEN        - Slack Bot OAuth token (xoxb-...)
  SLACK_CHANNEL_ID       - Slack channel ID or name to post into (e.g. C01234ABCDE)
  ANTHROPIC_API_KEY      - Anthropic API key (or rely on ANTHROPIC_BASE_URL if set)
"""

import os
import sys
from datetime import date

import anthropic
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

FOOTBALL_API_BASE = "https://api.football-data.org/v4"
PL_COMPETITION = "PL"  # Premier League competition code

PREMIER_LEAGUE_TEAMS = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford",
    "Brighton & Hove Albion", "Chelsea", "Crystal Palace", "Everton",
    "Fulham", "Ipswich Town", "Leicester City", "Liverpool",
    "Manchester City", "Manchester United", "Newcastle United",
    "Nottingham Forest", "Southampton", "Tottenham Hotspur",
    "West Ham United", "Wolverhampton Wanderers",
]


def get_todays_pl_matches(api_key: str) -> list[dict]:
    today = date.today().isoformat()
    url = f"{FOOTBALL_API_BASE}/competitions/{PL_COMPETITION}/matches"
    headers = {"X-Auth-Token": api_key}
    params = {"dateFrom": today, "dateTo": today}

    print(f"Fetching Premier League matches for {today} from football-data.org...")
    resp = requests.get(url, headers=headers, params=params, timeout=30)

    if resp.status_code == 403:
        print("Error: Invalid FOOTBALL_DATA_API_KEY or insufficient API tier.")
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    all_matches = data.get("matches", [])
    finished = [m for m in all_matches if m.get("status") == "FINISHED"]
    return finished


def result_emoji(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return ":blue_circle:"   # home win
    if home_score < away_score:
        return ":red_circle:"    # away win
    return ":white_circle:"      # draw


def generate_summary(claude: anthropic.Anthropic, match: dict) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    hs = match["score"]["fullTime"]["home"]
    as_ = match["score"]["fullTime"]["away"]
    matchday = match.get("matchday", "?")

    # Determine winner/draw for the prompt
    if hs > as_:
        outcome = f"{home} won"
    elif hs < as_:
        outcome = f"{away} won"
    else:
        outcome = "The match ended in a draw"

    prompt = (
        f"Write a punchy 2-3 sentence Premier League match summary for this result:\n\n"
        f"  {home} {hs} – {as_} {away}  (Matchday {matchday})\n"
        f"  Outcome: {outcome}\n\n"
        f"Be enthusiastic and concise. Mention both teams and the final scoreline."
    )

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def post_to_slack(client: WebClient, channel: str, text: str) -> None:
    try:
        client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as exc:
        print(f"Slack error: {exc.response['error']}")
        raise


def main() -> None:
    # --- Validate required environment variables ---
    football_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    missing = [
        name for name, val in [
            ("FOOTBALL_DATA_API_KEY", football_key),
            ("SLACK_BOT_TOKEN", slack_token),
            ("SLACK_CHANNEL_ID", slack_channel),
        ]
        if not val
    ]
    if missing:
        print(f"Error: Missing required environment variable(s): {', '.join(missing)}")
        sys.exit(1)

    today = date.today().isoformat()

    # --- Fetch matches ---
    finished_matches = get_todays_pl_matches(football_key)

    print(f"Found {len(finished_matches)} completed Premier League match(es) on {today}.")
    print(f"Checking all 20 Premier League teams: {len(PREMIER_LEAGUE_TEAMS)} teams tracked.\n")

    claude = anthropic.Anthropic()
    slack = WebClient(token=slack_token)

    if not finished_matches:
        no_games_msg = (
            f":soccer: *Premier League Results — {today}*\n\n"
            f"No completed matches today across all 20 Premier League teams."
        )
        post_to_slack(slack, slack_channel, no_games_msg)
        print("Posted 'no matches' notice to Slack.")
        return

    # --- Generate summaries ---
    lines = [f":soccer: *Premier League Results — {today}*\n"]
    for match in finished_matches:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        hs = match["score"]["fullTime"]["home"]
        as_ = match["score"]["fullTime"]["away"]

        print(f"Summarising: {home} {hs}–{as_} {away}")
        summary = generate_summary(claude, match)
        emoji = result_emoji(hs, as_)

        lines.append(
            f"{emoji} *{home} {hs}–{as_} {away}*\n{summary}"
        )

    full_message = "\n\n".join(lines)

    # --- Post to Slack ---
    post_to_slack(slack, slack_channel, full_message)
    print(f"\nPosted {len(finished_matches)} match summary/summaries to {slack_channel}.")


if __name__ == "__main__":
    main()
