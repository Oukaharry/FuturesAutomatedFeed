# Data Quality Dashboard — Rules and Checks

This document describes every automated rule that feeds the **Data Quality** experience: the quality scan (`run_quality_scan` in `dashboard/app.py`), how issues are **stored and shown**, how **health scores** are computed, and how **related dashboards** (admin tracker, daily summary tracker, Slack text) reuse or extend that logic.

**Source of truth for scan logic:** `dashboard/app.py` — function `run_quality_scan` (approximately lines 7109–7694), plus helpers `_parse_date_str`, `_get_row_dates`, `_estimate_issue_date`, `_max_out_row_is_live_numeric_account`, and constants `ADMIN_PROP_MAX_ACTIVE_ACCOUNTS` / `ADMIN_PROP_MAX_ACTIVE_DEFAULT` near the top of the same file.

**Persistence:** Super admins can run a scan from the UI or it can run on a schedule; results are saved via `save_quality_scan_results` in `dashboard/database.py` and read back with `get_quality_scan_results`.

---

## 1. How a scan runs (high level)

1. The system loads **every client** from the hierarchy (or a **single client** when `?rescan=1` or an internal call passes `target_client`).
2. For each client it loads `get_client_data(client_id)` (evaluations, statistics, account, hedge/prop credential tabs, identity).
3. **Inactive** clients (`identity.active_status == 'inactive'`) are **not** checked: they appear with `skipped: true`, zero issues, health **100**.
4. **Cell notes** are merged into evaluation rows (`ev['_notes']`) from `get_client_notes` so checks can treat notes as explanations or overrides where coded.
5. Each **evaluation row** is iterated in order (`idx` 0-based; the UI labels this as **Row idx+1**). Rows may be **skipped entirely** before most checks (see §2).
6. Client-level checks (MT5 push, hedging mismatch, credential tabs) run **once per client**, not per row.
7. A **health score** is derived from the list of issues (§4).

---

## 2. Row-level gating (what the scan ignores)

These rules apply **before** or **instead of** many per-row checks. Understanding them explains most “false negative” behavior.

### 2.1 Rows skipped for all row checks

| Condition | Effect |
|-----------|--------|
| `ev['_deleted']` is truthy | Row ignored (internal soft-delete). |
| `Status P1` or `Status` / `Status` column text contains `delete` | Row ignored (treated as super-admin cleanup, not a data-quality row). |
| **No row “data”** | If both `Prop Firm` and `Account Size` are empty/whitespace, the row does not increment `total_checks` and **none** of the per-row checks in the main loop run for that row. |
| **Prop firm `Funding Ticks` / `FundingTicks`** (case-insensitive) | Row skipped (“defunct” firm — no SOP flags). |

### 2.2 “Active” vs inactive row (used for several checks)

A row is **active** when:

- `Status P1` (lowercased) does **not** contain: `fail`, `breach`, `closed`, `sl`
- **and** `Status` (phase 2 / funded status, lowercased) does **not** contain: `fail`, `breach`, `closed`, `sl`, `complete`, `completed`

If either side hits those tokens, the row is **inactive** for purposes like **Empty Account #** (only flagged when `is_active`).

**Bypass / nuance:** Typos or non-standard status strings (e.g. “passed” vs “pass”, custom text) may be treated as **still active**, which can **increase** flags (e.g. weekday tracking).

### 2.3 Live funded numeric row (`is_live_funded_numeric_row`)

When `_max_out_row_is_live_numeric_account(ev)` is **True**, almost all **sheet SOP** row checks are **skipped** for that row. The intent: eval-sheet workflow does not apply when the trader is on a **broker numeric** funded/live account.

**Detection logic (summary):**

- Cleans placeholders: empty, `none`, `-`, em dashes, `n/a`, `tbd`, `pending`, etc.
- **Funded account `Account #.1`** (or eval `Account #` when `.1` is empty) must look like a **positive whole number** (digits only, or float that is an integer), including JSON numeric types.

**Still applies on live numeric rows:** client-level checks (no data, MT5 push, hedging mismatch, credentials). Row-level **weekday-of-day** style tracking is explicitly allowed to continue per code comments (in practice many row checks are behind `not is_live_funded_numeric_row`).

**Bypass:** Prefix eval-style IDs on funded cells so the row no longer looks “numeric-only”; the scan will then apply full SOP checks (may create **more** issues, not fewer).

### 2.4 “Double dip” firms (MFF / TopStep)

If `Prop Firm` normalizes to **My Funded Futures** / **MFF** / **TopStep** / **Top Step** / **TopStepX** **and** `Activation Fee` is non-empty, the row is treated as a **double-dip** reset pattern:

- **Status blank** is **not** flagged.
- **Empty Fee** is **not** flagged (eval fee may be intentionally blank after funded reset).

**Bypass:** Leaving `Activation Fee` empty when it should be filled avoids the double-dip exemption and may surface **Status blank** / **Empty Fee** again.

### 2.5 New row strict mode (`new_row_strict_mode`)

A row counts as **new** when `ev['_row_added_at']` is set **and** the row is **active** (`is_active`).

If the row is new, has **no** non-zero hedge result columns yet, and is **not** a live numeric row → **`new_row_strict_mode` is True**.

While in strict mode, the scan **suppresses** most early-life noise (empty account #, missing weekday, activation fee, negative hedge net, comma parsing, etc.) **except**:

- **Empty Fee** / zero fee (still flagged unless fee cell note — see **Empty Fee**).
- **Missing Date Purchased** (explicit extra check for new rows).
- **New row: Status P1 not started** when fee is present and Status P1 is not exactly `not started`, subject to **non-hedge** and **weekday** exceptions (see that check below).

**Bypass:** Enter any non-zero value in a `Hedge Result*` column to exit strict mode early; the full rule set then applies (which may add **more** flags).

---

## 3. Client-level checks (not tied to a single row)

### 3.1 `No data`

| Field | Value |
|-------|--------|
| **Severity** | `critical` |
| **When** | `get_client_data` returned falsy / empty. |
| **Detail** | States there is no saved data in the database. |
| **Estimated date** | Scan date. |

**Bypass:** Only operational — create/sync client data. Marking inactive does not apply (there is no `identity` to read).

### 3.2 `No evaluations`

| Field | Value |
|-------|--------|
| **Severity** | `warning` |
| **When** | Client has data but `evaluations` is empty. |
| **Estimated date** | Scan date. |

**Bypass:** Add at least one evaluation row (may then trigger row-level checks).

### 3.3 `No recent MT5 push`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | `get_client_activity(client_id).last_push_at` parses successfully, **more than 24 hours** elapsed since that timestamp, **and** the server’s **current weekday is Monday–Friday** (0–4). Weekends do not flag. |
| **Estimated date** | Date of the last push. |

**Bypass:** Push MT5 / refresh activity within 24h on a weekday; run scan on weekend; corrupt/unparseable `last_push_at` skips the check silently.

### 3.4 `Hedging Results mismatch`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | “MT5 context” exists **and** absolute difference between chosen MT5 profit and displayed hedging total is **≥ $1.00**. |

**Numbers used (must match Stats UI):**

- **MT5 profit (combined):** current account `total_deposits`, `total_withdrawals`, `balance` from `data.account` (fallback to hedging_review), **plus** all `hedging_review.historical_accounts` deposits/withdrawals/final_balance, minus `current_mt5_prior_activity` and per-historical `prior_activity_profit`.
- **MT5 profit (current-only):** current balance − (deposits + withdrawals) − `current_mt5_prior_activity` (no historical accounts).
- **Sheet hedging display total:** `cashflow_inprogress.hedging_results + farming_results + hedging_review.discrepancy`.

**Choosing combined vs current:** If any historical MT5 bucket is non-zero **and** current-only profit is within **$1** of the sheet total, the scan uses **current-only** profit; otherwise **combined**.

**MT5 context gate:** At least one of: any `last_push`, or non-zero deposits/withdrawals/balance on current or historical MT5.

**Tolerance:** `abs(diff) < 1.0` → no issue.

**Bypass:** Align sheet cashflow fields with MT5-derived profit; stay under $1 difference; remove MT5 deposits/balance/push so `has_mt5_context` is false (not recommended — hides real drift); exceptions in try/except swallow errors → no flag.

### 3.5 `Hedge account or Prop Firm missing` (two issues)

| Field | Value |
|-------|--------|
| **Severity** | `high` each |
| **When** | `total_checks > 0` (see §2.1 — at least one row with Prop Firm or Account Size) **and** no hedge account dict has non-empty `login` or `password` **and** no prop account dict has non-empty `login` or `password`. |
| **Tab** | First issue: `hedge`; second: `prop` (deep links in UI). |

**Bypass:** Fill either tab; if all visible rows lack both Prop Firm and Account Size, `total_checks` stays 0 and this check **does not run** (possible false negative).

### 3.6 `Scan error`

| Field | Value |
|-------|--------|
| **Severity** | `critical` |
| **When** | Uncaught exception while processing a client. |
| **Detail** | Exception string. |

**UI / API behavior:** Trader-facing and some APIs **strip** `Scan error` from issue lists and **recompute** health so infrastructure failures do not punish the displayed score.

---

## 4. Health score

After all issues are collected:

```text
deduction = sum of weights per issue severity
health_score = max(0, 100 - deduction), rounded to 1 decimal
```

| Severity | Weight |
|----------|--------|
| `critical` | 20 |
| `high` | 10 |
| `medium` | 5 |
| `warning` | 3 |
| `low` | 2 |
| `info` | 0 |
| unknown | 2 (default in `sum`) |

**Bypass:** Each extra issue lowers the score; inactive clients get **100** with no scan. Removing issues (fixing data) or getting `Scan error` filtered in UIs changes **displayed** health for those endpoints only, not the raw DB row unless resaved.

---

## 5. Row-level checks (alphabetical by check name)

### 5.1 `Alpha Futures: missing Activation Fee`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | Prop firm normalizes to **Alpha Futures**; `Activation Fee` empty; **not** new-row strict mode; **not** live numeric row; **and** a funded marker exists: Status P1 is `pass`, or `Account #.1` set, or `Date Started.1` / `Date Ended.1` / phase-2 `Status` non-empty; **and** at least one funded-phase hedge column contains a digit `1-9` (regex on string — crude proxy for “had activity”). |

**Bypass:** Enter activation fee; avoid funded markers until ready; ensure funded HR cells are empty/zero text; use live numeric row path; stay in new row strict mode without triggering Alpha block.

### 5.2 `Comma in hedge value`

| Field | Value |
|-------|--------|
| **Severity** | `low` |
| **When** | Any `Hedge Result*` or `Hedge Day*` cell contains a comma, **no** `.` in the numeric probe (so `1,000.50` is OK), and the cell ends with **`,NN`** two digits (European-style decimal). |

**Why:** Those values break US-style currency parsing and can silently drop cents.

**Bypass:** Use dot decimals or include a `.` for thousands; fix only flagged cells; new-row strict mode or live numeric row suppresses.

### 5.3 `Empty Account #`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | Row active; both `Account #` and `Account #.1` blank; not live numeric; not new-row strict; has_data implied earlier. **Suppressed** when Status P1 is exactly `not started` and there are no numeric hedge values yet. **Double-dip:** if `is_double_dip` and `Account #.1` is filled, eval `Account #` can stay empty without flag. |

**Bypass:** Enter either account field; mark row inactive; not started + no hedge numbers; double-dip with funded account # only.

### 5.4 `Empty Account Size`

| Field | Value |
|-------|--------|
| **Severity** | `low` |
| **When** | `Account Size` blank but `Prop Firm` present; not new-row strict; not live numeric; not double-dip. |

**Bypass:** Fill account size; remove prop firm name if row should be ignored (also clears `has_data` if both empty).

### 5.5 `Empty Activation Fee`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | Phase-2 status (`status_p2`) is one of `funded`, `live`, `payout`; activation field blank; not new-row strict; not live numeric. |

**Bypass:** Fill activation fee; use statuses outside that set; new-row strict / live numeric paths.

### 5.6 `Empty Fee`

| Field | Value |
|-------|--------|
| **Severity** | `low` |
| **When** | Fee missing or numeric ≤ 0; has_data; not live numeric; not double-dip; **no** cell note on column key **`Fee`** (case-insensitive match in `_notes`). |

**Bypass:** Enter fee &gt; 0; double-dip with activation fee set; add a **cell note** on the Fee cell (explicit override).

### 5.7 `Hedging Results mismatch`

See **§3.4** (client-level).

### 5.8 `Missing Date Purchased`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | **New row strict mode** and `Date Purchased` is empty. |

**Bypass:** Set date purchased; add hedge value to leave strict mode (then other date rules may apply from other systems, not this check).

### 5.9 `Negative Hedge Net-QA`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | `Hedge Net` parses as a number **&lt; 0**; not new-row strict; not live numeric; **and** `Date Purchased` parses to **≥ 2026-04-29** (cutoff). **Notes do not clear** this check. |

**Resolution:** Super admin / BEF admin can call `POST /api/quality/qa_resolve` with `check: Negative Hedge Net-QA`, `client_id`, `row`, optional `notes`. Resolved pairs are stored in DB (`is_qa_resolved` / `mark_qa_resolved` in `dashboard/database.py`) and skipped on future scans.

**Bypass (legitimate):** Fix Hedge Net to ≥ 0; change Date Purchased before cutoff (ethical/legal implications — audit trail); QA resolve after review; use row gating (inactive, live numeric, new strict).

### 5.10 `Negative Hedge Net, no note`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | Hedge Net &lt; 0; **Date Purchased** missing or **before** 2026-04-29; not new-row strict; not live numeric; **no** any cell note with non-empty text **and** no `Notes` column text. |

**“See note” in hedge cells:** For **Not Started but hedge values present**, “see note” in a hedge cell suppresses that mismatch — it does **not** by itself suppress **Negative Hedge Net, no note** (that check only looks `_notes` dict values and `Notes` column).

**Bypass:** Add any cell note or Notes column text; fix Hedge Net; cutoff date behavior switches issue to **Negative Hedge Net-QA** instead.

### 5.11 `New row: Status P1 not started`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | New row strict mode; fee present (&gt; 0); Status P1 non-empty and **≠** `not started`; fails **non-hedge** exception: not (`hit tp…` + weekday token in `Hedge Result 1`); fails **weekday_ok**: no weekday token in funded hedge columns `Hedge Result 1.1` … `Hedge Result 7` or `Hedge Day 1`…`Hedge Day 50`. |

**Bypass:** Set Status P1 to `not started` until hedging begins; use hit-tp + weekday in HR1; place weekday in funded/farming columns; add hedge numbers to exit strict mode (different rules apply).

### 5.12 `No current day value`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | Not inactive by status tokens; `status_p1` non-empty; **either** not in new-row strict mode **or** account # present on row; scans columns whose names start with `Hedge Result`, `Hedge Day`, `Prop Day`, or `Prop Progress` for a **weekday token** (Mon–Fri, including `tues`, `thurs`, etc.) **or** a **non-empty cell note** on that column (note counts as valid “day” explanation). |

**Bypass:** Put weekday or note in one of those columns; clear Status P1; mark row inactive; new strict without account # suppresses.

### 5.13 `Not Started but hedge values present`

| Field | Value |
|-------|--------|
| **Severity** | `high` |
| **When** | Not live numeric; **and** (`not started` in Status P1 **and** any eval-phase `Hedge Result*` non-zero) **or** (`not started` in Status P2 **and** any **funded** `Hedge Result*.1` / `Hedge Result 6` / `7` non-zero); **and** suppression false. |

**Suppression (`_suppress_not_started_hedge_mismatch`):** Any hedge result cell text contains `see note` (case-insensitive); **or** any `_notes` value non-empty; **or** `Notes` column non-empty.

**Bypass:** Align status with hedge values; clear hedge numbers; add see-note / notes; use live numeric row.

### 5.14 `Status blank`

| Field | Value |
|-------|--------|
| **Severity** | `medium` |
| **When** | Status P1 empty; row has data; not live numeric; not double-dip. |

**Bypass:** Fill Status P1; double-dip pattern; live numeric.

---

## 6. Reserved / pipeline checks (not produced by current `run_quality_scan`)

### 6.1 `Downtime detected`

The **admin tracker** and **daily Slack-style summary** look for this check name and render a **downtime alert** section if present.

In the **current** `dashboard/app.py`, **`run_quality_scan` does not append `Downtime detected`**. So under normal operation this section **never** triggers until a future implementation (or another service) writes that issue into saved scan results.

---

## 7. Admin tracker (separate from raw scan, derived in `compute_admin_tracker_payload`)

Used by super-admin flows; logic mirrors `dashboard/app.py` `compute_admin_tracker_payload` (~8074+).

### 7.1 Fee rollup (`challenge_fees`)

Promotes scan issues whose `check` is one of:

- `Empty Fee`
- `Empty Activation Fee`
- `Alpha Futures: missing Activation Fee`

into admin issues of `type: challenge_fees`.

**Bypass:** Fix underlying scan issue; exclude client/trader from summary tracker lists (same exclusion keys as daily tracker).

### 7.2 Downtime rollup (`downtime`)

Promotes `Downtime detected` if it ever appears in scan results.

### 7.3 Prop firm max-out (`max_out`)

Counts **active** rows (same inactive/delete rules as scan) per **normalized prop firm key** (`_norm_prop_firm_max_out_key`). Compares count to expected slots:

| Normalized key | Expected active rows |
|----------------|----------------------|
| `mffu` | 3 |
| `tradeday` | 3 |
| `alphafutures` | 3 |
| `apex` | 10 |
| *(default)* | 5 |
| `toponefutures` | Uses default (5) unless key matches |

**Under-filled (count &lt; expected):** Flags **unless** there is exactly **one** active row **and** it is a **live numeric** account (`_max_out_row_is_live_numeric_account`) — then skipped (single live account doesn’t need max eval slots).

**Over-filled (count &gt; expected):** Requires **excess** rows to have a **cell note on `Status P1` only**. Notes on other cells **do not** count. If `noted < excess`, emits `max_out` with count of missing notes.

**Special:** Admins **`joy ndua`** and **`marion nyika`** (case-insensitive) skip **all** MFFU max-out / excess logic.

**Bypass:** Adjust active row count per firm; add Status P1 notes only on excess rows; rename prop firm string to change normalization; hierarchy reassignment for MFFU skip admins (organizational, not technical).

### 7.4 Admin summary sign-off (`summary_signoff`)

Not a scan “check” but a **workflow gate** on the same payload:

- Builds `required_clients`: active clients under the admin, not excluded, **for which a trader submitted a daily summary** that UTC date (`get_summary_status_for_date`).
- Loads `get_daily_checklists(date, admin_name)` for checklist type `admin_daily_summary` with item `id == 'sent_to_client'` checked.
- `pending_clients` = required but not signed.

**Bypass:** Trader does not submit → admin not required to sign for that client that day; exclusions; mark client inactive.

---

## 8. Daily Summary Submission Tracker (API + UI)

**Endpoints:** `GET /api/quality/summary_status`, `GET /api/quality/trader_summary_status`, and the text builder in `GET /api/quality/daily_summary`.

**Rules:**

- Default **date** is server UTC `YYYY-MM-DD` (Kenyan EAT shown in some responses).
- Skips clients on `summary_tracker_excluded_clients` and traders on `summary_tracker_excluded_traders` (settings JSON in DB).
- Skips **inactive** clients.
- **Weekend:** the generated text says submission tracking is paused (Saturday/Sunday in **Kenyan** timezone), but API lists may still return data depending on caller.

**Bypass:** Super admin toggles exclusions via `POST /api/quality/summary_tracker_exclude`.

---

## 9. Other quality-related APIs (not new rules, but useful)

| Endpoint | Role |
|----------|------|
| `GET /api/quality/discrepancies` | Recomputes MT5 actual vs sheet hedging+farming (no `discrepancy` field in “sheet” side here — differs slightly from scan’s hedge display which **includes** `hedging_review.discrepancy`). |
| `GET /api/quality/deleted_rows` | Lists rows where `Status P1` strips to a string whose **lowercase** is exactly `deleted`. |
| `GET /api/quality/negative_hedge_net_qa` | Reads saved scan for a date and lists unresolved QA items. |
| `POST /api/quality/qa_resolve` | Marks QA resolved for a client+row. |
| `GET /api/quality/results` | Saved scans with optional date range; `Scan error` filtered for display health in some paths. |

---

## 10. Operational “bypasses” (human / process, not bugs)

1. **Exclude from trackers** — summary tracker lists; inactive flag; super-admin financial exclusions are **separate** (see UI hint on quality dashboard).
2. **Rescan single client** — `GET /api/quality/client/<id>?rescan=1` updates DB row for that client for the scan date (super admin).
3. **Stale saved results** — Dashboard shows last persisted scan until a new scan runs; fixing data without rescanning leaves old issues until overwritten.
4. **Trader API** — `Scan error` issues removed from list for trader-facing health recompute.
5. **Weekend MT5 push** — No “No recent MT5 push” flag regardless of 24h gap.

---

## 11. Estimated issue dates (`estimated_date`)

Many row issues set `estimated_date` via `_estimate_issue_date` using parsed dates from purchase/start/end, `Prop Day` / `Hedge Day` columns, etc. The UI can filter the issues table by date range against this field. **Missing or unparseable dates** fall back to **scan date** or row logic as coded.

---

## 12. Quick reference — all `check` strings emitted by `run_quality_scan`

1. `No data`  
2. `No evaluations`  
3. `No recent MT5 push`  
4. `Hedging Results mismatch`  
5. `Not Started but hedge values present`  
6. `Status blank`  
7. `Empty Fee`  
8. `Missing Date Purchased`  
9. `New row: Status P1 not started`  
10. `Empty Account Size`  
11. `Empty Account #`  
12. `Empty Activation Fee`  
13. `Alpha Futures: missing Activation Fee`  
14. `No current day value`  
15. `Negative Hedge Net-QA`  
16. `Negative Hedge Net, no note`  
17. `Comma in hedge value`  
18. `Hedge account or Prop Firm missing` (×2 entries with different `tab`)  
19. `Scan error` (on exception)

**Referenced elsewhere but not emitted today:** `Downtime detected`

---

*Document generated from codebase review. If behavior drifts from this file, prefer `dashboard/app.py` as authoritative.*
