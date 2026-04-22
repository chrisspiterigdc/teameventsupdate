# teameventsupdate

Checks today's completed Premier League matches, generates a short editorial "Latest [Team] News" blurb per involved club using Claude, and posts the results to Slack.

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

python check_results.py                        # today
python check_results.py 2026-04-21             # specific date
```

## What it does

1. Fetches finished Premier League fixtures for the target date.
   - If `FOOTBALL_DATA_API_KEY` is set, calls the football-data.org v4 API.
   - Otherwise falls back to the `_mock_matches()` dict in `check_results.py`, keyed by date.
2. For every listed club in each fixture, calls Claude (`claude-opus-4-7`) to generate a `Latest [Team] News` paragraph.
3. Posts each blurb to Slack (via `SLACK_CHANNEL`) or prints to stdout.

Only the 20 clubs in `PREMIER_LEAGUE_TEAMS` produce a summary. Alternate names (Spurs, Wolves, Man Utd, etc.) are normalised via `TEAM_ALIASES`.

## Adding match data for new dates

When the football-data.org API is not reachable (for example in a sandboxed environment), add an entry to the `known` dict inside `_mock_matches()`. Each match needs:

- `homeTeam`, `awayTeam`: `{"name": "..."}` using the canonical name from `PREMIER_LEAGUE_TEAMS`.
- `score`: `{"fullTime": {"home": int, "away": int}, "halfTime": {"home": int, "away": int}}`.
- `context`: per-team strings describing the post-match league position, points, European implications, notable runs or stats. The blurb generator threads this directly into the prompt, so anything worth mentioning (scorers, manager pressure, historical records) belongs here.

Example:

```python
"2026-04-21": [
    {
        "homeTeam": {"name": "Brighton & Hove Albion"},
        "awayTeam": {"name": "Chelsea"},
        "score": {"fullTime": {"home": 3, "away": 0}, "halfTime": {"home": 1, "away": 0}},
        "status": "FINISHED",
        "utcDate": "2026-04-21T15:00:00Z",
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
