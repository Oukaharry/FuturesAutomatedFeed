# Fix plan: Super Admin performance and dashboard scale

Engineering options ranked by fit for the current stack (Flask monolith, PythonAnywhere, Postgres `api_response_cache`, ~81 companions, 3 uWSGI workers). Complements operational mitigations (`DISABLE_BOOT_CACHE_WARM`, `HIERARCHY_CACHE_TTL`, `sql_probe/07`).

---

## 1. Scheduled precompute (best fit now)

**Idea:** Off-peak cron/scheduled task (e.g. every hour at **:10**) builds and persists:

- `super_admin_totals_bundle:v3:ALL`
- `super_admin_splits_bundle:v1:ALL`
- Optionally `hierarchy:enriched:full`

**Write target:** `api_response_cache` (same keys and TTLs as `dashboard/shared_cache.py` today).

**Outcome:** Super Admin always hits **warm or stale** cache; user traffic triggers background refresh only to extend TTL, not a cold 60s scan.

**Implementation sketch:**

- PA scheduled task or in-app scheduler (if already used) calling the same builders as `_build_super_admin_totals_bundle` / `_build_super_admin_splits_bundle` / `_build_hierarchy_enriched_full` inside `app.app_context()`.
- Use `run_heavy_cache_job` or direct `cache_set` after compute to avoid duplicating lock logic.
- Log `[scheduled-cache] computed …` for ops visibility.

**Does not replace:** splitting companion vs dashboard workers (see §4).

---

## 2. Materialized reporting layer

**Idea:** Stop re-aggregating all client JSON on every Super Admin load.

**Options:**

| Approach | Pros | Cons |
|----------|------|------|
| **Table** `client_performance_snapshot` (one row per client, columns for card metrics) | Simple reads; index by profile | Migrations; keep in sync on push |
| **Materialized view** refreshed on schedule | Postgres-native | Refresh still heavy; PA refresh timing |
| **Incremental update on push** | Fresh metrics without full scan | More application logic in `save_client_data` / push path |

Super Admin endpoints read **one query** (or cached bundle built from snapshot), not `get_client_performance_stats` over every `clients_data` row per request.

**When:** After or in parallel with §1 if totals/splits compute remains >30s even off-peak.

---

## 3. Never cold-miss in UI

**Policy:** Always serve **last good cache** (including expired / stale). **Never HTTP 503** when any stale row exists in `api_response_cache` or L1.

**Backend:**

- Extend `_super_admin_cache_response` / `get_or_compute` so cold miss returns **stale JSON + `refreshing: true`** (200), not 503, when `cache_get_stale(key)` is not None.
- Only 503 (or short “initializing”) when **never computed** and background job just started.

**Frontend (`super_admin.html`):**

- Treat 200 + `refreshing` as **“Refreshing…”** on cards, not hard **Error**.
- Retry totals/splits with backoff (already partial via sequential loads).

**Aligns with:** existing stale-while-revalidate design in `shared_cache.py`; closes gap where totals/splits still 503 on true miss.

---

## 4. Split read service (larger step)

**Idea:** Separate **ingestion** from **dashboard/reporting** so companion minute stampedes do not block Super Admin or trader `/api/data`.

```text
Companions → Ingestion API (own workers / subdomain / second PA web app)
Browsers   → Dashboard API (fewer workers, read-heavy, cache-first)
             └── optional Reporting worker for §1 cron only
```

**Requires:**

- Shared Postgres (with connection budget: pool × workers ≤ ~20 on PA).
- Same session/auth or shared cookies across subdomains if split on one domain.
- Deploy and routing changes (not a single-file fix).

**When:** If §1 + §3 still show 502/7s `GET /api/data` at :49/:50 after worker tuning.

---

## Suggested order of work

| Phase | Deliverable | Addresses |
|-------|-------------|-----------|
| **A** | §3 stale-first + UI “Refreshing…” | Super Admin 503 / Error cards |
| **B** | §1 hourly :10 scheduled precompute | Cold 45–60s totals/splits |
| **C** | §2 snapshot table + read path | Long-term DB/CPU on aggregates |
| **D** | §4 split ingestion vs dashboard | Worker saturation / 502 |

---

## Related code paths

- Cache keys: `super_admin_totals_bundle:v3:*`, `super_admin_splits_bundle:v1:*`, `hierarchy:enriched:full` — `dashboard/app.py`, `dashboard/shared_cache.py`
- Builders: `_build_super_admin_totals_bundle`, `_build_super_admin_splits_bundle`, `_build_hierarchy_enriched_full`
- Super Admin fetch: `dashboard/templates/super_admin.html` (sequential `/api/hierarchy`, totals, splits)
- Heavy stats: `get_client_performance_stats` — `dashboard/financial_overview.py`

---

## Out of scope for this doc

- Postgres slot emergencies → `sql_probe/01`, `99`, `07`
- Hierarchy boot warm → `DISABLE_BOOT_CACHE_WARM`, `HIERARCHY_CACHE_TTL` (already shipped)
- `update_data` 500 → save-path logging, version conflicts, write decoupling (separate hardening track)
