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

The script tries each source in order, moving to the next if one fails:

| Priority | Source | Method |
|---|---|---|
| 1 | **Optic Odds API** | n8n proxy workflow `2Ki8OH2pDXd7J0DI` at `/webhook/opticodds-proxy` — no API key needed in the request, credentials stored in n8n |
| 2 | **Optic Odds API** | Direct HTTP call using `OPTICODDS_KEY` env var |
| 3 | **BBC Sport** | Scrapes `bbc.com/sport/football/premier-league/scores-fixtures/{date}` using BeautifulSoup |
| 4 | **FlashScore** | Scrapes `flashscore.mobi` mobile site using BeautifulSoup (may be unreliable if page structure changes) |
| 5 | **Local file** | Reads `/tmp/epl_fixtures_today.json` as an offline fallback |

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
