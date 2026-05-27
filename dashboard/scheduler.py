import threading
import time
import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError
import logging
from dashboard.database import get_all_clients
from dashboard.watermark_service import save_daily_profit

stop_event = threading.Event()

# File-based tracking of which jobs already ran today.
# In-memory dicts get wiped when Flask reloader restarts the module, causing
# duplicate runs.  A tiny JSON file survives reloads within the same day.
_SCHEDULER_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scheduler_state.json')

def _load_ran_today():
    """Load the ran-today state from disk (survives module reloads)."""
    try:
        with open(_SCHEDULER_STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

def _mark_ran(job_name, date_str):
    """Mark a job as completed for a given date and persist to disk."""
    state = _load_ran_today()
    state[job_name] = date_str
    try:
        with open(_SCHEDULER_STATE_FILE, 'w') as f:
            json.dump(state, f)
    except OSError as e:
        logging.warning(f"Could not persist scheduler state: {e}")

# Prevent duplicate scheduler threads across Flask reloader / multiple imports
_scheduler_lock = threading.Lock()
_scheduler_started = False


def run_scheduler():
    logging.info("Starting Daily Scheduler (watermark + quality scan + Slack)...")
    while not stop_event.is_set():
        try:
            now = datetime.utcnow()
            today = now.strftime('%Y-%m-%d')
            ran = _load_ran_today()

            # All times in UTC (datetime.utcnow)
            # PythonAnywhere runs UTC natively.
            # Local dev machines may be in any timezone — utcnow() ensures consistency.

            # 21:00 UTC (00:00 EAT) — Midnight watermark snapshot
            if now.hour == 21 and now.minute == 0 and ran.get('watermark') != today:
                logging.info("Running midnight watermark update (00:00 EAT)...")
                update_all_clients_watermarks()
                _mark_ran('watermark', today)
                time.sleep(60)

            # 23:27 UTC (02:27 EAT) — Automated quality scan  [TEMP TEST]
            if now.hour == 23 and now.minute == 27 and ran.get('quality_scan') != today:
                logging.info("Running scheduled quality scan (TEST 02:27 EAT)...")
                run_scheduled_quality_scan()
                _mark_ran('quality_scan', today)
                time.sleep(60)

            # 23:30 UTC (02:30 EAT) — Post daily summary to Slack  [TEMP TEST]
            if now.hour == 23 and now.minute == 30 and ran.get('slack_summary') != today:
                logging.info("Posting daily quality summary to Slack (TEST 02:30 EAT)...")
                post_slack_summary()
                _mark_ran('slack_summary', today)
                time.sleep(60)

            # 23:15 UTC (02:15 EAT) — Daily database cleanup
            if now.hour == 23 and now.minute == 15 and ran.get('db_cleanup') != today:
                logging.info("Running daily database cleanup (02:15 EAT)...")
                run_database_cleanup()
                _mark_ran('db_cleanup', today)
                time.sleep(60)

            time.sleep(30)  # Check every 30s

        except Exception as e:
            logging.error(f"Scheduler error: {e}")
            time.sleep(60)


# ── Quality Scan ─────────────────────────────────────────────────────
def run_scheduled_quality_scan():
    """Run the quality scan and save results — same as the API but without Flask context."""
    try:
        from dashboard.app import run_quality_scan
        from dashboard.database import save_quality_scan_results, log_action

        results = run_quality_scan()
        scan_date = datetime.now().strftime('%Y-%m-%d')
        save_quality_scan_results(scan_date, results)

        total_issues = sum(r['total_issues'] for r in results)
        log_action('QUALITY_SCAN', 'system', 'scheduler',
                   '127.0.0.1', f"Scheduled scan: {len(results)} clients, {total_issues} issues")
        logging.info(f"Quality scan complete: {len(results)} clients, {total_issues} issues")
    except Exception as e:
        logging.error(f"Scheduled quality scan failed: {e}")


# ── Slack Integration ────────────────────────────────────────────────
def _get_slack_webhook_url():
    """Read Slack webhook URL from database, then environment, then .env file."""
    # 1. Check database (set via super admin UI)
    try:
        from dashboard.database import get_setting
        db_url = get_setting('slack_webhook_url')
        if db_url:
            return db_url
    except Exception:
        pass
    # 2. Check environment variable
    url = os.environ.get('SLACK_WEBHOOK_URL', '').strip()
    if url:
        return url
    # 3. Fallback: read from .env file in project root
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.isfile(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('SLACK_WEBHOOK_URL=') and not line.startswith('#'):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def send_slack_message(text):
    """Post a message to the configured Slack webhook."""
    webhook_url = _get_slack_webhook_url()
    if not webhook_url:
        logging.warning("Slack webhook URL not configured — skipping Slack post.")
        return False
    return send_slack_to_webhook(webhook_url, text)


def send_slack_to_webhook(webhook_url, text):
    """Post a message to a specific Slack webhook URL."""
    try:
        payload = json.dumps({'text': text}).encode('utf-8')
        req = Request(webhook_url, data=payload, headers={'Content-Type': 'application/json'})
        resp = urlopen(req, timeout=15)
        if resp.status == 200:
            logging.info("Slack message posted successfully.")
            return True
        else:
            logging.warning(f"Slack returned status {resp.status}")
            return False
    except URLError as e:
        logging.error(f"Slack post failed: {e}")
        return False
    except Exception as e:
        logging.error(f"Slack post error: {e}")
        return False


def _build_daily_summary_text():
    """Build the daily quality summary text (same logic as the API endpoint)."""
    from dashboard.database import (
        get_quality_scan_results,
        get_daily_checklists,
        record_quality_slack_post,
        upsert_quality_issue_baseline,
        get_trader_issue_resolution_minutes,
    )
    from dashboard.app import (
        _trader_ranking_health_metrics,
        _should_skip_daily_summary_tracking,
        DAILY_SUMMARY_TRACKER_SKIP_MSG,
    )
    from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
    from config.hierarchy import SYSTEM_HIERARCHY

    # UTC date — server runs UTC so at 23:05 UTC (2:05 AM Kenyan) the date
    # is still the day we want.  It flips at midnight UTC = 3 AM Kenyan.
    now = datetime.now()
    date = now.strftime('%Y-%m-%d')
    weekday = now.strftime('%A')

    scan_results = get_quality_scan_results(date)
    checklists = get_daily_checklists(date)
    # Apply the Daily Summary Tracker exclusions to the Slack report as well.
    # This keeps the bot report consistent with the tracker UI exclusions.
    try:
        from dashboard.database import get_setting
        excluded_traders = set(json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients = set(json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))
    except Exception:
        excluded_traders = set()
        excluded_clients = set()

    # Filter portfolio client list using the same exclusions
    all_clients = hierarchy_get_all_clients()
    filtered_clients = []
    for client_name in all_clients:
        if client_name in excluded_clients:
            continue
        prof = get_client_profile(client_name) or {}
        trader = (prof.get('trader') or '') or 'Unassigned'
        if trader in excluded_traders:
            continue
        filtered_clients.append(client_name)

    total_clients = len(filtered_clients)

    # Filter scan results to excluded traders/clients so leaderboard + top issues match the tracker.
    if excluded_traders or excluded_clients:
        scan_results = [
            r for r in (scan_results or [])
            if (r.get('client_id') not in excluded_clients)
            and ((r.get('trader') or 'Unassigned') not in excluded_traders)
        ]

    # Leaderboard health excludes payout QA (super-admin); issues list still shows it for top-issues counts.
    for r in scan_results:
        r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
        r['total_issues'], r['health_score'] = _trader_ranking_health_metrics(r.get('issues'))

    # Record Slack post time + baseline issue state (used only for implicit tie-breaks).
    # This does NOT change the message content — it only influences tie ordering later.
    try:
        posted_at = datetime.utcnow().isoformat()
        record_quality_slack_post(date, posted_at)
        for r in scan_results or []:
            upsert_quality_issue_baseline(
                date,
                str(r.get('client_id') or ''),
                str(r.get('trader') or ''),
                bool(r.get('total_issues') or 0),
            )
    except Exception:
        pass

    # Collect downtime data (rendered at the bottom for maximum visibility)
    downtime_clients = []
    try:
        for r in scan_results or []:
            for iss in r.get('issues', []) or []:
                if iss.get('check') == 'Downtime detected':
                    downtime_clients.append((
                        r.get('trader', 'Unknown') or 'Unknown',
                        r.get('client_id', '') or '',
                        iss.get('detail') or 'Downtime detected',
                    ))
    except Exception:
        downtime_clients = []

    clients_healthy = sum(1 for r in scan_results if r['health_score'] >= 90)
    clients_warning = sum(1 for r in scan_results if 70 <= r['health_score'] < 90)
    clients_critical = sum(1 for r in scan_results if r['health_score'] < 70)
    total_issues = sum(r['total_issues'] for r in scan_results)
    avg_health = round(sum(r['health_score'] for r in scan_results) / len(scan_results), 1) if scan_results else 0

    # Top issues by frequency
    issue_counts = {}
    for r in scan_results:
        for iss in r['issues']:
            issue_counts[iss['check']] = issue_counts.get(iss['check'], 0) + 1
    top_issues = sorted(issue_counts.items(), key=lambda x: -x[1])[:5]

    # Trader breakdown
    trader_stats = {}
    for r in scan_results:
        t = r.get('trader', 'Unknown')
        if t not in trader_stats:
            trader_stats[t] = {'clients': 0, 'issues': 0, 'health_sum': 0}
        trader_stats[t]['clients'] += 1
        trader_stats[t]['issues'] += r['total_issues']
        trader_stats[t]['health_sum'] += r['health_score']

    lines = [f"📊 *Daily Quality Summary — {weekday}, {date}*", ""]
    lines.append(f"🏢 *Portfolio:* {total_clients} total clients")
    if scan_results:
        lines.append(f"💚 Healthy (90%+): {clients_healthy}  |  🟡 Warning: {clients_warning}  |  🔴 Critical: {clients_critical}")
        lines.append(f"📈 Avg Health Score: *{avg_health}%*  |  Total Issues: *{total_issues}*")
    else:
        lines.append("⚠️ No quality scan results for today.")
    lines.append("")

    if top_issues:
        lines.append("🔍 *Top Issues:*")
        for check, count in top_issues:
            lines.append(f"  • {check}: {count} occurrences")
        lines.append("")

    # Build daily-summary missing counts per trader, to apply a penalty ONLY when NOT sent.
    # Weight: roughly "medium" severity = 5 points per missing client.
    missing_by_trader = {}
    total_by_trader = {}
    _apply_summary_penalty = True
    try:
        from dashboard.database import get_summary_status_for_date, get_setting, get_client_data
        from config.hierarchy import get_client_profile as _gcp
        from datetime import timezone, timedelta as _tz_td
        import json as _json_mod

        submissions = get_summary_status_for_date(date)
        sent_map = {s['client_id']: s for s in submissions}
        excluded_traders2 = set(_json_mod.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients2 = set(_json_mod.loads(get_setting('summary_tracker_excluded_clients') or '[]'))

        all_hierarchy_clients2 = hierarchy_get_all_clients()
        from datetime import timezone as _tz2, timedelta as _td2
        _eat_now = datetime.now(_tz2(_td2(hours=3)))
        if _should_skip_daily_summary_tracking(_eat_now):
            _apply_summary_penalty = False
        else:
            for client_name in all_hierarchy_clients2:
                profile = _gcp(client_name)
                trader = (profile.get('trader', '') if profile else '') or 'Unassigned'
                if trader in excluded_traders2 or client_name in excluded_clients2:
                    continue
                try:
                    cdata = get_client_data(client_name)
                    if cdata and isinstance(cdata.get('identity'), dict):
                        if cdata['identity'].get('active_status') == 'inactive':
                            continue
                except Exception:
                    pass
                total_by_trader[trader] = total_by_trader.get(trader, 0) + 1
                if client_name not in sent_map:
                    missing_by_trader[trader] = missing_by_trader.get(trader, 0) + 1
    except Exception:
        # If anything fails, do not penalize; keep previous behavior.
        _apply_summary_penalty = False

    if trader_stats:
        def _adjusted_avg(item):
            t, s = item
            raw = (s['health_sum'] / max(s['clients'], 1)) if s.get('clients') else 0.0
            if not _apply_summary_penalty:
                return raw
            missing = int(missing_by_trader.get(t, 0) or 0)
            total = int(total_by_trader.get(t, s.get('clients', 0)) or 0) or max(s.get('clients', 1), 1)
            # Deduct 5 points per missing client summary, distributed across trader's portfolio.
            deduction = 5.0 * (missing / max(total, 1))
            return max(0.0, raw - deduction)

        # Gamified Trader Issue Clearance Leaderboard — fastest full clearance first
        from dashboard.app import (
            _trader_leaderboard_entry_lines,
            _trader_leaderboard_sort_key,
        )
        ranked = sorted(
            trader_stats.items(),
            key=lambda it: _trader_leaderboard_sort_key(
                it[0], it[1], get_trader_issue_resolution_minutes(date, it[0]),
            ),
        )
        lines.append("🏆 *TRADER HEALTH LEADERBOARD*")
        lines.append("_Green bar = average client health for that trader._")
        lines.append("")
        total_traders = len(ranked)
        for rank, (t, s) in enumerate(ranked, 1):
            clear_mins = get_trader_issue_resolution_minutes(date, t)
            if rank == 1:
                medal = '🥇'
            elif rank == 2:
                medal = '🥈'
            elif rank == 3:
                medal = '🥉'
            else:
                medal = f'#{rank}'
            line1, line2 = _trader_leaderboard_entry_lines(t, clear_mins, s, medal)
            lines.append(line1.replace('**', '*'))
            lines.append(line2.replace('**', '*'))
        lines.append("")

    lines.append(f"📋 Checklists submitted today: *{len(checklists)}*")
    lines.append("")

    # ── Daily Summary Submission Tracker ──
    try:
        from dashboard.database import get_summary_status_for_date, get_setting, get_client_data
        from config.hierarchy import get_client_profile as _gcp
        from datetime import timezone, timedelta as _tz_td
        import json as _json_mod

        _kenyan_tz = timezone(_tz_td(hours=3))
        submissions = get_summary_status_for_date(date)
        for s in submissions:
            ts = s.get('submitted_at', '')
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    s['submitted_at'] = dt.astimezone(_kenyan_tz).isoformat()
                except Exception:
                    pass

        sent_map = {s['client_id']: s for s in submissions}
        excluded_traders = set(_json_mod.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients = set(_json_mod.loads(get_setting('summary_tracker_excluded_clients') or '[]'))

        all_hierarchy_clients = hierarchy_get_all_clients()
        tracker_traders = {}
        tracked_total = 0
        for client_name in all_hierarchy_clients:
            profile = _gcp(client_name)
            trader = (profile.get('trader', '') if profile else '') or 'Unassigned'
            if trader in excluded_traders or client_name in excluded_clients:
                continue
            try:
                cdata = get_client_data(client_name)
                if cdata and isinstance(cdata.get('identity'), dict):
                    if cdata['identity'].get('active_status') == 'inactive':
                        continue
            except Exception:
                pass
            tracked_total += 1
            if trader not in tracker_traders:
                tracker_traders[trader] = {'sent': [], 'not_sent': [], 'total': 0}
            tracker_traders[trader]['total'] += 1
            if client_name in sent_map:
                ts = sent_map[client_name].get('submitted_at', '')
                tracker_traders[trader]['sent'].append(ts)
            else:
                tracker_traders[trader]['not_sent'].append(client_name)

        tracker_complete = []   # 100% — will be ranked
        tracker_incomplete = [] # partial or zero sends
        for t, d in tracker_traders.items():
            sent_count = len(d['sent'])
            if sent_count == d['total']:
                minutes_list = []
                for ts in d['sent']:
                    try:
                        dt = datetime.fromisoformat(ts)
                        minutes_list.append(dt.hour * 60 + dt.minute)
                    except Exception:
                        pass
                avg_minutes = round(sum(minutes_list) / len(minutes_list)) if minutes_list else 1440
                avg_hh = avg_minutes // 60
                avg_mm = avg_minutes % 60
                avg_time_str = f"{avg_hh:02d}:{avg_mm:02d}"
                tracker_complete.append((t, sent_count, d['total'], avg_minutes, avg_time_str))
            else:
                tracker_incomplete.append((t, sent_count, d['total'], d['not_sent']))

        tracker_complete.sort(key=lambda x: x[3])
        tracker_incomplete.sort(key=lambda x: x[0])
        total_sent_summary = sum(x[1] for x in tracker_complete) + sum(x[1] for x in tracker_incomplete)

        lines.append("📬 *DAILY SUMMARY SUBMISSION BY MIDNIGHT (KENYAN TIME)*")
        from datetime import timezone as _tz2, timedelta as _td2
        _eat_now = datetime.now(_tz2(_td2(hours=3)))
        if _should_skip_daily_summary_tracking(_eat_now):
            lines.append(DAILY_SUMMARY_TRACKER_SKIP_MSG)
            lines.append("")
        else:
            pct = round(total_sent_summary / tracked_total * 100) if tracked_total else 0
            lines.append(f"✅ {total_sent_summary}/{tracked_total} sent ({pct}%)")
            lines.append("")
            if tracker_complete:
                lines.append("🏆 *Complete — ranked by earliest avg submission time:*")
                lines.append("_All your clients' summaries must be submitted to qualify. The earlier you submit, the higher you rank. 🥇 goes to the fastest!_")
                for rank, (t, sent, total, _avg_m, avg_t) in enumerate(tracker_complete, 1):
                    if rank == 1:
                        medal = '🥇'
                    elif rank == 2:
                        medal = '🥈'
                    elif rank == 3:
                        medal = '🥉'
                    else:
                        medal = f'#{rank}'
                    lines.append(f"{medal} *{t}* — {sent}/{total} ✅ · avg {avg_t}")
                lines.append("")
            if tracker_incomplete:
                lines.append("❌ *Incomplete — missing clients:*")
                for t, sent, total, missing in tracker_incomplete:
                    lines.append(f"⚠️ *{t}* — {sent}/{total} sent")
                    lines.append(f"   ⛔ {', '.join(missing)}")
                lines.append("")
            lines.append("👁️ _We track everything — every submission, every miss, every second._")
            lines.append("")
    except Exception as e:
        import traceback
        traceback.print_exc()

    # ── Admin Team Rankings (posted with daily Slack summary) ──
    try:
        from dashboard.app import _build_admin_teams_ranking_lines
        lines.extend(_build_admin_teams_ranking_lines(
            date, all_clients, excluded_clients, excluded_traders, for_slack=True,
        ))
    except Exception:
        pass

    # ── Downtime Alert (bottom of message for maximum visibility) ──
    if downtime_clients:
        lines.append("🚨🚨🚨 *DOWNTIME ALERT — ZERO TOLERANCE* 🚨🚨🚨")
        lines.append(f"⚠️ *{len(downtime_clients)} account(s) have stale trading days. This means the account was NOT traded on those days.*")
        lines.append("")
        for trader, client, detail in sorted(downtime_clients):
            # Keep this robust: detail formats differ depending on scan source.
            stale_part = detail.split('Stale day(s) found: ')[-1].split(' —')[0] if 'Stale day(s) found: ' in detail else detail
            lines.append(f"  🔴 *{client}* ({trader}) — {stale_part}")
        lines.append("")
        lines.append("‼️ *Downtime is unacceptable. Every trading day must be accounted for. Traders responsible for these accounts must explain immediately.*")
        lines.append("")
        # Divider goes LAST so nothing after it gets dropped by clients/bots.
        lines.append("━" * 30)
        lines.append("")

    return "\n".join(lines)


def post_slack_summary():
    """Build and post the daily quality summary to Slack."""
    try:
        text = _build_daily_summary_text()
        send_slack_message(text)
    except Exception as e:
        logging.error(f"Failed to build/post Slack summary: {e}")


# ── Database Cleanup ─────────────────────────────────────────────────
def run_database_cleanup():
    """Run daily database cleanup: prune data_history, audit_log, expired sessions."""
    try:
        from dashboard.database import cleanup_database
        results = cleanup_database()
        logging.info(f"Database cleanup results: {results}")
    except Exception as e:
        logging.error(f"Database cleanup failed: {e}")


def update_all_clients_watermarks():
    try:
        clients = get_all_clients()  # Returns a dict: {client_id: client_data}
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        for client_id, client in clients.items():
            try:
                # Pull net profit directly from stored statistics
                # (already includes discrepancy from the last data push)
                stored_stats = client.get('statistics', {})
                if not isinstance(stored_stats, dict):
                    logging.info(f"Skipping {client_id}: no statistics data")
                    continue

                net_profit = stored_stats.get('cashflow_inprogress', {}).get('net_profit')
                if net_profit is None:
                    net_profit = stored_stats.get('profitability_completed', {}).get('net_profit')
                if net_profit is None:
                    logging.info(f"Skipping {client_id}: no net_profit in statistics")
                    continue
                
                # Save daily snapshot
                save_daily_profit(client_id, net_profit, today_str, source='auto')
                logging.info(f"Updated watermark for {client_id}: {net_profit}")
                
            except Exception as e:
                logging.error(f"Error updating client {client_id}: {e}")
                
    except Exception as e:
        logging.error(f"Error in update_all_clients_watermarks: {e}")

def start_scheduler():
    global _scheduler_started
    # Flask's Werkzeug reloader spawns TWO processes: a parent watcher and a
    # child that actually serves.  Only start the scheduler in the child
    # (WERKZEUG_RUN_MAIN='true') to avoid duplicate threads.  When the
    # reloader is disabled (e.g. production), WERKZEUG_RUN_MAIN is unset and
    # there is only one process — that's fine, start normally.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return None  # Parent watcher process — skip
    with _scheduler_lock:
        if _scheduler_started:
            logging.info("Scheduler already running — skipping duplicate start.")
            return None
        _scheduler_started = True
    # Ensure stop_event is clear so the new thread's loop runs
    stop_event.clear()
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    return t
