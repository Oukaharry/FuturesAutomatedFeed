-- Clear stuck shared-cache compute locks (after worker reload / hung hierarchy job).
-- Run with web app DISABLED so locks are not recreated immediately.
-- \c tradeopss

DELETE FROM api_response_cache
WHERE cache_key LIKE '%::computing'
   OR cache_key LIKE 'heavy_compute::%'
   OR cache_key LIKE 'cache-warm::%';

SELECT cache_key, updated_at
FROM api_response_cache
WHERE cache_key LIKE '%computing%'
   OR cache_key LIKE 'heavy_compute%'
   OR cache_key LIKE 'cache-warm%';
