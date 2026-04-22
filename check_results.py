#!/usr/bin/env python3
"""
check_results.py

Checks all 20 Premier League teams for today's completed matches via the
OpticOdds API, generates a short summary for each result using Claude, and
posts the summaries to the #optic-general Slack channel.

Authentication:
  - Claude API  : reads the Claude Code session token from the path stored in
                  SESSION_TOKEN_FILE (written by the Claude Code remote runner)
  - Slack        : calls the Slack MCP server through the Anthropic CCR proxy,
                  using the same session token
  - OpticOdds   : reads OPTICODDS_KEY from the environment
"""

import json
import os
import sys
from datetime import date

import anthropic
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TODAY = date.today().isoformat()
SLACK_CHANNEL_ID = "C08AJL44C01"  # #optic-general

SESSION_TOKEN_FILE = "/home/claude/.claude/remote/.session_ingress_token"
SESSION_ID = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "")
MCP_CONFIG_FILE = f"/tmp/mcp-config-{SESSION_ID}.json"

SUMMARY_MODEL = "claude-haiku-4-5-20251001"

PL_TEAMS = [
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_client() -> anthropic.Anthropic:
    token = open(SESSION_TOKEN_FILE).read().strip()
    return anthropic.Anthropic(auth_token=token)


def get_slack_mcp_url() -> str:
    with open(MCP_CONFIG_FILE) as f:
        config = json.load(f)
    return config["mcpServers"]["Slack"]["url"]


def fetch_pl_matches(target_date: str) -> list[dict]:
    """Return completed PL fixtures for *target_date* from OpticOdds API."""
    api_key = os.environ.get("OPTICODDS_KEY", "")
    if not api_key:
        print("  OPTICODDS_KEY not set – skipping API call.")
        return []

    try:
        r = requests.get(
            "https://api.opticodds.com/api/v3/fixtures",
            params={
                "sport": "soccer",
                "league": "EPL",
                "status": "completed",
                "date": target_date,
            },
            headers={"X-Api-Key": api_key},
            timeout=10,
        )
        if r.status_code != 200 or not r.text.startswith("{"):
            print(f"  OpticOdds returned {r.status_code}: {r.text[:120]}")
            return []
        data = r.json()
        return [
            {
                "home": fixture["home_team"],
                "away": fixture["away_team"],
                "home_score": int(fixture.get("home_score", 0)),
                "away_score": int(fixture.get("away_score", 0)),
                "kickoff": fixture.get("start_date", ""),
            }
            for fixture in data.get("data", [])
        ]
    except Exception as exc:
        print(f"  OpticOdds error: {exc}")
        return []


def generate_summary(client: anthropic.Anthropic, match: dict) -> str:
    """Ask Claude for a short, engaging match summary."""
    h, a = match["home"], match["away"]
    hs, as_ = match["home_score"], match["away_score"]

    if hs > as_:
        outcome = f"{h} won {hs}–{as_}"
    elif as_ > hs:
        outcome = f"{a} won {as_}–{hs}"
    else:
        outcome = f"both sides drew {hs}–{as_}"

    response = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=160,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a concise 2-3 sentence Premier League match summary for:\n"
                    f"{h} {hs}–{as_} {a}\n"
                    f"Result: {outcome}.\n"
                    "Keep it punchy and engaging. No hashtags or emojis."
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def slack_send(client: anthropic.Anthropic, mcp_url: str, message: str) -> None:
    """Post *message* to SLACK_CHANNEL_ID via the Slack MCP server."""
    token = open(SESSION_TOKEN_FILE).read().strip()

    response = client.beta.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=300,
        betas=["mcp-client-2025-04-04"],
        mcp_servers=[
            {
                "type": "url",
                "url": mcp_url,
                "name": "slack",
                "authorization_token": token,
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Send a message to Slack channel ID {SLACK_CHANNEL_ID} "
                    f"with exactly this text (preserve all formatting):\n\n"
                    f"{message}"
                ),
            }
        ],
    )

    tool_calls = [b for b in response.content if b.type == "mcp_tool_use"]
    if any("send_message" in getattr(b, "name", "") for b in tool_calls):
        print("  ✓ Posted to #optic-general")
    else:
        print("  ⚠ Slack tool was not invoked; Claude responded:")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"    {block.text[:300]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"=== Premier League Results – {TODAY} ===")
    print(f"Teams in scope: {len(PL_TEAMS)}\n")

    client = get_client()
    mcp_url = get_slack_mcp_url()

    # 1. Fetch completed matches
    print("Fetching completed matches from OpticOdds API...")
    matches = fetch_pl_matches(TODAY)

    if not matches:
        print("No completed matches found for today (or API unavailable).")
        msg = (
            f"*Premier League Results — {TODAY}*\n"
            f"No completed matches found for today, or the OpticOdds data "
            f"source is currently unavailable.\n"
            f"_{len(PL_TEAMS)} teams checked._"
        )
        print("\nPosting status update to Slack...")
        slack_send(client, mcp_url, msg)
        print("\nDone.")
        return

    print(f"Found {len(matches)} completed match(es).\n")

    # 2. Generate Claude summaries
    summaries = []
    for match in matches:
        h, a = match["home"], match["away"]
        hs, as_ = match["home_score"], match["away_score"]
        print(f"Generating summary: {h} {hs}–{as_} {a} ...")
        summary = generate_summary(client, match)
        summaries.append(f"*{h} {hs}–{as_} {a}*\n{summary}")
        print(f"  ✓\n")

    # 3. Compose and post Slack message
    body = "\n\n".join(summaries)
    msg = f"*Premier League Results — {TODAY}*\n\n{body}"

    print("Posting to Slack (#optic-general)...")
    slack_send(client, mcp_url, msg)
    print("\nDone.")


if __name__ == "__main__":
    main()
