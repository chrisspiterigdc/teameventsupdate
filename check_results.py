#!/usr/bin/env python3
"""Premier League match results -> Claude summary -> Slack."""

import datetime
import os
import sys

import requests

# Read from environment variables if set, otherwise fall back to config.py
try:
    import config as _cfg
    OPTICODDS_KEY     = os.environ.get("OPTICODDS_KEY")     or _cfg.OPTICODDS_KEY
    CLAUDE_API_KEY    = os.environ.get("CLAUDE_API_KEY")    or _cfg.CLAUDE_API_KEY
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL") or _cfg.SLACK_WEBHOOK_URL
except ImportError:
    OPTICODDS_KEY     = os.environ.get("OPTICODDS_KEY", "")
    CLAUDE_API_KEY    = os.environ.get("CLAUDE_API_KEY", "")
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

TEAMS = [
    {"teamName": "AFC Bournemouth",         "opticoddsId": "F2CCF38E0A5A"},
    {"teamName": "Arsenal",                  "opticoddsId": "48B92509529C"},
    {"teamName": "Aston Villa",              "opticoddsId": "C5F8130E6580"},
    {"teamName": "Brentford",                "opticoddsId": "B196AD1A3F37"},
    {"teamName": "Brighton & Hove Albion",   "opticoddsId": "263AF016D0C5"},
    {"teamName": "Burnley",                  "opticoddsId": "4B94C3B57377"},
    {"teamName": "Chelsea",                  "opticoddsId": "A477D0C02A28"},
    {"teamName": "Crystal Palace",           "opticoddsId": "E22B557B1960"},
    {"teamName": "Everton",                  "opticoddsId": "F55F77B71202"},
    {"teamName": "Fulham",                   "opticoddsId": "D6AD821C3B5E"},
    {"teamName": "Ipswich Town",             "opticoddsId": "77CBFB371ED9"},
    {"teamName": "Leeds United",             "opticoddsId": "EA3F3BDC929F604A"},
    {"teamName": "Leicester City",           "opticoddsId": "AF647EC9C595"},
    {"teamName": "Liverpool",                "opticoddsId": "F799E43513D4"},
    {"teamName": "Luton Town",               "opticoddsId": "982A5B2282B1"},
    {"teamName": "Manchester City",          "opticoddsId": "E69E55FFCF65"},
    {"teamName": "Manchester United",        "opticoddsId": "AF8DDBC0795A"},
    {"teamName": "Newcastle United",         "opticoddsId": "273700707FB1"},
    {"teamName": "Nottingham Forest",        "opticoddsId": "013D1D5F4D18"},
    {"teamName": "Sheffield United",         "opticoddsId": "C65F416ACC52"},
    {"teamName": "Southampton",              "opticoddsId": "BFC3376DC331"},
    {"teamName": "Sunderland",               "opticoddsId": "7FE4D2F60890E794"},
    {"teamName": "Tottenham Hotspur",        "opticoddsId": "35DDD3D70565"},
    {"teamName": "West Ham United",          "opticoddsId": "957C00F85D81"},
    {"teamName": "Wolverhampton Wanderers",  "opticoddsId": "1F74DDDE7110"},
]

OPTICODDS_BASE = "https://api.opticodds.com/api/v3"


def opticodds_get(path, params):
    r = requests.get(
        f"{OPTICODDS_BASE}{path}",
        headers={"X-Api-Key": OPTICODDS_KEY},
        params=params,
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def get_today_fixture(team_id, today):
    fixtures = opticodds_get("/fixtures/results", {"sport": "soccer", "team_id": team_id})
    matches = [
        f for f in fixtures
        if (f.get("fixture", {}).get("start_date") or f.get("start_date", "")).startswith(today)
    ]
    return matches[0] if matches else None


def get_next_fixture(team_id, tomorrow):
    fixtures = opticodds_get("/fixtures", {
        "sport": "soccer",
        "team_id": team_id,
        "start_date": tomorrow,
        "limit": 1,
    })
    return fixtures[0] if fixtures else None


def get_injuries(team_id):
    try:
        return opticodds_get("/injuries", {"sport": "soccer", "team_id": team_id})
    except Exception:
        return []


def _first(lst):
    return (lst or [{}])[0]


def extract_match_info(fixture, team_id):
    f = fixture.get("fixture", {})
    home_id = _first(f.get("home_competitors")).get("id")
    is_home = home_id == team_id

    scores = fixture.get("scores") or {}
    home_score = (scores.get("home") or {}).get("total", 0) or 0
    away_score = (scores.get("away") or {}).get("total", 0) or 0
    goals_for     = home_score if is_home else away_score
    goals_against = away_score if is_home else home_score
    result = "WIN" if goals_for > goals_against else "LOSS" if goals_for < goals_against else "DRAW"

    if is_home:
        opponent = f.get("away_team_display") or _first(f.get("away_competitors")).get("name", "Unknown")
    else:
        opponent = f.get("home_team_display") or _first(f.get("home_competitors")).get("name", "Unknown")

    competition = (fixture.get("league") or {}).get("name", "")

    side_stats = ((fixture.get("stats") or {}).get("home" if is_home else "away")) or []
    my_stats = next((s.get("stats", {}) for s in side_stats if s.get("period") == "all"), {})

    return {
        "is_home": is_home,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "result": result,
        "opponent": opponent,
        "competition": competition,
        "stats": my_stats,
    }


def extract_next_fixture(raw, team_id):
    if not raw:
        return None
    nf = raw.get("fixture", {})
    nf_home_id = _first(nf.get("home_competitors")).get("id")
    nf_is_home = nf_home_id == team_id
    if nf_is_home:
        opponent = nf.get("away_team_display") or _first(nf.get("away_competitors")).get("name", "TBD")
    else:
        opponent = nf.get("home_team_display") or _first(nf.get("home_competitors")).get("name", "TBD")
    return {
        "opponent": opponent,
        "date": nf.get("start_date"),
        "competition": (raw.get("league") or {}).get("name", "TBD"),
    }


def extract_injuries(raw):
    return [
        {
            "name": i["player"]["name"],
            "position": (i.get("player") or {}).get("position", ""),
            "status": i.get("status", ""),
            "type": i.get("type", ""),
        }
        for i in raw
        if (i.get("player") or {}).get("name")
    ][:5]


def build_prompt(team_name, d):
    lines = [
        f"Update the website for {team_name}.",
        "",
        "MATCH:",
        f"- {d['competition']} | {'Home' if d['is_home'] else 'Away'} vs {d['opponent']}",
        f"- Result: {d['result']} {d['goals_for']}-{d['goals_against']}",
    ]

    s = d.get("stats", {})
    parts = []
    shots   = s.get("total_scoring_att")    if s.get("total_scoring_att")    is not None else s.get("shots")
    on_tgt  = s.get("ontarget_scoring_att") if s.get("ontarget_scoring_att") is not None else s.get("shots_on_target")
    poss    = s.get("possession_percentage") if s.get("possession_percentage") is not None else s.get("possession")
    corners = s.get("corner_taken")         if s.get("corner_taken")         is not None else s.get("corners")
    if shots   is not None: parts.append(f"Shots {shots}" + (f" ({on_tgt} on target)" if on_tgt is not None else ""))
    if poss    is not None: parts.append(f"Possession {poss}%")
    if corners is not None: parts.append(f"Corners {corners}")
    if parts:
        lines.append("- Stats: " + " | ".join(parts))

    nf = d.get("next_fixture")
    if nf and nf.get("date"):
        try:
            dt = datetime.datetime.fromisoformat(nf["date"].replace("Z", "+00:00"))
            formatted = dt.strftime("%A %-d %B")
        except Exception:
            formatted = nf["date"]
        lines += ["", f"NEXT MATCH: {nf['opponent']} ({nf['competition']}) - {formatted}"]
    else:
        lines += ["", "NEXT MATCH: No upcoming match currently scheduled."]

    injuries = d.get("injuries", [])
    if injuries:
        lines += ["", "INJURY LIST:"]
        for inj in injuries:
            pos = f" ({inj['position']})" if inj.get("position") else ""
            lines.append(f"- {inj['name']}{pos}: {inj.get('status', '')} - {inj.get('type', '')}")

    lines += [
        "",
        "Write a punchy, supporter-facing 2-3 sentence update for the team's website. Requirements:",
        "1. Open with the result and score",
        "2. Include a performance detail from the stats if provided",
        "3. Close with the next fixture",
        "4. If there are injuries, weave in one concern naturally",
        "",
        "Return ONLY plain text - no HTML, no markdown, no quotes.",
    ]
    return "\n".join(lines)


def call_claude(prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def send_slack(team_name, d, generated):
    result      = d["result"]
    score       = f"{d['goals_for']}-{d['goals_against']}"
    opponent    = d["opponent"]
    competition = d.get("competition") or "Premier League"
    next_fixture = d.get("next_fixture")
    injuries    = d.get("injuries", [])

    emoji = {"WIN": ":white_check_mark:", "LOSS": ":x:", "DRAW": ":heavy_minus_sign:"}.get(result, ":heavy_minus_sign:")
    ctx = [competition]
    if next_fixture:
        ctx.append(f"Next: {next_fixture['opponent']} ({next_fixture['competition']})")
    if injuries:
        ctx.append(f"Injuries: {len(injuries)}")

    r = requests.post(
        SLACK_WEBHOOK_URL,
        json={
            "text": f"{team_name} | {result} {score} vs {opponent}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"{team_name}  |  {result} {score}", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji}  *vs {opponent}*  ({competition})\n\n{generated}"}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": "  |  ".join(ctx)}]},
            ],
        },
        timeout=10,
    )
    r.raise_for_status()


def process_team(team, today, tomorrow):
    team_id   = team["opticoddsId"]
    team_name = team["teamName"]

    fixture = get_today_fixture(team_id, today)
    if not fixture:
        print(f"  {team_name}: no match today")
        return False

    d = extract_match_info(fixture, team_id)
    d["next_fixture"] = extract_next_fixture(get_next_fixture(team_id, tomorrow), team_id)
    d["injuries"]     = extract_injuries(get_injuries(team_id))

    prompt    = build_prompt(team_name, d)
    generated = call_claude(prompt)
    send_slack(team_name, d, generated)

    print(f"  OK  {team_name}: {d['result']} {d['goals_for']}-{d['goals_against']} vs {d['opponent']}")
    return True


def main():
    placeholder = "PASTE_YOUR"
    missing = [k for k, v in [
        ("OPTICODDS_KEY",     OPTICODDS_KEY),
        ("CLAUDE_API_KEY",    CLAUDE_API_KEY),
        ("SLACK_WEBHOOK_URL", SLACK_WEBHOOK_URL),
    ] if not v or placeholder in v]
    if missing:
        print(f"ERROR: fill in these keys in config.py: {', '.join(missing)}")
        sys.exit(1)

    today    = datetime.date.today().isoformat()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    print(f"Checking {len(TEAMS)} Premier League teams for {today} ...")

    sent = sum(1 for team in TEAMS if process_team(team, today, tomorrow))
    print(f"\nDone - {sent} Slack message(s) sent.")


if __name__ == "__main__":
    main()
