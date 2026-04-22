# Premier League Match Results -> Slack

## Task

Run the match results script, then post each result to Slack channel **fb-team-event-updates** (ID: C0AVBC6256C).

## Steps

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the script and capture JSON output:
   ```
   python check_results.py
   ```
   Progress logs go to stderr. The script prints a JSON array to stdout — one object per team that played today.

3. For each item in the JSON output, post a Slack message to channel `C0AVBC6256C` using the Slack connector with this format:

   **Header:** `{team}  |  {result} {score}`

   **Body:**
   ```
   {result emoji}  *vs {opponent}*  ({competition})

   {summary}
   ```
   Use :white_check_mark: for WIN, :x: for LOSS, :heavy_minus_sign: for DRAW.

   **Footer (context line):** `{competition}  |  Next: {next_opponent} ({next_competition})` — omit the Next part if next_opponent is null. If injuries > 0, append `  |  Injuries: {injuries}`.

4. If the JSON array is empty, do nothing — no teams played today.

## Config

API keys are read from `config.py` in the repo root. Edit that file to update keys.
