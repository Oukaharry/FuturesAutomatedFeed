-- Lock waits: useful when dashboards hang but connections look idle.
-- If many rows show ALTER TABLE clients_data ADD COLUMN prop_accounts, terminate
-- duplicate ALTER pids (keep one), then deploy init_database fix / reload workers.
-- \c tradeopss

-- Sessions waiting on a lock.
SELECT pid,
       usename,
       wait_event_type,
       wait_event,
       state,
       left(coalesce(query, ''), 100) AS query_preview
FROM pg_stat_activity
WHERE datname = 'tradeopss'
  AND wait_event_type = 'Lock'
  AND pid <> pg_backend_pid();

-- Who blocks whom (blocked pid → blocking pid).
SELECT blocked.pid          AS blocked_pid,
       blocked.usename      AS blocked_user,
       left(blocked.query, 80) AS blocked_query,
       blocking.pid         AS blocking_pid,
       blocking.usename     AS blocking_user,
       left(blocking.query, 80) AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking
  ON blocking.pid = ANY (pg_blocking_pids(blocked.pid))
WHERE blocked.datname = 'tradeopss'
  AND blocked.pid <> pg_backend_pid();
