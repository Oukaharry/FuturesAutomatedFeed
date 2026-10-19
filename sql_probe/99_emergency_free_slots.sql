-- EMERGENCY ONLY: terminate backends on tradeopss to free connection slots.
-- Use when app logs "remaining connection slots are reserved...".
-- Always connect to the app DB first: \c tradeopss
--
-- After kills: reload www.tradeopss.com and keep web workers at 3.

-- Step A — safest: idle and stuck transactions only.
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'tradeopss'
  AND pid <> pg_backend_pid()
  AND state IN (
    'idle',
    'idle in transaction',
    'idle in transaction (aborted)'
  );

-- Step B — if companions still cannot connect: all other sessions on tradeopss.
-- SELECT pg_terminate_backend(pid)
-- FROM pg_stat_activity
-- WHERE datname = 'tradeopss'
--   AND pid <> pg_backend_pid();

-- Verify slot pressure eased.
SELECT state, count(*) AS n
FROM pg_stat_activity
WHERE datname = 'tradeopss'
GROUP BY state
ORDER BY n DESC;
