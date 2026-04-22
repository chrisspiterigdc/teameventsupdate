# Premier League Match Results → Slack

## What this routine does

Checks all 25 Premier League teams for today's completed match results, generates a punchy supporter-facing summary via Claude, and posts a formatted message to Slack for each team that played.

## How to run

```bash
pip install -r requirements.txt
python check_results.py
```

## Required environment variables

Set these in your Routine settings at claude.ai/code/routines:

| Variable | Description |
|---|---|
| `OPTICODDS_KEY` | OpticOdds API key |
| `CLAUDE_API_KEY` | Anthropic Claude API key |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

## Recommended schedule

Hourly — matches are checked against today's date so duplicate runs are safe.

## Files

- `check_results.py` — main script, runs end-to-end
- `requirements.txt` — Python dependencies (just `requests`)
- `workflow.json` — legacy n8n workflow (kept for reference)
