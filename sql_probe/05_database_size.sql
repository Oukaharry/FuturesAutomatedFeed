-- Storage (disk upgrade ≠ more connections; still useful for health checks).
-- \c tradeopss

-- Total size of the app database.
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;

-- Largest tables (helps find bloat / huge JSON tables).
SELECT relname AS table_name,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;
