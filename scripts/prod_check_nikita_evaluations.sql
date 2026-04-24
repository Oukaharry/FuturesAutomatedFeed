-- scripts/prod_check_nikita_evaluations.sql
--
-- Purpose:
--   Production DB sanity check for client_id='Nikita' evaluations visibility.
--   Works on PostgreSQL (production) where JSON is stored as TEXT.
--
-- How to run (psql):
--   psql "$DATABASE_URL" -f scripts/prod_check_nikita_evaluations.sql
--
-- Notes:
--   - This script is READ-ONLY.
--   - It checks both:
--       1) clients_data.evaluations (the dashboard "sheet rows" JSON array)
--       2) evaluations table (phase tracking table keyed by account_signature)

\echo '--- 1) Find Nikita rows in clients_data (exact + fuzzy) ---'
SELECT
  client_id,
  last_updated,
  CASE
    WHEN evaluations IS NULL OR evaluations = '' THEN NULL
    ELSE jsonb_array_length(evaluations::jsonb)
  END AS evaluations_json_count,
  CASE
    WHEN identity IS NULL OR identity = '' THEN NULL
    ELSE left(identity, 120)
  END AS identity_preview
FROM clients_data
WHERE client_id = 'Nikita'
   OR client_id ILIKE '%nikita%'
ORDER BY (client_id = 'Nikita') DESC, client_id;

\echo '--- 2) Confirm user_credentials row (common mismatch cause) ---'
SELECT
  id,
  username,
  email,
  user_type,
  parent_admin,
  parent_trader,
  is_active,
  last_login
FROM user_credentials
WHERE username = 'Nikita'
   OR username ILIKE '%nikita%'
   OR lower(email) = 'nikitavpf14@gmail.com'
ORDER BY user_type, username;

\echo '--- 3) If clients_data row exists: count eval rows + extract signatures ---'
WITH nikita AS (
  SELECT client_id, evaluations
  FROM clients_data
  WHERE client_id = 'Nikita'
),
eval_rows AS (
  SELECT
    n.client_id,
    jsonb_array_elements(COALESCE(NULLIF(n.evaluations, '')::jsonb, '[]'::jsonb)) AS ev
  FROM nikita n
),
sig AS (
  SELECT
    client_id,
    -- Try several key names (sheet changes over time). Keep whichever exists.
    NULLIF(
      COALESCE(
        ev->>'account_signature',
        ev->>'Account Signature',
        ev->>'AccountSignature',
        ev->>'Account',
        ev->>'Account ID',
        ev->>'AccountID'
      ),
      ''
    ) AS account_signature
  FROM eval_rows
)
SELECT
  client_id,
  COUNT(*) AS eval_rows_in_clients_data,
  COUNT(account_signature) AS eval_rows_with_signature,
  COUNT(DISTINCT account_signature) AS distinct_signatures
FROM sig
GROUP BY client_id;

\echo '--- 4) If signatures exist: how many phase rows are in evaluations table ---'
WITH nikita AS (
  SELECT client_id, evaluations
  FROM clients_data
  WHERE client_id = 'Nikita'
),
eval_rows AS (
  SELECT
    n.client_id,
    jsonb_array_elements(COALESCE(NULLIF(n.evaluations, '')::jsonb, '[]'::jsonb)) AS ev
  FROM nikita n
),
sig AS (
  SELECT DISTINCT
    NULLIF(
      COALESCE(
        ev->>'account_signature',
        ev->>'Account Signature',
        ev->>'AccountSignature',
        ev->>'Account',
        ev->>'Account ID',
        ev->>'AccountID'
      ),
      ''
    ) AS account_signature
  FROM eval_rows
)
SELECT
  e.account_signature,
  COUNT(*) AS phase_rows,
  MIN(e.created_at) AS first_created_at,
  MAX(e.created_at) AS last_created_at
FROM evaluations e
JOIN sig s
  ON s.account_signature IS NOT NULL
 AND e.account_signature = s.account_signature
GROUP BY e.account_signature
ORDER BY phase_rows DESC, e.account_signature;

\echo '--- 5) Quick health check: does Nikita have a clients_data row at all? ---'
SELECT
  'clients_data' AS table_name,
  COUNT(*) AS rows
FROM clients_data
WHERE client_id = 'Nikita'
UNION ALL
SELECT
  'data_history' AS table_name,
  COUNT(*) AS rows
FROM data_history
WHERE client_id = 'Nikita';

