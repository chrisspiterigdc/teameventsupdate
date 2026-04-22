# Team Events Update — Premier League Match Results

Checks all 20 Premier League teams for today's completed matches, generates summaries via Claude, and posts them to Slack.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python check_results.py
```

## Configuration

| Variable | Description |
|---|---|
| `OPTICODDS_KEY` | Optic Odds API key for fetching fixtures |
| `SLACK_BOT_TOKEN` | Slack bot token for posting messages |

**Slack channel:** Posts exclusively to `C0AVBC6256C` — do not change this.

## Data source

Fixtures are fetched from the Optic Odds API via the n8n proxy workflow (`2Ki8OH2pDXd7J0DI`).
Falls back to a direct API call, then to `/tmp/epl_fixtures_today.json` if the network is unavailable.
