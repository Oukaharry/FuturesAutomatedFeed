-- Force super_admin tree to rebuild from hierarchy.json (after add_client / create_user).
-- Safe while app is running; next GET /api/hierarchy recomputes the tree.
--
-- Also click "Reload" on the PythonAnywhere Web tab once: each uWSGI worker
-- keeps a ~30s in-memory (L1) copy of hierarchy even after this DELETE.
-- \c tradeopss

DELETE FROM api_response_cache
WHERE cache_key = 'hierarchy:enriched:full'
   OR cache_key = 'hierarchy:enriched:full::computing';

SELECT cache_key, updated_at, expires_at
FROM api_response_cache
WHERE cache_key LIKE 'hierarchy:enriched%';
