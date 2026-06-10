#!/usr/bin/env python3
"""
Premier League + FIFA World Cup 2026 match results checker.
Fetches today's EPL and WC fixtures, generates summaries/page intros via Claude,
and posts them to Slack (two separate messages).
"""

import json
import os
import re
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from anthropic import Anthropic

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

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
WC_FIXTURES_FALLBACK = "/tmp/wc_fixtures_today.json"

# All 48 FIFA World Cup 2026 teams (verify/update as final qualifiers are confirmed)
WC2026_TEAMS = [
    # CONMEBOL (6)
    "Argentina", "Brazil", "Colombia", "Ecuador", "Uruguay", "Venezuela",
    # UEFA (16)
    "England", "France", "Germany", "Spain", "Portugal", "Netherlands",
    "Belgium", "Croatia", "Austria", "Switzerland", "Denmark", "Serbia",
    "Poland", "Ukraine", "Romania", "Albania",
    # CONCACAF (6 + 3 hosts)
    "United States", "Mexico", "Canada", "Panama", "Costa Rica", "Jamaica",
    "Honduras", "El Salvador", "Trinidad and Tobago",
    # AFC (8 + 1 host)
    "Japan", "South Korea", "Australia", "Iran", "Saudi Arabia", "Qatar",
    "Jordan", "Iraq", "Uzbekistan",
    # CAF (9)
    "Morocco", "Senegal", "Egypt", "Nigeria", "South Africa",
    "Ivory Coast", "Ghana", "Tunisia", "Algeria",
    # OFC (1)
    "New Zealand",
    # Intercontinental play-off winners (adjust when confirmed)
    "Indonesia", "Paraguay",
]


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


# ---------------------------------------------------------------------------
# World Cup 2026 fixture fetchers (same Optic Odds API, different league slug)
# ---------------------------------------------------------------------------

WC_LEAGUE_SLUG = "fifa_-_world_cup"


def fetch_wc_fixtures_via_proxy(target_date: str) -> list[dict]:
    """Fetch WC 2026 fixtures via n8n OpticOdds proxy."""
    url = (
        f"{OPTICODDS_BASE}/fixtures"
        f"?sport=soccer&league={WC_LEAGUE_SLUG}"
        f"&start_date={target_date}&end_date={target_date}"
    )
    resp = requests.post(N8N_PROXY_URL, json={"url": url}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_wc_fixtures_direct(target_date: str) -> list[dict]:
    """Fetch WC 2026 fixtures directly from Optic Odds (requires API key)."""
    url = (
        f"{OPTICODDS_BASE}/fixtures"
        f"?sport=soccer&league={WC_LEAGUE_SLUG}"
        f"&start_date={target_date}&end_date={target_date}"
        f"&key={OPTICODDS_KEY}"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_wc_from_bbc(target_date: str) -> list[dict]:
    """Scrape BBC Sport for WC 2026 match scores."""
    if not BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 not installed")
    url = f"https://www.bbc.com/sport/football/world-cup-2026/scores-fixtures/{target_date}"
    resp = requests.get(url, headers=BBC_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    fixtures = []
    for item in soup.select("[data-fixture-id], [data-test='fixture-row']"):
        try:
            teams = item.select(".sp-c-fixture__team-name-trunc, .gs-u-display-none")
            scores = item.select(".sp-c-fixture__number")
            status_el = item.select_one(".sp-c-fixture__status")
            if len(teams) < 2:
                continue
            home_name = teams[0].get_text(strip=True)
            away_name = teams[1].get_text(strip=True)
            status_text = status_el.get_text(strip=True) if status_el else ""
            home_score = int(scores[0].get_text(strip=True)) if len(scores) >= 2 else None
            away_score = int(scores[1].get_text(strip=True)) if len(scores) >= 2 else None
            is_completed = "FT" in status_text or "AET" in status_text
            context_parts = []
            for el in item.select(
                ".sp-c-fixture__scorers, [class*='scorer'], [class*='goal'],"
                "[class*='venue'], [class*='attendance'], [class*='summary'],"
                "[class*='detail'], [aria-label]"
            ):
                text = el.get_text(" ", strip=True)
                if text and text not in context_parts:
                    context_parts.append(text)
            fixture = {
                "home_team_display": home_name,
                "away_team_display": away_name,
                "start_date": f"{target_date}T00:00:00Z",
                "status": "completed" if is_completed else "unplayed",
                "season_week": "",
                "venue_name": "",
                "bbc_context": " | ".join(context_parts),
                "result": {
                    "scores": {
                        "home": {"total": home_score},
                        "away": {"total": away_score},
                    } if home_score is not None else None
                },
            }
            fixtures.append(fixture)
        except Exception:
            continue
    return fixtures


def fetch_wc_from_flashscore(target_date: str) -> list[dict]:
    """Scrape FlashScore mobile for WC 2026 results."""
    if not BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 not installed")
    url = "https://www.flashscore.mobi/football/world/world-cup/"
    resp = requests.get(url, headers=FS_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    fixtures = []
    today = target_date
    for row in soup.select(".event__match, .row, [class*='match']"):
        try:
            text = row.get_text(" ", strip=True)
            if today.replace("-", ".") not in text and today not in text:
                continue
            teams = row.select(".event__participant, .team-name, [class*='team']")
            scores_el = row.select(".event__score, .score")
            if len(teams) < 2:
                continue
            home_name = teams[0].get_text(strip=True)
            away_name = teams[1].get_text(strip=True)
            home_score = away_score = None
            if len(scores_el) >= 2:
                try:
                    home_score = int(scores_el[0].get_text(strip=True))
                    away_score = int(scores_el[1].get_text(strip=True))
                except ValueError:
                    pass
            status_el = row.select_one("[class*='status'], [class*='stage']")
            status_text = status_el.get_text(strip=True) if status_el else ""
            is_completed = home_score is not None and ("FT" in status_text or "Finished" in status_text)
            fixture = {
                "home_team_display": home_name,
                "away_team_display": away_name,
                "start_date": f"{target_date}T00:00:00Z",
                "status": "completed" if is_completed else "unplayed",
                "season_week": "",
                "venue_name": "",
                "bbc_context": "",
                "result": {
                    "scores": {
                        "home": {"total": home_score},
                        "away": {"total": away_score},
                    } if home_score is not None else None
                },
            }
            fixtures.append(fixture)
        except Exception:
            continue
    return fixtures


def get_today_wc_fixtures() -> tuple[list[dict], str]:
    """
    Fetch WC 2026 fixtures for today. Same fallback priority as EPL:
      1+2. Optic Odds (n8n proxy) + BBC Sport  — simultaneous (primary)
      3+2. Optic Odds (direct)   + BBC Sport  — simultaneous (fallback)
        4. BBC Sport alone
        5. FlashScore mobile scraper
        6. Pre-fetched local file
    """
    today = date.today().isoformat()

    def _try_proxy():
        return fetch_wc_fixtures_via_proxy(today)

    def _try_direct():
        return fetch_wc_fixtures_direct(today) if OPTICODDS_KEY else None

    def _try_bbc():
        return fetch_wc_from_bbc(today)

    opticodds_fixtures = bbc_fixtures = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_odds = ex.submit(_try_proxy)
        fut_bbc = ex.submit(_try_bbc)
        try:
            opticodds_fixtures = fut_odds.result()
            print(f"[WC] Fetched {len(opticodds_fixtures)} fixture(s) via n8n proxy")
        except Exception as e:
            print(f"[WC] n8n proxy unavailable: {e}", file=sys.stderr)
        try:
            bbc_fixtures = fut_bbc.result()
            print(f"[WC] Fetched {len(bbc_fixtures)} fixture(s) from BBC Sport")
        except Exception as e:
            print(f"[WC] BBC Sport unavailable: {e}", file=sys.stderr)

    if opticodds_fixtures is not None:
        if bbc_fixtures:
            opticodds_fixtures = merge_with_bbc(opticodds_fixtures, bbc_fixtures)
            return opticodds_fixtures, "Optic Odds (n8n proxy) + BBC Sport"
        return opticodds_fixtures, "Optic Odds (n8n proxy)"

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_odds = ex.submit(_try_direct)
        fut_bbc = ex.submit(_try_bbc) if bbc_fixtures is None else None
        try:
            opticodds_fixtures = fut_odds.result()
            if opticodds_fixtures is not None:
                print(f"[WC] Fetched {len(opticodds_fixtures)} fixture(s) directly from Optic Odds")
        except Exception as e:
            print(f"[WC] Optic Odds direct unavailable: {e}", file=sys.stderr)
        if fut_bbc is not None:
            try:
                bbc_fixtures = fut_bbc.result()
                print(f"[WC] Fetched {len(bbc_fixtures)} fixture(s) from BBC Sport")
            except Exception as e:
                print(f"[WC] BBC Sport unavailable: {e}", file=sys.stderr)

    if opticodds_fixtures is not None:
        if bbc_fixtures:
            opticodds_fixtures = merge_with_bbc(opticodds_fixtures, bbc_fixtures)
            return opticodds_fixtures, "Optic Odds (direct) + BBC Sport"
        return opticodds_fixtures, "Optic Odds (direct)"

    if bbc_fixtures:
        return bbc_fixtures, "BBC Sport"

    try:
        fixtures = fetch_wc_from_flashscore(today)
        if fixtures:
            print(f"[WC] Fetched {len(fixtures)} fixture(s) from FlashScore")
            return fixtures, "FlashScore"
    except Exception as e:
        print(f"[WC] FlashScore unavailable: {e}", file=sys.stderr)

    if os.path.exists(WC_FIXTURES_FALLBACK):
        fixtures = load_fixtures_from_file(WC_FIXTURES_FALLBACK)
        print(f"[WC] Loaded {len(fixtures)} fixture(s) from fallback file")
        return fixtures, "pre-fetched file"

    return [], "no source available"


# ---------------------------------------------------------------------------
# BBC Sport scraper
# ---------------------------------------------------------------------------

BBC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PremierLeagueBot/1.0)"
    )
}

# Canonical name map: BBC uses shorter names, normalise to our EPL_TEAMS list
BBC_NAME_MAP = {
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion FC",
    "Brighton and Hove Albion": "Brighton & Hove Albion FC",
    "Man City": "Manchester City FC",
    "Manchester City": "Manchester City FC",
    "Man Utd": "Manchester United FC",
    "Manchester United": "Manchester United FC",
    "Newcastle": "Newcastle United FC",
    "Newcastle United": "Newcastle United FC",
    "Nott'm Forest": "Nottingham Forest FC",
    "Nottingham Forest": "Nottingham Forest FC",
    "Spurs": "Tottenham Hotspur FC",
    "Tottenham": "Tottenham Hotspur FC",
    "West Ham": "West Ham United FC",
    "Wolves": "Wolverhampton Wanderers FC",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers FC",
}


def _normalise_bbc_name(raw: str) -> str:
    raw = raw.strip()
    if raw in BBC_NAME_MAP:
        return BBC_NAME_MAP[raw]
    for team in EPL_TEAMS:
        if raw.lower() in team.lower() or team.lower().startswith(raw.lower()):
            return team
    return raw + " FC" if not raw.endswith("FC") else raw


def fetch_from_bbc(target_date: str) -> list[dict]:
    """
    Scrape BBC Sport scores-fixtures page for EPL matches.
    URL: https://www.bbc.com/sport/football/premier-league/scores-fixtures/{date}
    Returns fixtures with an extra 'bbc_context' field containing any rich text
    found alongside each match (scorers, venue, attendance, match blurb).
    Requires beautifulsoup4. Works in production; blocked in Claude Code sandbox.
    """
    if not BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 not installed")

    url = f"https://www.bbc.com/sport/football/premier-league/scores-fixtures/{target_date}"
    resp = requests.get(url, headers=BBC_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    fixtures = []

    for item in soup.select("[data-fixture-id], [data-test='fixture-row']"):
        try:
            teams = item.select(".sp-c-fixture__team-name-trunc, .gs-u-display-none")
            scores = item.select(".sp-c-fixture__number")
            status_el = item.select_one(".sp-c-fixture__status")

            if len(teams) < 2:
                continue

            home_name = _normalise_bbc_name(teams[0].get_text(strip=True))
            away_name = _normalise_bbc_name(teams[1].get_text(strip=True))
            status_text = status_el.get_text(strip=True) if status_el else ""

            home_score = int(scores[0].get_text(strip=True)) if len(scores) >= 2 else None
            away_score = int(scores[1].get_text(strip=True)) if len(scores) >= 2 else None

            is_completed = "FT" in status_text or "AET" in status_text
            status = "completed" if is_completed else "unplayed"

            # Collect any additional context: scorers, venue, attendance, blurbs
            context_parts = []
            for el in item.select(
                ".sp-c-fixture__scorers, [class*='scorer'], [class*='goal'],"
                "[class*='venue'], [class*='attendance'], [class*='summary'],"
                "[class*='detail'], [aria-label]"
            ):
                text = el.get_text(" ", strip=True)
                if text and text not in context_parts:
                    context_parts.append(text)
            bbc_context = " | ".join(context_parts) if context_parts else ""

            fixture = {
                "home_team_display": home_name,
                "away_team_display": away_name,
                "start_date": f"{target_date}T00:00:00Z",
                "status": status,
                "season_week": "",
                "venue_name": "",
                "bbc_context": bbc_context,
                "result": {
                    "scores": {
                        "home": {"total": home_score},
                        "away": {"total": away_score},
                    } if home_score is not None else None
                },
            }
            fixtures.append(fixture)
        except Exception:
            continue

    return fixtures


def _bbc_context_map(bbc_fixtures: list[dict]) -> dict[tuple, str]:
    """Return a lookup of (home_team, away_team) -> bbc_context string."""
    result = {}
    for fix in bbc_fixtures:
        key = (fix["home_team_display"], fix["away_team_display"])
        result[key] = fix.get("bbc_context", "")
    return result


def merge_with_bbc(opticodds_fixtures: list[dict], bbc_fixtures: list[dict]) -> list[dict]:
    """
    Enrich Optic Odds fixtures with BBC Sport context.
    Optic Odds is the authoritative source for structure/scores; BBC adds
    any extra detail (scorers, attendance, match blurbs) via 'bbc_context'.
    """
    ctx = _bbc_context_map(bbc_fixtures)
    for fix in opticodds_fixtures:
        key = (fix.get("home_team_display", ""), fix.get("away_team_display", ""))
        fix["bbc_context"] = ctx.get(key, "")
    return opticodds_fixtures


# ---------------------------------------------------------------------------
# FlashScore scraper (mobile site — lighter HTML, no JS required)
# ---------------------------------------------------------------------------

FS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    )
}

FS_NAME_MAP = {
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion FC",
    "Man City": "Manchester City FC",
    "Man Utd": "Manchester United FC",
    "Newcastle": "Newcastle United FC",
    "Nott'm Forest": "Nottingham Forest FC",
    "Nottm Forest": "Nottingham Forest FC",
    "Tottenham": "Tottenham Hotspur FC",
    "West Ham": "West Ham United FC",
    "Wolves": "Wolverhampton Wanderers FC",
}


def _normalise_fs_name(raw: str) -> str:
    raw = raw.strip()
    if raw in FS_NAME_MAP:
        return FS_NAME_MAP[raw]
    for team in EPL_TEAMS:
        if raw.lower() in team.lower():
            return team
    return raw


def fetch_from_flashscore(target_date: str) -> list[dict]:
    """
    Scrape FlashScore mobile site for EPL results.
    URL: https://www.flashscore.mobi/football/england/premier-league/
    Note: FlashScore's main site is JS-rendered; this uses the lighter mobile
    version which has some static HTML. May break if FlashScore changes structure.
    Requires beautifulsoup4.
    """
    if not BS4_AVAILABLE:
        raise RuntimeError("beautifulsoup4 not installed")

    url = "https://www.flashscore.mobi/football/england/premier-league/"
    resp = requests.get(url, headers=FS_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    fixtures = []
    today = target_date  # YYYY-MM-DD

    for row in soup.select(".event__match, .row, [class*='match']"):
        try:
            text = row.get_text(" ", strip=True)
            # Look for date pattern
            if today.replace("-", ".") not in text and today not in text:
                continue

            teams = row.select(".event__participant, .team-name, [class*='team']")
            scores_el = row.select(".event__score, .score")

            if len(teams) < 2:
                continue

            home_name = _normalise_fs_name(teams[0].get_text(strip=True))
            away_name = _normalise_fs_name(teams[1].get_text(strip=True))

            home_score = away_score = None
            if len(scores_el) >= 2:
                try:
                    home_score = int(scores_el[0].get_text(strip=True))
                    away_score = int(scores_el[1].get_text(strip=True))
                except ValueError:
                    pass

            status_el = row.select_one("[class*='status'], [class*='stage']")
            status_text = status_el.get_text(strip=True) if status_el else ""
            is_completed = home_score is not None and ("FT" in status_text or "Finished" in status_text)

            fixture = {
                "home_team_display": home_name,
                "away_team_display": away_name,
                "start_date": f"{target_date}T00:00:00Z",
                "status": "completed" if is_completed else "unplayed",
                "season_week": "",
                "venue_name": "",
                "result": {
                    "scores": {
                        "home": {"total": home_score},
                        "away": {"total": away_score},
                    } if home_score is not None else None
                },
            }
            fixtures.append(fixture)
        except Exception:
            continue

    return fixtures


# ---------------------------------------------------------------------------
# Main data fetch — Optic Odds + BBC Sport run simultaneously
# ---------------------------------------------------------------------------

def get_today_fixtures() -> tuple[list[dict], str]:
    """
    Fetch EPL fixtures for today.

    Optic Odds (via n8n proxy or direct) and BBC Sport are fetched in parallel.
    Optic Odds is the authoritative source for fixture structure and scores;
    BBC Sport enriches each fixture with additional context (scorers, attendance,
    match blurbs) stored in the 'bbc_context' field passed to Claude.

    Full priority:
      1+3. Optic Odds (n8n proxy) + BBC Sport  — simultaneous (primary)
      2+3. Optic Odds (direct)   + BBC Sport  — simultaneous (production fallback)
        4. FlashScore mobile scraper           — fallback if both above fail
        5. Pre-fetched local file              — offline fallback
    """
    today = date.today().isoformat()

    def _try_opticodds_proxy():
        return fetch_fixtures_via_proxy(today)

    def _try_opticodds_direct():
        return fetch_fixtures_direct(today) if OPTICODDS_KEY else None

    def _try_bbc():
        return fetch_from_bbc(today)

    # --- Attempt 1: n8n proxy + BBC Sport in parallel ---
    opticodds_fixtures = bbc_fixtures = None
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_odds = ex.submit(_try_opticodds_proxy)
        fut_bbc = ex.submit(_try_bbc)

        try:
            opticodds_fixtures = fut_odds.result()
            print(f"Fetched {len(opticodds_fixtures)} fixture(s) via n8n Optic Odds proxy")
        except Exception as e:
            print(f"n8n proxy unavailable: {e}", file=sys.stderr)

        try:
            bbc_fixtures = fut_bbc.result()
            print(f"Fetched {len(bbc_fixtures)} fixture(s) from BBC Sport")
        except Exception as e:
            print(f"BBC Sport unavailable: {e}", file=sys.stderr)

    if opticodds_fixtures is not None:
        if bbc_fixtures:
            opticodds_fixtures = merge_with_bbc(opticodds_fixtures, bbc_fixtures)
            return opticodds_fixtures, "Optic Odds API (n8n proxy) + BBC Sport"
        return opticodds_fixtures, "Optic Odds API (n8n proxy)"

    # --- Attempt 2: direct Optic Odds + BBC Sport in parallel ---
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_odds = ex.submit(_try_opticodds_direct)
        fut_bbc = ex.submit(_try_bbc) if bbc_fixtures is None else None

        try:
            opticodds_fixtures = fut_odds.result()
            if opticodds_fixtures is not None:
                print(f"Fetched {len(opticodds_fixtures)} fixture(s) directly from Optic Odds")
        except Exception as e:
            print(f"Optic Odds direct unavailable: {e}", file=sys.stderr)

        if fut_bbc is not None:
            try:
                bbc_fixtures = fut_bbc.result()
                print(f"Fetched {len(bbc_fixtures)} fixture(s) from BBC Sport")
            except Exception as e:
                print(f"BBC Sport unavailable: {e}", file=sys.stderr)

    if opticodds_fixtures is not None:
        if bbc_fixtures:
            opticodds_fixtures = merge_with_bbc(opticodds_fixtures, bbc_fixtures)
            return opticodds_fixtures, "Optic Odds API (direct) + BBC Sport"
        return opticodds_fixtures, "Optic Odds API (direct)"

    # --- Attempt 3: BBC Sport alone (already fetched above) ---
    if bbc_fixtures:
        return bbc_fixtures, "BBC Sport"

    # --- Attempt 4: FlashScore ---
    try:
        fixtures = fetch_from_flashscore(today)
        if fixtures:
            print(f"Fetched {len(fixtures)} fixture(s) from FlashScore")
            return fixtures, "FlashScore"
    except Exception as e:
        print(f"FlashScore unavailable: {e}", file=sys.stderr)

    # --- Attempt 5: local file ---
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
            line = (
                f"- {fix['home_team_display']} {score} {fix['away_team_display']}"
                f" (GW{fix.get('season_week','?')}, {fix.get('venue_name','')})"
            )
            ctx = fix.get("bbc_context", "").strip()
            if ctx:
                line += f"\n  BBC context: {ctx}"
            lines.append(line)
        completed_text = "COMPLETED MATCHES:\n" + "\n".join(lines)

    scheduled_text = ""
    if scheduled:
        lines = []
        for fix in scheduled:
            line = (
                f"- {fix['home_team_display']} vs {fix['away_team_display']}"
                f" at {format_kickoff(fix['start_date'])} (GW{fix.get('season_week','?')}, {fix.get('venue_name','')})"
            )
            ctx = fix.get("bbc_context", "").strip()
            if ctx:
                line += f"\n  BBC context: {ctx}"
            lines.append(line)
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


# ---------------------------------------------------------------------------
# World Cup page intro generator
# ---------------------------------------------------------------------------

def generate_wc_page_intro(client: Anthropic, team: str, fixture: dict) -> str:
    """
    Generate an updated odds-page introduction for a WC team.
    Produces a preview if the match is upcoming, or a result recap if completed.
    The intro must open with '[Team] World Cup odds'.
    """
    is_completed = fixture.get("status") == "completed"
    score = score_str(fixture)
    opponent = (
        fixture["away_team_display"]
        if fixture["home_team_display"] == team
        else fixture["home_team_display"]
    )
    home_away = "home" if fixture["home_team_display"] == team else "away"
    venue = fixture.get("venue_name", "")
    kickoff = format_kickoff(fixture["start_date"])
    bbc_ctx = fixture.get("bbc_context", "").strip()

    if is_completed:
        match_desc = (
            f"{team} played {home_away} against {opponent}"
            + (f" at {venue}" if venue else "")
            + (f", final score {score}" if score else "")
            + (f". Additional context: {bbc_ctx}" if bbc_ctx else "")
        )
        prompt = f"""You are a sports betting content writer updating a World Cup odds page for {team}.

Today's result:
{match_desc}

Write a 2–3 paragraph introduction for the '{team} World Cup odds' page that:
- Opens with the exact words "{team} World Cup odds" as the very first words of the text.
- Reflects their tournament performance based on today's result.
- Mentions the opponent, score, and what the result means for their campaign.
- Ends noting the page updates after each match and readers should check back for latest odds and next match previews.
- Plain text only (no markdown). Punchy, factual, SEO-suitable."""
    else:
        match_desc = (
            f"{team} play {home_away} against {opponent}"
            + (f" at {venue}" if venue else "")
            + f" today, kick-off {kickoff}."
        )
        prompt = f"""You are a sports betting content writer updating a World Cup odds page for {team}.

Today's upcoming fixture:
{match_desc}

Write a 2–3 paragraph introduction for the '{team} World Cup odds' page that:
- Opens with the exact words "{team} World Cup odds" as the very first words of the text.
- Covers the current tournament situation — their group, key players, what's at stake in today's match.
- Builds anticipation for the fixture with relevant context (form, squad strength, tournament ambitions).
- Ends noting the page will be updated with their result after the match and readers should check back for latest odds analysis.
- Plain text only (no markdown). Punchy, factual, SEO-suitable."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_wc_slack_message(
    fixtures: list[dict],
    intros: dict[str, str],
    source: str,
    today_str: str,
) -> str:
    completed = [f for f in fixtures if f.get("status") == "completed"]
    scheduled = [f for f in fixtures if f.get("status") in ("unplayed", "scheduled")]

    lines = [
        f"*FIFA World Cup 2026 Update — {today_str}*",
        "",
    ]

    if completed:
        lines.append(f"*Results today ({len(completed)} match{'es' if len(completed) != 1 else ''}):*")
        for fix in completed:
            sc = score_str(fix)
            lines.append(f"• {fix['home_team_display']} {sc} {fix['away_team_display']} ✅")
        lines.append("")

    if scheduled:
        lines.append(f"*Upcoming today ({len(scheduled)} match{'es' if len(scheduled) != 1 else ''}):*")
        for fix in scheduled:
            lines.append(
                f"• {fix['home_team_display']} vs {fix['away_team_display']}"
                f" — KO {format_kickoff(fix['start_date'])} 🕐"
            )
        lines.append("")

    if not completed and not scheduled:
        lines.append("No World Cup fixtures today.")
        lines.append("")

    if intros:
        lines.append("*Updated page intros (copy-paste into CMS):*")
        lines.append("─" * 40)
        for team, intro in intros.items():
            lines.append(f"*{team}*")
            lines.append(intro)
            lines.append("─" * 40)

    lines.append(f"_Source: {source}_")
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
    client = _make_anthropic_client()

    # -----------------------------------------------------------------------
    # Part 1: Premier League
    # -----------------------------------------------------------------------
    print(f"\n=== Premier League Match Results — {today_str} ===\n")

    fixtures, source = get_today_fixtures()
    completed = [f for f in fixtures if f.get("status") == "completed"]
    scheduled = [f for f in fixtures if f.get("status") in ("unplayed", "scheduled")]
    print(f"Fixtures found: {len(fixtures)} total, {len(completed)} completed, {len(scheduled)} scheduled")

    team_status = build_team_status(fixtures)

    print("\nGenerating EPL summary via Claude...")
    summary = generate_summary(client, completed, scheduled)
    print(f"\nSummary:\n{summary}\n")

    epl_slack_msg = build_slack_message(team_status, summary, source, today_str)
    print("=== EPL SLACK MESSAGE ===")
    print(epl_slack_msg)
    print("========================\n")

    epl_posted = post_to_slack(epl_slack_msg)
    if epl_posted:
        print("EPL message posted to Slack successfully.")
    else:
        print("EPL Slack posting not available — message printed above.")

    # -----------------------------------------------------------------------
    # Part 2: FIFA World Cup 2026
    # -----------------------------------------------------------------------
    print(f"\n=== FIFA World Cup 2026 — {today_str} ===\n")

    wc_fixtures, wc_source = get_today_wc_fixtures()
    wc_completed = [f for f in wc_fixtures if f.get("status") == "completed"]
    wc_scheduled = [f for f in wc_fixtures if f.get("status") in ("unplayed", "scheduled")]
    print(f"[WC] Fixtures: {len(wc_fixtures)} total, {len(wc_completed)} completed, {len(wc_scheduled)} scheduled")

    # Generate page intros for all teams with a fixture today (completed or scheduled)
    team_fixture_map: dict[str, dict] = {}
    for fix in wc_completed:
        team_fixture_map[fix["home_team_display"]] = fix
        team_fixture_map[fix["away_team_display"]] = fix
    for fix in wc_scheduled:
        # completed takes priority if a team has both (shouldn't happen, but safe)
        team_fixture_map.setdefault(fix["home_team_display"], fix)
        team_fixture_map.setdefault(fix["away_team_display"], fix)

    wc_intros: dict[str, str] = {}
    if team_fixture_map:
        print(f"\nGenerating WC page intros for {len(team_fixture_map)} team(s) via Claude...")
        for team in sorted(team_fixture_map):
            fix = team_fixture_map[team]
            label = "result" if fix.get("status") == "completed" else "preview"
            print(f"  [{label}] {team}...")
            wc_intros[team] = generate_wc_page_intro(client, team, fix)
    else:
        print("[WC] No fixtures today — skipping page intro generation.")

    wc_slack_msg = build_wc_slack_message(wc_fixtures, wc_intros, wc_source, today_str)
    print("\n=== WC SLACK MESSAGE ===")
    print(wc_slack_msg)
    print("========================\n")

    wc_posted = post_to_slack(wc_slack_msg)
    if wc_posted:
        print("WC message posted to Slack successfully.")
    else:
        print("WC Slack posting not available — message printed above.")

    return epl_slack_msg, wc_slack_msg


if __name__ == "__main__":
    main()
