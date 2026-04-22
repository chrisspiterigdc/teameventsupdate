# Team Events Update — Premier League Match Results

Checks all 20 Premier League teams for today's completed matches, generates summaries via Claude, and posts them to Slack channel `C0AVBC6256C`.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python check_results.py
```

## Slack

Posts **only** to channel `C0AVBC6256C`. This is hardcoded and should not be changed.

## Data Sources

Optic Odds and BBC Sport are always fetched **simultaneously**. Optic Odds is the authoritative source for fixture structure and scores; BBC Sport enriches each fixture with additional context (goal scorers, attendance, match blurbs) that is passed to Claude when generating summaries.

| Priority | Source | Method |
|---|---|---|
| 1 + 3 | **Optic Odds (n8n proxy) + BBC Sport** | Fetched in parallel — primary path |
| 2 + 3 | **Optic Odds (direct) + BBC Sport** | Fetched in parallel — production fallback |
| 4 | **BBC Sport alone** | If Optic Odds fails entirely but BBC succeeded |
| 5 | **FlashScore** | Scrapes `flashscore.mobi` mobile site using BeautifulSoup |
| 6 | **Local file** | Reads `/tmp/epl_fixtures_today.json` as an offline fallback |

### n8n Optic Odds proxy

The primary data source is the Optic Odds API routed through an n8n workflow that holds the API credentials internally. The script calls:

```
POST https://gdcgroup.app.n8n.cloud/webhook/opticodds-proxy
Body: {"url": "https://api.opticodds.com/api/v3/fixtures?sport=soccer&league=england_-_premier_league&start_date=...&end_date=..."}
```

n8n workflow ID: `2Ki8OH2pDXd7J0DI`

### BBC Sport & FlashScore

Scrapers use `requests` + `beautifulsoup4`. Both sites are publicly accessible in standard server environments. FlashScore's main site is JavaScript-rendered; the script targets their lighter mobile version (`flashscore.mobi`), which may need updating if their page structure changes.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes (for posting) | Slack bot token |
| `OPTICODDS_KEY` | Optional | Optic Odds API key (used for direct fallback only) |
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key (falls back to Claude Code session token) |
