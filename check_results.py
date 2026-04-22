#!/usr/bin/env python3
"""Fetch yesterday's Premier League match data from OpticOdds and print as JSON."""

import datetime
import json
import os
import sys

import requests

try:
    import config as _cfg
    OPTICODDS_KEY = os.environ.get("OPTICODDS_KEY") or _cfg.OPTICODDS_KEY
except ImportError:
    OPTICODDS_KEY = os.environ.get("OPTICODDS_KEY", "")

TEAMS = [
    {"teamName": "AFC Bournemouth",         "opticoddsId": "F2CCF38E0A5A"},
    {"teamName": "Arsenal",                  "opticoddsId": "48B92509529C"},
    {"teamName": "Aston Villa",              "opticoddsId": "C5F8130E6580"},
    {"teamName": "Brentford",               "opticoddsId": "B196AD1A3F37"},
    {"teamName": "Brighton & Hove Albion",  "opticoddsId": "263AF016D0C5"},
    {"teamName": "Burnley",                  "opticoddsId": "4B94C3B57377"},
    {"teamName": "Chelsea",                  "opticoddsId": "A477D0C02A28"},
    {"teamName": "Crystal Palace",          "opticoddsId": "E22B557B1960"},
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

BASE = "https://api.opticodds.com/api/v3"


def api_get(path, params):
    r = requests.get(f"{BASE}{path}", headers={"X-Api-Key": OPTICODDS_KEY}, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("data", [])


def _first(lst):
    return (lst or [{}])[0]


def get_fixture(team_id, date):
    all_fixtures = api_get("/fixtures/results", {"sport": "soccer", "team_id": team_id})
    matches = [f for f in all_fixtures
               if (f.get("fixture", {}).get("start_date") or "").startswith(date)]
    return matches[0] if matches else None


def get_next(team_id, from_date):
    fixtures = api_get("/fixtures", {"sport": "soccer", "team_id": team_id, "start_date": from_date, "limit": 1})
    return fixtures[0] if fixtures else None


def get_injuries(team_id):
    try:
        return api_get("/injuries", {"sport": "soccer", "team_id": team_id})
    except Exception:
        return []


def process_team(team, yesterday, today):
    team_id = team["opticoddsId"]
    fixture = get_fixture(team_id, yesterday)
    if not fixture:
        return None

    f = fixture.get("fixture", {})
    home_id = _first(f.get("home_competitors")).get("id")
    is_home = home_id == team_id

    scores = fixture.get("scores") or {}
    home_goals = (scores.get("home") or {}).get("total", 0) or 0
    away_goals = (scores.get("away") or {}).get("total", 0) or 0
    goals_for     = home_goals if is_home else away_goals
    goals_against = away_goals if is_home else home_goals
    result = "WIN" if goals_for > goals_against else "LOSS" if goals_for < goals_against else "DRAW"

    opponent = (
        f.get("away_team_display") or _first(f.get("away_competitors")).get("name", "Unknown")
        if is_home else
        f.get("home_team_display") or _first(f.get("home_competitors")).get("name", "Unknown")
    )
    competition = (fixture.get("league") or {}).get("name", "")

    side = "home" if is_home else "away"
    side_stats = ((fixture.get("stats") or {}).get(side)) or []
    stats = next((s.get("stats", {}) for s in side_stats if s.get("period") == "all"), {})

    # Next fixture
    next_raw = get_next(team_id, today)
    next_match = None
    if next_raw:
        nf = next_raw.get("fixture", {})
        nf_is_home = _first(nf.get("home_competitors")).get("id") == team_id
        next_match = {
            "opponent": (
                nf.get("away_team_display") or _first(nf.get("away_competitors")).get("name", "TBD")
                if nf_is_home else
                nf.get("home_team_display") or _first(nf.get("home_competitors")).get("name", "TBD")
            ),
            "date": nf.get("start_date"),
            "venue": "Home" if nf_is_home else "Away",
            "competition": (next_raw.get("league") or {}).get("name", "TBD"),
        }

    # Injuries
    inj_raw = get_injuries(team_id)
    injuries = [
        {
            "name": i["player"]["name"],
            "position": (i.get("player") or {}).get("position", ""),
            "status": i.get("status", ""),
            "type": i.get("type", ""),
        }
        for i in inj_raw if (i.get("player") or {}).get("name")
    ][:5]

    # Key stats
    shots   = stats.get("total_scoring_att")     if stats.get("total_scoring_att")     is not None else stats.get("shots")
    on_tgt  = stats.get("ontarget_scoring_att")  if stats.get("ontarget_scoring_att")  is not None else stats.get("shots_on_target")
    poss    = stats.get("possession_percentage") if stats.get("possession_percentage") is not None else stats.get("possession")
    corners = stats.get("corner_taken")          if stats.get("corner_taken")          is not None else stats.get("corners")

    return {
        "team":        team["teamName"],
        "result":      result,
        "score":       f"{goals_for}-{goals_against}",
        "opponent":    opponent,
        "venue":       "Home" if is_home else "Away",
        "competition": competition,
        "match_date":  yesterday,
        "stats": {
            "shots":      shots,
            "on_target":  on_tgt,
            "possession": poss,
            "corners":    corners,
        },
        "next_match":  next_match,
        "injuries":    injuries,
    }


def main():
    if not OPTICODDS_KEY or "PASTE_YOUR" in OPTICODDS_KEY:
        print(json.dumps({"error": "Fill in OPTICODDS_KEY in config.py"}))
        sys.exit(1)

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    today     = datetime.date.today().isoformat()
    print(f"Fetching results for {yesterday} ...", file=sys.stderr)

    results = []
    for team in TEAMS:
        try:
            data = process_team(team, yesterday, today)
            if data:
                results.append(data)
                print(f"  OK  {data['team']}: {data['result']} {data['score']} vs {data['opponent']}", file=sys.stderr)
            else:
                print(f"  --  {team['teamName']}: no match", file=sys.stderr)
        except Exception as e:
            print(f"  ERR {team['teamName']}: {e}", file=sys.stderr)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
