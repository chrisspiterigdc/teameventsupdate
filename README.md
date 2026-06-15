# Team Events Update — Premier League & FIFA World Cup 2026

Checks all 20 Premier League teams and all FIFA World Cup 2026 teams for today's fixtures, generates summaries and page intros via Claude, and posts them to Slack channel `C0AVBC6256C`.

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

---

## FIFA World Cup 2026 Routine

### 1. Fetch fixtures

Check today's **and** tomorrow's World Cup 2026 fixtures using the n8n MCP tool (workflow ID `2Ki8OH2pDXd7J0DI`). Fetch both dates in parallel by passing the full OpticOdds URL in the webhook body:

```
https://api.opticodds.com/api/v3/fixtures?sport=soccer&league=fifa_-_world_cup&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

### 2. Validate the data

Before writing anything, validate the data:

- Completed fixtures must have scores populated
- Unplayed fixtures must not have scores
- No score should be negative or above 20
- Each fixture's date must match today or tomorrow
- Team names must not be blank or identical

Flag any issues and stop if something looks wrong.

### 3. Generate content

All kick-off times must be displayed in BST (British Summer Time, UTC+1). Convert all times from the UTC values returned by the API before writing any content.

Once validated, generate two things:

1. A short Slack update summarising today's results and tomorrow's kick-offs
2. A 3-paragraph page intro for every team with a fixture (today or tomorrow)

**Completed match intros** — reflect the result and what it means for their campaign. Only state facts the data directly confirms: the final score and the half-time score (period 1 totals). Do not infer or describe the sequence of goals within a half — the API returns period totals only, not a goal-by-goal timeline, so the order of scoring is unknown.

**Upcoming match intros** — cover the fixture context and what's at stake.

Every intro must:
- Open with the exact words `[Team] World Cup odds`
- Close with a line saying the page updates after each match

### 4. Humanize all content

Run every piece of generated content through `/the-humanizer` before doing anything with it. Do not skip this step.

### 5. Post to Slack

Once humanized, post to Slack channel `C0AVBC6256C` using the Slack MCP tool only — no bot token.

- Post the match update and completed-match intros as the **main message**
- Thread the upcoming-match intros as **replies**
- Keep each message under 4,500 characters and split into further thread replies if needed

---

## Premier League Data Sources

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
