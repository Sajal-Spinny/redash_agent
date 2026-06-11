# Redash Data Fetcher Agent (Claude Code)

Ask for data in plain English; the agent adapts proven Redash queries
and runs them read-only against Doris (iceberg catalog).

## Setup

1. Clone this repo
2. `pip install -r requirements.txt`
3. Set YOUR OWN Doris credentials (PowerShell, then reopen terminal):

   setx DORIS_HOST "sp-query-engine.mngt.ispinnyworks.in"
   setx DORIS_PORT "9030"
   setx DORIS_USER "your.username"
   setx DORIS_PASSWORD "your_password"

4. Test: `python scripts\run_query.py "SHOW DATABASES"`
5. Run `claude` from the repo root and ask for data, e.g.
   "city-wise refurb movement counts for last 7 days, save as CSV"

## Adding your queries

Export your Redash queries (see scripts/export instructions or ask Sajal)
and append them to `knowledge/redash_queries.md`. The agent only uses
queries from this file — it never invents table names.

## Rules
- Read-only (SELECT/SHOW/DESCRIBE only — enforced in run_query.py)
- Never commit credentials. Env vars only.