sql_probe — Postgres console diagnostics (PythonAnywhere / tradeopss)
=====================================================================

Open: PythonAnywhere → Databases → Postgres → psql console.

Always use the app database for app session queries:
  \c tradeopss

Run files in order during an incident:
  01_connection_budget.sql   — max_connections vs usage
  02_session_list.sql        — who is connected
  03_problem_sessions.sql    — idle-in-transaction, long queries
  04_locks_blocking.sql      — if UI hangs with few "active" queries
  05_database_size.sql       — disk / table size (not connection limits)
  07_clear_cache_compute_locks.sql — stuck hierarchy/cache-warm ::computing rows (disable web first)

Emergency (kills connections — use only when app is down):
  99_emergency_free_slots.sql

Copy/paste one file at a time, or open the .sql file locally and paste sections.
Comments in each file explain what each query is for.

Equivalent bash helper (when a slot is free):
  python3 scripts/pa_free_pg_slots.py
