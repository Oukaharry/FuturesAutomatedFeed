-- Connection budget: how full is Postgres?
-- Run from any database; first query is global, second focuses on tradeopss.

-- Hard limit on this server (PythonAnywhere managed Postgres is often 20).
SHOW max_connections;

-- Backends per database (find which DB is saturated — app uses tradeopss).
SELECT datname,
       count(*) AS backends
FROM pg_stat_activity
WHERE datname IS NOT NULL
GROUP BY datname
ORDER BY backends DESC;

-- State breakdown for the app database (switch with \c tradeopss if needed).
SELECT state,
       count(*) AS n
FROM pg_stat_activity
WHERE datname = 'tradeopss'
GROUP BY state
ORDER BY n DESC;

-- Quick headline: app DB total vs max (run after SHOW max_connections above).
SELECT count(*) AS tradeopss_backends
FROM pg_stat_activity
WHERE datname = 'tradeopss';
