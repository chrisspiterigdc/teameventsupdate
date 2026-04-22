# teameventsupdate

Checks **yesterday's** completed Premier League matches, generates a short editorial "Latest [Team] News" blurb per involved club using Claude, and posts the results to Slack.

Yesterday is always the default target date. Matches typically finish late in the day, so by the time this runs (next morning), yesterday's fixtures have final scores and settled league-table implications. A specific date can be passed as an argument to override.

## Quick start

```bash
pip install -r requirements.txt

# Required: one of these for Claude
export ANTHROPIC_API_KEY=sk-ant-api03-...      # standard API key
# or
export ANTHROPIC_AUTH_TOKEN=sk-ant-si-...      # OAuth / session ingress token

# Optional
export SLACK_BOT_TOKEN=xoxb-...                # omit to print to stdout
export SLACK_CHANNEL=C0AVBC6256C               # channel ID (default: #match-results)
export FOOTBALL_DATA_API_KEY=...               # omit to use built-in mock data

python check_results.py                        # yesterday (default)
python check_results.py 2026-04-21             # specific date override
```

## What it does

1. Fetches finished Premier League fixtures for the target date.
2. For every listed club in each fixture, calls Claude (`claude-opus-4-7`) to generate a `Latest [Team] News` paragraph.
3. Posts each blurb to Slack (via `SLACK_CHANNEL`) or prints to stdout.

## Data sources

The script uses a layered source strategy. From most canonical to last-resort:

| Layer | Source | Purpose | Status |
| --- | --- | --- | --- |
| 1 | **Flashscore** | Scores, half-time scores, scorers, minute timings | Canonical. Needs a headless browser in production (JS-rendered, no public API). `fetch_flashscore_results()` stub. |
| 2 | **BBC Sport** | Post-match narrative, manager quotes, tactical context, statistical runs | Enrichment. No public API; scrape match-report pages via `fetch_bbc_match_details()`. |
| 3 | `football-data.org` v4 | Structured fixtures/results | Fallback when Flashscore is unavailable. Requires `FOOTBALL_DATA_API_KEY`. |
| 4 | `_mock_matches()` | Hand-curated offline fixtures keyed by date | Last-resort fallback for sandboxes / unreachable networks. Each entry has `sources` pointing to the Flashscore match URL and the BBC page used when populating it. |

In sandboxed environments (no outbound access to Flashscore/BBC), the script transparently walks down to mock data. The mock entries still attribute their figures to Flashscore + BBC so Claude has accurate provenance to draw on.

Only the 20 clubs in `PREMIER_LEAGUE_TEAMS` produce a summary. Alternate names (Spurs, Wolves, Man Utd, etc.) are normalised via `TEAM_ALIASES`.

## Adding match data for new dates

When the football-data.org API is not reachable (for example in a sandboxed environment), add an entry to the `known` dict inside `_mock_matches()`. Each match needs:

- `homeTeam`, `awayTeam`: `{"name": "..."}` using the canonical name from `PREMIER_LEAGUE_TEAMS`.
- `score`: `{"fullTime": {"home": int, "away": int}, "halfTime": {"home": int, "away": int}}` - take from Flashscore.
- `sources`: `{"results": "<flashscore match url>", "details": "<bbc url>"}` for attribution.
- `context`: per-team strings describing the post-match league position, points, European implications, notable runs or stats. Pull specific details (scorers, minutes, manager quotes, historical records) from BBC Sport match reports. The blurb generator threads this directly into the prompt.

Example:

```python
"2026-04-21": [
    {
        "homeTeam": {"name": "Brighton & Hove Albion"},
        "awayTeam": {"name": "Chelsea"},
        "score": {"fullTime": {"home": 3, "away": 0}, "halfTime": {"home": 1, "away": 0}},
        "status": "FINISHED",
        "utcDate": "2026-04-21T15:00:00Z",
        "sources": {
            "results": "https://www.flashscore.com/match/football/brighton-2XrRecc3/chelsea-4fGZN2oK/",
            "details": "https://www.bbc.co.uk/sport/football/premier-league",
        },
        "context": {
            "Brighton & Hove Albion": "Result lifted Brighton into 6th...",
            "Chelsea": "Defeat leaves Chelsea 7th...",
        },
    },
],
```

## Editorial style

Output follows the freebets.com team-page voice:

- Short punchy sentences, narrative-led, not stat-led.
- Present tense, third person.
- 3-4 short paragraphs of 1-2 sentences each.
- Table and European-qualification angles woven in naturally, not listed.
- Short/common team names in body copy (Brighton, Spurs, Man Utd).
- No headers, bullets, emoji, first-person language, or **em dashes (—)**. Use commas, colons, full stops, or hyphens instead.

The prompt in `generate_team_news()` carries a few-shot example from a human writer to anchor the voice. If the style drifts, update that example.

## Model

`claude-opus-4-7` with `max_tokens=500`. Change in `generate_team_news()` if needed.
