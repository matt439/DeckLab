"""Deck Lab's PostgreSQL database (decklab/PLAN.md, "Moving storage to a database").

Phase 1 is the foundation only: the connection settings and roles (conn.py), the schema
migrations (migrate.py and migrations/), the one-time set-up (setup.py), the profiles synced
from config.json (profiles_sync.py), a read-only query command (sql.py), and the nightly
backups to the NAS and the export repo (backup.py, export.py, nightly.py, schedule.py).

The running Deck Lab server doesn't use any of it yet: no module outside this package imports
psycopg or decklab.db, and nothing on the page changes. psycopg isn't in the standard library,
so everything here runs from the repo's .venv (.venv\\Scripts\\python -m decklab.db ...).
"""
