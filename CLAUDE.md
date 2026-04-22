# Premier League Results — Daily Update

## Task

Each session: fetch yesterday's match data, write a proper team news article for each team that played, and post it to Slack channel **fb-team-event-updates** (ID: `C0AVBC6256C`).

## Steps

### 1. Install and run the data script

```bash
python check_results.py
```

The script prints a JSON array to stdout (one object per team that played yesterday). Progress logs go to stderr. If the array is empty, no teams played — do nothing.

### 2. For each team in the JSON results, write a team news article

Search the web for the team's **current league position and points** (e.g. search "[Team Name] Premier League table position 2025-26").

Then write a **4–5 paragraph team news article** in a journalistic, editorial style — like a proper football website update, not a social media caption. Use this structure:

**Paragraph 1 — The result**: Open with the result, score, venue (home/away), and competition. Mention the significance if relevant (e.g. must-win, title race, relegation battle).

**Paragraph 2 — The performance**: Describe how the team played using the stats provided (shots, possession, corners). Write it narratively — don't just list numbers.

**Paragraph 3 — League context**: Where does this result leave them in the table? What does it mean for their season — title challenge, European push, survival fight? Use the league position you searched for.

**Paragraph 4 — What's next**: Preview the next fixture. When is it, who are they playing, what are the stakes?

**Paragraph 5 — Squad concerns** (only if injuries exist): Mention any notable injury absences or fitness worries going into the next game.

Tone: authoritative, engaged, written for supporters. No bullet points. No markdown. Plain paragraphs only.

### 3. Post each article to Slack channel `C0AVBC6256C`

Use the Slack connector to post one message per team. Format:

- **Header**: `[Team] | [RESULT] [score] vs [Opponent]`
- **Body**: the full article text
- **Footer**: `[Competition] | Next: [next opponent] ([next competition]) — [formatted date]`

Post them one at a time. Wait for each post to succeed before moving to the next.

## Data provided by the script

Each JSON object contains:
- `team` — team name
- `result` — WIN / LOSS / DRAW
- `score` — e.g. `2-1`
- `opponent` — opponent name
- `venue` — Home or Away
- `competition` — competition name
- `match_date` — date of the match
- `stats` — `shots`, `on_target`, `possession` (%), `corners`
- `next_match` — `opponent`, `date`, `venue`, `competition`
- `injuries` — list of `name`, `position`, `status`, `type`

## Config

The OpticOdds API key is in `config.py`. Edit that file to update it.
