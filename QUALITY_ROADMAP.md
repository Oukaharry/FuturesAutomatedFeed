# VPF Futures — 2-Week Quality Improvement Plan
**Start Date:** March 24, 2026  
**Team:** 8 Admins · 14 Traders · 70 Clients · QA Team  
**Goal:** 100% data accuracy and zero client complaints caused by internal errors

---

## WHY THIS MATTERS — Evidence From the Field

| # | Issue Observed | Impact |
|---|---------------|--------|
| 1 | Hedge Net not calculating after status changes | Clients see stale/empty financial data — trust erosion |
| 2 | 28-hour Discord response time during admin transition | Client publicly questioning our reliability in group Discord |
| 3 | Client cross-referencing with other clients about what's "normal" | Trust deficit — client doesn't believe their own team's info |
| 4 | Evaluation row deleted without explanation (Row 397) | Client says it "smells fishy" — data integrity concern |
| 5 | Dashboard data not updated for an entire day (Monday) | Client catches it before we do — reactive instead of proactive |
| 6 | Traders missing trades / running out of time | Downtime = lost profit days for the client |
| 7 | Wrong values entered in manual fields | Compounding errors, false Hedge Net results, bad EV calculations |
| 8 | Notes stale or missing on active accounts | Clients don't know what's happening with their money |
| 9 | Hedge Day columns showing previous day's marker (e.g., "Wed" on Thursday) | Proof of missed trades — no one catching it systematically |
| 10 | Clients have no way to independently verify calculations | Zero transparency — must blindly trust the team |

---

## THE 4-LAYER QUALITY SYSTEM

Every client's data passes through **minimum 3 independent checks** — nothing can slip through.

```
CLIENT DATA
    ├── LAYER 1: SYSTEM (Automated)        → Catches 70% — runs on ALL 70 clients daily
    ├── LAYER 2: PROCESS (Checklists)      → Catches 20% — human confirms completeness
    ├── LAYER 3: HUMAN QA (Spot-checks)    → Catches 10% — verifies accuracy & quality
    └── LAYER 4: ACCOUNTABILITY (Tracking) → Makes it all stick — scorecards & escalation
```

---

## WEEK 1 — DETECT & SURFACE (March 24–28)

### Day 1–2 (Mon–Tue): Automated Daily Quality Scan

**What:** Build a backend scan that checks every client nightly and flags SOP violations.

| Check | SOP Reference | What It Catches |
|-------|--------------|-----------------|
| Missing Date Started | Trader §6b | First trade placed but no start date |
| Missing Date Ended | Trader §7 | Account marked Fail/Complete but no end date |
| Empty Fee / Account Size | Trader §9 | Manual entry fields left blank |
| Empty Activation Fee on funded accounts | Trader §9 | Funded row missing activation fee |
| Active account with no note | Trader §8 | Any eval not Fail/Complete without a current note |
| Note older than 24 hours on active account | Trader §8 | Stale note — trader hasn't reviewed |
| Negative Hedge Net without explanatory note | Trader §7d | Loss not explained — SOP requires why + prevention |
| Status = Payout but no payout tracking note | Trader §4e | Payout marked but no timestamped follow-up |
| Farming note wrong format | Trader §4d | Missing "X/Y – date" pattern (e.g., "⅗ – 3/15/26") |
| No MT5 push in 24h on weekday | Trader §5 | Missed trades — no data pushed for active hedging client |
| Status blank on non-empty row | Trader §6b | Row has data but no status set |
| Hedge Day column shows stale day marker | Trader workflow | e.g., "Wed" still present on Thursday = missed trade day |
| Account # blank on active row | Trader §4g | Account number not filled in |

**Output:** Per-trader report posted to their Slack QA channel every morning.

**Technical Build:**
- [ ] Backend: `/api/quality/scan` endpoint — scans all clients, returns per-trader issues
- [ ] Backend: `/api/quality/report` endpoint — returns latest scan results for dashboard
- [ ] Cron/scheduled task: Run scan daily at 2:00 AM EAT

---

### Day 3–4 (Wed–Thu): Super Admin Quality Dashboard Tab

**What:** New "Data Quality" tab on the super admin page.

**Features:**
- Health score per client: 🟢 100% | 🟡 80-99% | 🔴 <80%
- Breakdown by trader — each admin sees their 2 traders at a glance
- Drill-down: click any flag to jump directly to that client's eval row
- Filters: "Show all missing dates" / "Show all stale notes" / "Show missed trades"
- Summary cards: Total issues today, issues by category, trend vs. yesterday

**Technical Build:**
- [ ] Frontend: New tab on super admin page with quality metrics
- [ ] Frontend: Per-trader expandable sections showing client health
- [ ] Frontend: Click-to-navigate from any issue to the specific client/row
- [ ] Backend: Aggregate quality data by trader, by admin, by issue type

---

### Day 5 (Fri): Quick Wins — Security + Visibility

**5a. Restrict Delete to Super Admin Only**

Currently any admin/trader can delete evaluation rows. This caused the "Row 397 missing" incident.

- [ ] Backend: Change delete endpoint to require `super_admin` session
- [ ] Frontend: Hide delete button for non-super-admin users
- [ ] Backend: Log all deletions with who deleted, what was deleted, and when

**5b. "Last Activity" Indicators on Client Dashboard**

- [ ] Show "Last MT5 Push: 6h ago" on each client's dashboard header
- [ ] Show "Last Edit: 2d ago by Steve" — identifies abandoned clients
- [ ] Warning badge if >24h since last push on a weekday

**5c. CSV Download Button**

Allow clients (and all users) to download their full evaluation data as CSV for independent verification.

- [ ] Backend: `/api/client/{id}/export_csv` endpoint
- [ ] CSV includes ALL fields: Prop Firm, Account Size, Date Purchased, Fee, Date Started, Date Ended, Status P1, Account #, all Hedge Results (1-5, 1.1-5.1, 6, 7), Hedge Net, Hedge Net.1, Account #.1, Activation Fee, Status, all Payouts + Dates, all Hedge Days 1-50, Farming Profit, Notes
- [ ] Frontend: Download button on client dashboard (visible to all user types)
- [ ] Include calculated stats in a second sheet/section (EV, net profit, etc.)

---

## WEEK 2 — PREVENT & ENFORCE (March 31 – April 4)

### Day 6–7 (Mon–Tue): Save-Time Validation Warnings

**What:** When a trader/admin hits Save, the system highlights all data quality issues.

**Behavior:**
- Warning banner: "⚠️ 3 issues found — Date Started missing on row 2, Fee empty on row 5, No note on row 3"
- Highlight specific cells in red
- **Do NOT block the save** — the data might not be available yet
- Log every dismissed warning with timestamp and user — becomes QA audit trail
- Special warning if Hedge Net is negative and no note exists (Trader §7d)

**Technical Build:**
- [ ] Frontend: Validation function that checks all required fields before save
- [ ] Frontend: Visual highlighting of problem cells
- [ ] Backend: Log dismissed warnings per save for QA audit

---

### Day 8–9 (Wed–Thu): Trader & Admin Daily Checklists

**What:** Built-in checklists in the dashboard that must be submitted daily. Logged with timestamp for QA audit.

**Trader Daily Sign-Off Checklist:**

| # | Checkpoint | Why It Can't Be Automated |
|---|-----------|--------------------------|
| 1 | "I confirmed all accounts are visible on Tradovate AND the dashboard" | Requires visual cross-check across platforms |
| 2 | "I verified MT5 name matches client name on every hedging account" | Identity verification |
| 3 | "I confirmed Tradovate balance matches the sheet (within $100)" | Cross-platform number comparison |
| 4 | "I checked forexfactory.com for red-zone news before trading" | External source review |
| 5 | "I verified trades against the correct blueprint before placing" | Judgment call requiring context |
| 6 | "I confirmed MT5 opposite trade executed after each Tradovate trade" | Real-time hedging verification |
| 7 | "Every active account has an updated note with today's date" | Quality of note content |
| 8 | "I traded ALL accounts — none were skipped" | Completeness confirmation |
| 9 | "All numbers entered are exact to the cent, no rounding" | Accuracy intent |

**Admin Daily Sign-Off Checklist:**

| # | Checkpoint |
|---|-----------|
| 1 | "All challenges needed for tomorrow are purchased" |
| 2 | "All failed account subscriptions are cancelled" |
| 3 | "All master agreements are signed" |
| 4 | "All eligible payouts are requested" |
| 5 | "All client emails checked for notifications" |
| 6 | "All Discord messages replied to" |
| 7 | "Daily summary sent to EVERY client" |
| 8 | "All clients are within challenge limit" |

**System Cross-Check:**
If a trader checks "I traded ALL accounts" but the system detected 2 accounts with no MT5 push → automatic flag for QA.

**Technical Build:**
- [ ] Backend: Checklist submission + storage endpoints
- [ ] Backend: Cross-reference checklist claims vs. automated scan findings
- [ ] Frontend: Checklist UI accessible from dashboard (trader/admin views)
- [ ] Frontend: QA view showing all checklist submissions + discrepancies

---

### Day 10 (Fri): Weekly Scorecard + Auto-Generated Summary Draft

**10a. Weekly Trader Scorecard (posted every Monday to #admins-traders):**

| Metric | How It's Calculated |
|--------|-------------------|
| % of clients with 100% complete data | From automated quality scan |
| Missed trade days this week | Stale Hedge Day markers + no MT5 push |
| Stale notes (>24h on active accounts) | From quality scan |
| QA flags raised this week | Logged from scan + spot-checks |
| Checklists submitted every trading day | From checklist log |
| **Overall Quality Score** | Weighted average of above |

**10b. Auto-Generated Daily Summary Draft:**

Auto-generate 80-90% of the Admin Daily Summary (Admin SOP §4) from dashboard data:

| Summary Section | Data Source | Auto or Manual |
|----------------|------------|----------------|
| 1. Challenge Purchase Status | Count evals by firm vs. expected limits | Semi-auto (admin confirms) |
| 2. Renewal / Cancellation Check | Evals recently marked "Fail" | Auto-generated |
| 3. Trading / Operational Delays | N/A | Manual (admin adds context) |
| 4. Payout Requests | Evals with Status = "Payout" + dates | Auto-generated |
| 5. Payout Confirmation | Evals with payouts recently confirmed | Auto-generated |
| 6. Client Action Items | Derived from above | Semi-auto |

Admin reviews, tweaks, and posts to Discord. Saves 15–20 minutes per client per day.

**10c. CSV Re-Import via Companion App**

Allow bulk data correction by importing a CSV back through the connector app.

- [ ] Companion app: File picker for CSV upload
- [ ] Backend: `/api/client/import_csv` endpoint — parses CSV and merges into evaluations
- [ ] Validation: Check column headers match expected fields, flag any mismatches
- [ ] Merge logic: Match rows by Account # → update existing, add new
- [ ] Available to anyone connected to the client account via the companion app

---

## ONGOING — QA TEAM MANUAL PROCEDURES

These cannot be automated and require consistent human execution:

### Daily QA Routine

**Morning (after automated scan runs at 2AM EAT):**
1. Review the automated quality report in the Data Quality dashboard tab
2. Prioritize red flags — assign to trader's Slack channel
3. Spot-check **3 random clients per trader** (rotate daily — different clients each day):
   - Open client dashboard
   - Verify notes are current AND meaningful (not generic filler)
   - Verify hedge results look reasonable (not copy-paste errors)
   - Cross-check that status progression makes sense
4. Review each trader's daily sign-off checklist — flag discrepancies

**Evening (after market close):**
1. Confirm every trader submitted their daily checklist
2. Confirm every admin submitted their daily checklist
3. Any trader who didn't submit → immediate Slack escalation to their admin
4. Review the "missed trades" list — confirm explanations are valid

### Weekly Deep Audit (Friday/Weekend)

1. Pick **2 clients per trader** for full row-by-row review:
   - Every eval row: dates present, statuses correct, notes current
   - Every hedge result: does the value look reasonable?
   - Every payout: amount exact to the cent, note with confirmation date
2. Admin weekly review:
   - Were all 7 daily summaries sent this week (Mon–Sun)?
   - Were all client action items followed up on?
   - Was any client left waiting >24h without a response?
3. Compare trader quality scores week-over-week — identify trends

### Client Handoff Protocol (When Trader/Admin Changes)

When a client is reassigned to a new trader or admin:
1. Outgoing person creates handoff note in Slack with:
   - Current status of every active account
   - Any pending issues or follow-ups
   - Client communication style preferences
2. New person reviews ALL client notes within 24 hours
3. New person posts introduction in client's Discord channel within 24 hours
4. QA spot-checks the client daily for the first week after transition

---

## ESCALATION CHAIN

```
Issue detected by automated scan or QA
         │
         ▼
Trader's Slack QA channel (callout posted)
         │ (not fixed within 4 hours)
         ▼
Admin notified in #admins-traders
         │ (not fixed within 24 hours)
         ▼
Harry / Philip notified directly
```

For client-facing issues (missed Discord messages, delayed payouts):
```
Client messages in Discord
         │ (no response within 4 hours)
         ▼
QA flags in admin's Slack channel
         │ (still no response within 8 hours)
         ▼
Harry / Philip notified + reassignment considered
```

---

## IMPLEMENTATION CHECKLIST

### Week 1 Deliverables
- [ ] Automated daily quality scan (backend + scheduled job)
- [ ] Quality scan Slack notifications (per-trader channels)
- [ ] Super admin Data Quality dashboard tab
- [ ] Restrict evaluation delete to super_admin only
- [ ] "Last Activity" indicators on client dashboards
- [ ] CSV Download button for clients

### Week 2 Deliverables
- [ ] Save-time validation warnings (frontend)
- [ ] Trader daily checklist (UI + logging)
- [ ] Admin daily checklist (UI + logging)
- [ ] Cross-check: checklist claims vs. automated findings
- [ ] Weekly trader scorecard generator
- [ ] Auto-generated daily summary draft for admins
- [ ] CSV Re-import via companion app

### Process Deliverables (No Code — QA Team)
- [ ] QA daily routine documented and assigned
- [ ] QA weekly deep audit schedule created (rotating client assignments)
- [ ] Client handoff protocol implemented
- [ ] Escalation chain communicated to all admins and traders
- [ ] Weekly team meeting established to review scorecards

---

## SUCCESS METRICS (After 2 Weeks)

| Metric | Current (Estimated) | Target |
|--------|-------------------|--------|
| Clients with 100% complete eval data | ~60% | 95%+ |
| Average missed trade days per trader per week | 2–3 | 0 |
| Notes updated within 24h on all active accounts | ~70% | 100% |
| Daily summaries sent to every client every day | ~80% | 100% |
| Client complaints about data accuracy | Weekly | Zero |
| Average Discord response time | 12–28h | <4h |
| Trader daily checklists submitted | N/A (new) | 100% |

---

*Document Version: 1.0 — March 19, 2026*  
*Next Review: April 7, 2026 (end of 2-week sprint)*
