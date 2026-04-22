#!/usr/bin/env python3
"""
Premier League match results checker.
Fetches today's EPL fixtures via Optic Odds API, generates summaries via Claude,
and posts them to Slack.
"""

import json
import os
import sys
import requests
from datetime import date, datetime, timezone
from anthropic import Anthropic

# All 20 Premier League 2025-26 teams
EPL_TEAMS = [
    "AFC Bournemouth",
    "Arsenal FC",
    "Aston Villa FC",
    "Brentford FC",
    "Brighton & Hove Albion FC",
    "Burnley FC",
    "Chelsea FC",
    "Crystal Palace FC",
    "Everton FC",
    "Fulham FC",
    "Leeds United FC",
    "Liverpool FC",
    "Manchester City FC",
    "Manchester United FC",
    "Newcastle United FC",
    "Nottingham Forest FC",
    "Sunderland AFC",
    "Tottenham Hotspur FC",
    "West Ham United FC",
    "Wolverhampton Wanderers FC",
]

N8N_PROXY_URL = "https://gdcgroup.app.n8n.cloud/webhook/opticodds-proxy"
OPTICODDS_BASE = "https://api.opticodds.com/api/v3"
OPTICODDS_KEY = os.environ.get("OPTICODDS_KEY", "")
FIXTURES_FALLBACK = "/tmp/epl_fixtures_today.json"


def fetch_fixtures_via_proxy(target_date: str) -> list[dict]:
    """Fetch EPL fixtures via n8n OpticOdds proxy."""
    url = (
        f"{OPTICODDS_BASE}/fixtures"
        f"?sport=soccer&league=england_-_premier_league"
        f"&start_date={target_date}&end_date={target_date}"
    )
    resp = requests.post(N8N_PROXY_URL, json={"url": url}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_fixtures_direct(target_date: str) -> list[dict]:
    """Fetch EPL fixtures directly from Optic Odds (requires network access)."""
    url = (
        f"{OPTICODDS_BASE}/fixtures"
        f"?sport=soccer&league=england_-_premier_league"
        f"&start_date={target_date}&end_date={target_date}"
        f"&key={OPTICODDS_KEY}"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def load_fixtures_from_file(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f).get("data", [])


def get_today_fixtures() -> tuple[list[dict], str]:
    """Return (fixtures, source_description)."""
    today = date.today().isoformat()

    # 1. Try n8n proxy (works from this environment)
    try:
        fixtures = fetch_fixtures_via_proxy(today)
        print(f"Fetched {len(fixtures)} fixture(s) via n8n proxy for {today}")
        return fixtures, "Optic Odds API (via n8n proxy)"
    except Exception as e:
        print(f"n8n proxy unavailable: {e}", file=sys.stderr)

    # 2. Try direct API call (works in production)
    if OPTICODDS_KEY:
        try:
            fixtures = fetch_fixtures_direct(today)
            print(f"Fetched {len(fixtures)} fixture(s) directly for {today}")
            return fixtures, "Optic Odds API (direct)"
        except Exception as e:
            print(f"Direct API unavailable: {e}", file=sys.stderr)

    # 3. Fall back to pre-fetched file
    if os.path.exists(FIXTURES_FALLBACK):
        fixtures = load_fixtures_from_file(FIXTURES_FALLBACK)
        print(f"Loaded {len(fixtures)} fixture(s) from fallback file")
        return fixtures, "pre-fetched file"

    return [], "no source available"


def score_str(fixture: dict) -> str:
    """Return 'H-A' score string or empty string if no score."""
    result = fixture.get("result") or {}
    scores = result.get("scores")
    if not scores:
        return ""
    home = scores.get("home", {}).get("total")
    away = scores.get("away", {}).get("total")
    if home is None or away is None:
        return ""
    return f"{home}-{away}"


def format_kickoff(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.strftime("%H:%M UTC")


def build_team_status(fixtures: list[dict]) -> dict[str, dict]:
    """Build a mapping of team_name -> match info for all EPL teams."""
    status = {team: None for team in EPL_TEAMS}
    for fix in fixtures:
        home = fix.get("home_team_display", "")
        away = fix.get("away_team_display", "")
        match_info = {
            "home": home,
            "away": away,
            "status": fix.get("status", "unknown"),
            "kickoff": format_kickoff(fix["start_date"]),
            "venue": fix.get("venue_name", ""),
            "score": score_str(fix),
            "week": fix.get("season_week", ""),
        }
        if home in status:
            status[home] = match_info
        if away in status:
            status[away] = match_info
    return status


def _make_anthropic_client() -> Anthropic:
    """Return an authenticated Anthropic client, supporting both API key and session token."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return Anthropic(api_key=api_key)
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if token_file and os.path.exists(token_file):
        token = open(token_file).read().strip()
        return Anthropic(auth_token=token)
    return Anthropic()


def generate_summary(client: Anthropic, completed: list[dict], scheduled: list[dict]) -> str:
    """Use Claude to generate a natural-language match day summary."""
    today_str = date.today().strftime("%A, %d %B %Y")

    completed_text = ""
    if completed:
        lines = []
        for fix in completed:
            score = score_str(fix)
            lines.append(
                f"- {fix['home_team_display']} {score} {fix['away_team_display']}"
                f" (GW{fix.get('season_week','?')}, {fix.get('venue_name','')})"
            )
        completed_text = "COMPLETED MATCHES:\n" + "\n".join(lines)

    scheduled_text = ""
    if scheduled:
        lines = []
        for fix in scheduled:
            lines.append(
                f"- {fix['home_team_display']} vs {fix['away_team_display']}"
                f" at {format_kickoff(fix['start_date'])} (GW{fix.get('season_week','?')}, {fix.get('venue_name','')})"
            )
        scheduled_text = "SCHEDULED (NOT YET PLAYED):\n" + "\n".join(lines)

    data_section = "\n\n".join(filter(None, [completed_text, scheduled_text]))
    if not data_section:
        data_section = "No Premier League fixtures today."

    prompt = f"""You are a Premier League football reporter. Write a concise, engaging Slack post summarising today's Premier League activity for {today_str}.

Match data:
{data_section}

Guidelines:
- If there are completed results, lead with them and include the score, venue, and gameweek.
- If only upcoming matches, briefly note kick-off times and build anticipation.
- If no matches, say so clearly and mention the next upcoming fixture if possible.
- Keep it to 3-5 sentences, punchy and factual.
- Do NOT use markdown headers. Use plain text suitable for Slack.
- End with a relevant emoji or two."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_slack_message(
    team_status: dict[str, dict],
    summary: str,
    source: str,
    today_str: str,
) -> str:
    lines = [
        f"*Premier League Update — {today_str}*",
        f"_{summary}_",
        "",
        "*Today's Team Status:*",
    ]
    for team in EPL_TEAMS:
        info = team_status[team]
        if info is None:
            lines.append(f"• {team}: No fixture today")
        elif info["status"] == "completed":
            opponent = info["away"] if info["home"] == team else info["home"]
            home_away = "vs" if info["home"] == team else "at"
            lines.append(
                f"• {team}: ✅ {home_away} {opponent} — *{info['score']}* (FT)"
            )
        elif info["status"] in ("unplayed", "scheduled"):
            opponent = info["away"] if info["home"] == team else info["home"]
            home_away = "vs" if info["home"] == team else "at"
            lines.append(
                f"• {team}: 🕐 {home_away} {opponent} — KO {info['kickoff']}"
            )
        else:
            lines.append(f"• {team}: {info['status']}")

    lines += ["", f"_Source: {source}_"]
    return "\n".join(lines)


SLACK_CHANNEL_ID = "C0AVBC6256C"


def post_to_slack(message: str) -> bool:
    """Post to Slack channel C0AVBC6256C via bot token. Returns True on success."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if token:
        try:
            r = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": SLACK_CHANNEL_ID, "text": message},
                timeout=10,
            )
            return r.json().get("ok", False)
        except Exception:
            pass

    return False


def main():
    today_str = date.today().strftime("%A, %d %B %Y")
    print(f"\n=== Premier League Match Results — {today_str} ===\n")

    # 1. Fetch fixtures
    fixtures, source = get_today_fixtures()

    completed = [f for f in fixtures if f.get("status") == "completed"]
    scheduled = [f for f in fixtures if f.get("status") in ("unplayed", "scheduled")]

    print(f"Fixtures found: {len(fixtures)} total, {len(completed)} completed, {len(scheduled)} scheduled")

    # 2. Build team status map
    team_status = build_team_status(fixtures)

    # 3. Generate Claude summary
    print("\nGenerating summary via Claude...")
    client = _make_anthropic_client()
    summary = generate_summary(client, completed, scheduled)
    print(f"\nSummary:\n{summary}\n")

    # 4. Build full Slack message
    slack_msg = build_slack_message(team_status, summary, source, today_str)
    print("=== SLACK MESSAGE ===")
    print(slack_msg)
    print("====================\n")

    # 5. Try to post to Slack
    posted = post_to_slack(slack_msg)
    if posted:
        print("Posted to Slack successfully.")
    else:
        print("Slack posting not available in this environment — message printed above.")

    return slack_msg


if __name__ == "__main__":
    main()
