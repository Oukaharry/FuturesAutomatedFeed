-- Sessions that commonly cause outages on a 20-slot plan.
-- \c tradeopss

-- Idle in transaction: open txn, often holds locks and wastes a slot until killed.
SELECT pid,
       usename,
       application_name,
       now() - state_change AS idle_in_txn_for,
       left(coalesce(query, ''), 120) AS last_query
FROM pg_stat_activity
WHERE datname = 'tradeopss'
  AND state IN ('idle in transaction', 'idle in transaction (aborted)')
  AND pid <> pg_backend_pid();

-- Long-running active queries (adjust threshold as needed).
SELECT pid,
       usename,
       application_name,
       now() - query_start AS running_for,
       left(query, 200) AS query_preview
FROM pg_stat_activity
WHERE datname = 'tradeopss'
  AND state = 'active'
  AND pid <> pg_backend_pid()
  AND query_start < now() - interval '30 seconds'
ORDER BY query_start;

-- Count by application_name (spot uWSGI / script leaks).
SELECT coalesce(nullif(application_name, ''), '(empty)') AS app,
       state,
       count(*) AS n
FROM pg_stat_activity
WHERE datname = 'tradeopss'
GROUP BY 1, 2
ORDER BY n DESC;
