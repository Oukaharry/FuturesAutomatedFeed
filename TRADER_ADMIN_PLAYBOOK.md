# Most recurring issues — how to clear them fast

Ranked by how often they showed up last week (Jul 10–13).  
Teach this order: **fix the ones that keep coming back first.**

---

## 1. Negative Hedge Net, no note — **80×**

**What it means:** Hedge Net is negative and the sheet has no explanation.

**Fix (pick one):**
1. Fix the Hedge Net number (make it ≥ 0 if the number was wrong), **or**
2. Add a **cell note** on *any* cell on that row, **or** type in the **Notes** column.

**If it keeps coming back:**
- You’re typing in a hedge cell as normal text — that is **not** a note. Open the **cell note** (comment), don’t just overwrite the number with words.
- Or you only fixed yesterday’s row and a **different row** is still negative.
- After ~Apr 29 purchase dates, this flips to **Negative Hedge Net-QA** — notes stop working (see #6).

**Who:** Trader

---

## 2. Phase 1: missing Date Ended — **51×**

**What it means:** Status P1 is `pass` or `fail`, but **Date Ended** (phase 1) is empty.

**Fix:** Fill **Date Ended** on that row (eval / phase 1 date column — not the funded `.1` date).

**If it keeps coming back:**
- You’re filling **Date Ended.1** (funded) instead of phase 1 **Date Ended**.
- Or Status P1 still says pass/fail while you meant `not started` / still running — then change status, don’t only add dates.

**Who:** Trader

---

## 3. Daily summary: payouts eligible ≥1-QA — **50×**

**What it means:** In today’s daily summary, payouts-eligible count is ≥ 1. Needs a human QA check (not a sheet typo fix).

**Fix:**
- Trader: in Daily Summaries, make sure section 4 (payouts) is **true** — don’t mark eligible if they aren’t.
- Admin: spot-check; don’t “resolve” this yourself.
- Super admin: clear it in the QA queue after review.

**If it keeps coming back:**
- Someone is marking “eligible” on the summary every day even when nothing is due.
- Or the real payout is fine and QA was never cleared — escalate, don’t keep editing the sheet.

**Who:** Trader (accuracy) → Super admin (resolve)

---

## 4. Downtime detected — **22×**

**What it means:** A hedge/day cell still has a **weekday that isn’t allowed for today** (Kenya time). Usually yesterday’s `mon`/`tue` left sitting there.

**Fix:** In **Hedge Result / Hedge Day / Prop Day**:
- Put **today’s** weekday (mon–fri), **or**
- Clear the old weekday, **or**
- Put a **cell note on that same day/result column** explaining downtime.

**If it keeps coming back:**
- You updated Status or Notes column — **wrong place**. The marker lives in the **day/result cells**.
- You fixed one client and the same stale weekday is on **another row**.
- It reappears right after you Send to Slack — that’s normal; fix the leftover weekday then Refresh Issues.

**Who:** Trader (Admin sees it on their tracker too)

---

## 5. No current day value — **21×**

**What it means:** Row is active, but none of the day/result columns show today’s weekday **and** there’s no note on those columns.

**Fix:** On **Hedge Result / Hedge Day / Prop Day / Prop Progress**, put today’s weekday **or** a cell note on that column.

**If it keeps coming back:**
- Note is on Status / Fee / random cell — **doesn’t count**. Note must be on a **day/result** column.
- Status P1 is filled so the check runs — if the account isn’t trading, mark status inactive properly (fail/breach/closed/sl) instead of leaving it “active looking.”

**Who:** Trader

---

## 6. Negative Hedge Net-QA — **20×**

**What it means:** Hedge Net &lt; 0 on a newer purchase (from ~Apr 29). **This is QA-locked.**

**Fix:**
1. Correct Hedge Net if it’s wrong, **or**
2. Ask **super admin / BEF** to QA-resolve after they review.

**If it keeps coming back:**
- You’re adding notes — **notes do nothing here** (unlike #1).
- You’re treating it like “Negative Hedge Net, no note.” Different rule.

**Who:** Trader + Super/BEF

---

## 7. Missing Date Purchased — **18×**

**What it means:** New row still in “strict” mode with no **Date Purchased**.

**Fix:** Fill **Date Purchased**.

**If it keeps coming back:**
- You’re filling Date Started instead of Date Purchased.
- Or you added hedge numbers so it’s no longer “new” — then other date flags may appear; still fill Date Purchased when you create the row.

**Who:** Trader

---

## 8. Funded phase: missing Date Started — **16×**

**What it means:** Funded **Status** starts with `pass` or `fail`, but **Date Started.1** is empty.

**Fix:** Fill **Date Started.1** (funded start — the `.1` column).

**If it keeps coming back:**
- You’re filling phase 1 **Date Started** (no `.1`) — wrong column.
- Funded Status still says pass/fail when the account never really started funded — fix Status, not only dates.

**Who:** Trader

---

## 9. New row: Status P1 not started — **15×**

**What it means:** Brand-new row with a fee, but Status P1 is something other than exactly `not started` (and no weekday hedge yet).

**Fix:** Set Status P1 to **`not started`** until they actually hedge.

**If it keeps coming back:**
- You’re typing `Not Started`, `pending`, `new` — it must match **`not started`** (that exact idea the sheet expects).
- Or you already put hedge numbers — then exit “new row” properly and use real status (pass / in progress / etc.).

**Who:** Trader

---

## 10. No evaluations — **14×**

**What it means:** Client exists but the evaluations table is empty.

**Fix:** Add at least one evaluation row (prop firm + size, etc.).

**If it keeps coming back:**
- Client was wiped / never saved. Open sheet, add row, **Save**.
- Inactive clients shouldn’t be worked — mark inactive in profile if they’re done.

**Who:** Trader

---

## 11. Funded phase: missing Date Ended — **13×**

**Same family as #8.** Funded Status is pass/fail but **Date Ended.1** empty.

**Fix:** Fill **Date Ended.1**.

**If it keeps coming back:** Filling phase 1 Date Ended instead of **Date Ended.1**.

**Who:** Trader

---

## 12. Phase 1: missing Date Started — **11×**

**What it means:** Status P1 needs a start date and **Date Started** (phase 1) is empty.

**Fix:** Fill phase 1 **Date Started** (not `.1`).

**If it keeps coming back:** Filling **Date Started.1** by mistake.

**Who:** Trader

---

## 13. Empty Fee — **9×**

**What it means:** Fee is blank/0 and there’s no override on the Fee cell.

**Fix (pick one):**
1. Enter the real Fee (&gt; 0), **or**
2. Add a **cell note on the Fee cell** (not Status, not Notes column only), **or**
3. MFF/TopStep double-dip: fill **Activation Fee** so empty challenge fee is allowed.

**If it keeps coming back:**
- Note is on Status P1 or Notes column — **wrong**. For Empty Fee it must be a **note on the Fee cell**.
- You’re zeroing Fee every day “temporarily.”

**Who:** Trader (Admin sees under challenge fees)

---

## 14. Status blank — **4×**

**Fix:** Fill **Status P1**.

**If it keeps coming back:** Saving without Status on new rows; or clearing Status when editing fees.

**Who:** Trader

---

## 15. No data — **3×**

**Fix:** Client has no saved sheet — create/sync data before anything else.

**Who:** Trader / escalate if client won’t load

---

## 16. Alpha Futures: missing Activation Fee — **2×**

**Fix:** Fill **Activation Fee** once they’ve funded and have funded hedge activity.

**If it keeps coming back:** Filling regular Fee but leaving Activation Fee empty.

**Who:** Trader (Admin: challenge fees)

---

## Also teach: Not Started but hedge values present

**Fix:** Change status to match hedges, **or** type **`see note`** in a Hedge Result cell, **or** any cell note / Notes column.

**If it keeps coming back:** Writing explanation only in Status — need `see note` in hedge cell or a real cell note.

---

# Admin-only patterns (teach these too)

### Challenge fees (Empty Fee / Empty Activation / Alpha)
Same fixes as above. Admin opens client from **Admin-owned Issues** and nudges or fills.

### Max-out (too many / too few active accounts per firm)
**Over limit:** put a **cell note on Status P1 only** on each extra row.  
**If it keeps coming back:** note is on Fee, Hedge, or Notes column — **doesn’t count**. Status P1 only.

### Summary sign-off
After trader Sends to Slack → Admin tab **Daily Summaries — Sign-off** → check sent to client.  
**Can’t untick.** If badge stuck: trader never sent Slack for that client.

---

# 60-second trader loop

1. Trader home → **Issues** → Refresh  
2. Open top clients → Issues → **Go To**  
3. Fix using the cards above (watch **which column** and **note vs typed text**)  
4. Daily Summaries FAB → Submit → **Send to Slack**  
5. Issues again until clear  

# 60-second admin loop

1. Admin home → **Admin-owned Issues** (fees / downtime / max-out)  
2. Open client → fix or ping trader  
3. **Sign-off** tab after traders send summaries  

---

*Refresh counts: `python scripts/_issue_priority_report.py`*
