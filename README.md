# pull-fitbit-data

Pull your own Fitbit data with code, through the **Google Health API**
(`health.googleapis.com/v4`), and save it as JSONL and CSV.

The legacy Fitbit Web API (`api.fitbit.com`) stops working on **October 30,
2026**, so this tool uses its replacement. The data types, filter syntax and
scopes come from the API's official discovery document.

## Setup (one time)

1. **Google Cloud project.** This repo uses the GCP project `persona-adkaspar`.
   Enable the **Google Health API** on it, either in the
   [console](https://console.cloud.google.com/apis/library/health.googleapis.com?project=persona-adkaspar)
   or with:
   ```bash
   gcloud services enable health.googleapis.com --project persona-adkaspar
   ```
2. **OAuth consent screen.** Set it to *External*, leave it in *Testing*, and
   add your own Google account (the one your Fitbit is linked to) as a test user.
3. **OAuth client.** Go to *Credentials → Create credentials → OAuth client ID →
   Desktop app*. Download the JSON and save it as `client_secret.json` in this
   directory. It is gitignored.
4. **Install:**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```
5. **Log in.** A browser opens for consent, and the token is saved to `token.json`:
   ```bash
   fitbit-pull login
   fitbit-pull devices   # quick check: should list your Fitbit
   ```

   No browser on this machine (e.g. a server)? Use `fitbit-pull login --manual`,
   open the printed link anywhere, then pass the `localhost` URL your browser
   lands on to `fitbit-pull login --redirect-url '<url>'`.

> While the consent screen is in *Testing*, Google expires refresh tokens after
> 7 days. If a pull fails with an auth error, run `fitbit-pull login` again.

## Usage

```bash
# First run: backfill from a start date. This can take a while for heart-rate.
fitbit-pull -v pull --start 2020-01-01

# Later runs: resume from where each type left off.
fitbit-pull pull

# Only some types
fitbit-pull pull --types sleep,heart-rate,daily-heart-rate-variability --start 2025-01-01

# Flatten everything to CSV (data/csv/<type>.csv)
fitbit-pull export-csv

fitbit-pull types     # list every supported data type

# One summary row per day (sleep, steps, distance, zone minutes, resting HR)
fitbit-pull pull --reconciled --types steps,distance,active-zone-minutes,daily-resting-heart-rate,sleep --start 2023-01-01
fitbit-pull daily     # writes data/daily.csv
```

`--reconciled` asks Google to merge overlapping sources the way the Fitbit app
does. Without it, steps from your phone (via Health Connect) are added on top of
your watch's, double counting. `daily` files each night's main sleep under the
date you woke up.

Output:

```
data/
  raw/<type>/<YYYY-MM>.jsonl   raw API data points, one per line (lossless)
  csv/<type>.csv               flattened view (nested lists stored as JSON strings)
  state.json                   where each type's last pull ended
```

Data is fetched in calendar-month chunks, and each month's file is rewritten
whole. Re-running is safe, and a resumed run re-fetches the last (partial)
month. HTTP 429 and 5xx responses are retried with backoff.

### Data types

Running `pull` without `--types` fetches activity (steps, distance, floors,
active/zone minutes, calories, exercise, and more), heart (intraday heart
rate, HRV, resting HR, HR zones, VO2 max), body (weight, body fat, SpO2,
temperature, and more), respiratory, sleep, and nutrition/hydration logs.

`electrocardiogram` and `irregular-rhythm-notification` need extra sensitive
scopes, so they are opt-in. To get them, log in and pull with `--types`
including them.

Two rollup-only types, `total-calories` and `calories-in-heart-rate-zone`,
aren't supported yet. They use the `dailyRollUp` endpoint instead of `list`.

## Readiness (for planning)

`readiness` compares a day's sleep, HRV and resting heart rate against your own
30-day baseline and prints JSON with an energy `level` (`low`, `normal`, `high`
or `unknown`) and the reasons. A planning agent can use it to lighten the day
after a bad night.

```bash
fitbit-pull readiness --pull          # refresh sleep/HRV/resting HR, then score today
fitbit-pull readiness --date 2026-10-01
```

It is a simple heuristic, not a medical measure. Under 5h of sleep, or two of
"short sleep", "HRV 15%+ below baseline" and "resting HR 5+ bpm above baseline",
counts as `low`.

## Scheduled cloud sync

A Claude scheduled task ("Fitbit daily sync", daily 07:29 America/Argentina/Cordoba)
runs this branch in the cloud: it writes `token.json` from the environment
variable `FITBIT_TOKEN_JSON`, runs `pull --reconciled` and `daily`, upserts the
last 3 days into the Notion Health Log, and reports `readiness`. Setup,
re-login and monitoring are documented in the
[daily-planner-agent](https://github.com/adkaspar/daily-planner-agent/blob/main/docs/automation.md)
repo.

The OAuth consent screen is in production, so refresh tokens no longer expire
after 7 days.

## Development

```bash
pip install -e '.[test]'
pytest
```
