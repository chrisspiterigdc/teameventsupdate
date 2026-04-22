"""
Premier League match results checker.

Fetches today's completed PL matches via the ESPN Scoreboard API, generates
a short match summary for each using Claude, then posts the summaries to Slack.

Environment variables:
  ANTHROPIC_API_KEY   – Anthropic API key (falls back to Claude Code OAuth token)
  SLACK_BOT_TOKEN     – Slack bot token for chat.postMessage
  SLACK_WEBHOOK_URL   – Slack incoming-webhook URL (used if SLACK_BOT_TOKEN unset)
  SLACK_CHANNEL       – Channel to post into (default: #general)
  DEMO_MODE           – Set to "1" to run with sample fixture data (useful when
                        the sports API is unreachable or no matches are live yet)
"""

import os
import sys
import time
import requests
from datetime import date

import anthropic

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#general")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"

PREMIER_LEAGUE_TEAMS = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton & Hove Albion",
    "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich Town",
    "Leicester City", "Liverpool", "Manchester City", "Manchester United",
    "Newcastle United", "Nottingham Forest", "Southampton",
    "Tottenham Hotspur", "West Ham United", "Wolverhampton Wanderers",
]

DEMO_FIXTURES = [
    {"home_team": "Arsenal",           "away_team": "Liverpool",           "home_score": 2, "away_score": 1},
    {"home_team": "Manchester City",   "away_team": "Chelsea",             "home_score": 3, "away_score": 1},
    {"home_team": "Tottenham Hotspur", "away_team": "Newcastle United",    "home_score": 0, "away_score": 0},
    {"home_team": "Aston Villa",       "away_team": "Nottingham Forest",   "home_score": 2, "away_score": 2},
    {"home_team": "Brighton & Hove Albion", "away_team": "Wolverhampton Wanderers", "home_score": 1, "away_score": 0},
]


def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        oauth_path = "/home/claude/.claude/remote/.oauth_token"
        if os.path.exists(oauth_path):
            with open(oauth_path) as f:
                api_key = f.read().strip()
    if not api_key:
        print("Error: no ANTHROPIC_API_KEY found.")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def get_todays_matches():
    today = date.today().strftime("%Y%m%d")
    resp = requests.get(ESPN_URL, params={"dates": today}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("events", [])


def is_completed(event):
    return event.get("status", {}).get("type", {}).get("completed", False)


def parse_match(event):
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    return {
        "home_team": home.get("team", {}).get("displayName", "Unknown"),
        "away_team": away.get("team", {}).get("displayName", "Unknown"),
        "home_score": int(home.get("score", 0) or 0),
        "away_score": int(away.get("score", 0) or 0),
    }


def _match_line(m):
    home, away, hs, as_ = m["home_team"], m["away_team"], m["home_score"], m["away_score"]
    if hs > as_:
        ctx = f"{home} won {hs}-{as_} at home"
    elif as_ > hs:
        ctx = f"{away} won {as_}-{hs} away"
    else:
        ctx = f"ended {hs}-{hs} (draw)"
    return f"{home} {hs} - {as_} {away} ({ctx})"


def generate_summaries(matches, client, retries=4):
    """Return a list of summaries, one per match, via a single API call."""
    numbered = "\n".join(f"{i+1}. {_match_line(m)}" for i, m in enumerate(matches))
    prompt = (
        "For each of the following Premier League results, write exactly one punchy "
        "2-3 sentence match report in an enthusiastic football commentary style.\n\n"
        "Return ONLY a numbered list matching the input order, like:\n"
        "1. <report>\n2. <report>\n...\n\n"
        f"Results:\n{numbered}"
    )

    for attempt in range(retries):
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            lines = []
            for line in raw.splitlines():
                line = line.strip()
                # Strip leading "1. " / "2. " etc.
                if line and line[0].isdigit() and ". " in line:
                    lines.append(line.split(". ", 1)[1])
            if len(lines) == len(matches):
                return lines
            # Fallback: split on double-newline blocks
            blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
            if len(blocks) == len(matches):
                return blocks
            # Last resort: return whole text as the single summary
            return [raw] + [""] * (len(matches) - 1)
        except anthropic.RateLimitError:
            wait = 10 * (attempt + 1)
            print(f"  [rate limited, retrying in {wait}s…]")
            time.sleep(wait)
    raise RuntimeError(f"Failed to generate summaries after {retries} attempts")


def post_to_slack(text):
    if SLACK_BOT_TOKEN and SLACK_SDK_AVAILABLE:
        slack = WebClient(token=SLACK_BOT_TOKEN)
        try:
            slack.chat_postMessage(channel=SLACK_CHANNEL, text=text)
            print(f"  [Slack] posted to {SLACK_CHANNEL}")
            return
        except SlackApiError as e:
            print(f"  [Slack error: {e.response['error']}]")
    elif SLACK_WEBHOOK_URL:
        r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        if r.ok:
            print("  [Slack] posted via webhook")
        return
    # Fallback: echo the message
    print(text)


def main():
    today = date.today().isoformat()
    print(f"Premier League Match Results — {today}")
    if DEMO_MODE:
        print("(running in DEMO_MODE with sample fixture data)")
    print("=" * 60)

    client = get_anthropic_client()

    if DEMO_MODE:
        completed = DEMO_FIXTURES
        print(f"Using {len(completed)} demo fixture(s).\n")
    else:
        print("Fetching today's matches from ESPN…")
        try:
            events = get_todays_matches()
        except requests.RequestException as e:
            print(f"Error fetching matches: {e}")
            print("Tip: set DEMO_MODE=1 to run with sample fixture data.")
            sys.exit(1)

        completed = [parse_match(e) for e in events if is_completed(e)]

        if not completed:
            print("No completed matches found today.")
            post_to_slack(f":soccer: *Premier League Results — {today}*\nNo completed matches today.")
            return

        print(f"Found {len(completed)} completed match(es).\n")

    post_to_slack(f":soccer: *Premier League Results — {today}*{' (demo)' if DEMO_MODE else ''} :soccer:")

    print("Generating summaries via Claude…")
    summaries = generate_summaries(completed, client)

    for match, summary in zip(completed, summaries):
        home, away = match["home_team"], match["away_team"]
        hs, as_ = match["home_score"], match["away_score"]

        print(f"\n  {home} {hs} - {as_} {away}")
        print(f"  {summary}")

        post_to_slack(f"*{home} {hs} — {as_} {away}*\n{summary}")

    print("\nDone.")


if __name__ == "__main__":
    main()
