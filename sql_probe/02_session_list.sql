-- Live sessions on tradeopss (exclude nothing — full picture).
-- Connect first: \c tradeopss

SELECT pid,
       usename,
       application_name,
       client_addr,
       state,
       now() - state_change AS in_state_for,
       now() - query_start AS query_running_for,
       wait_event_type,
       wait_event,
       left(coalesce(query, ''), 120) AS query_preview
FROM pg_stat_activity
WHERE datname = 'tradeopss'
ORDER BY state, state_change;

-- Same list but skip your own psql session (easier to read during incident).
SELECT pid,
       usename,
       application_name,
       state,
       now() - state_change AS in_state_for,
       left(coalesce(query, ''), 120) AS query_preview
FROM pg_stat_activity
WHERE datname = 'tradeopss'
  AND pid <> pg_backend_pid()
ORDER BY state, state_change;
