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

# Track which jobs already ran today to avoid double-runs
_ran_today = {'watermark': None, 'quality_scan': None, 'slack_summary': None}


def run_scheduler():
    logging.info("Starting Daily Scheduler (watermark + quality scan + Slack)...")
    while not stop_event.is_set():
        try:
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')

            # 00:00 — Midnight watermark snapshot
            if now.hour == 0 and now.minute == 0 and _ran_today['watermark'] != today:
                logging.info("Running midnight watermark update...")
                update_all_clients_watermarks()
                _ran_today['watermark'] = today
                time.sleep(60)

            # 02:00 — Automated quality scan
            if now.hour == 2 and now.minute == 0 and _ran_today['quality_scan'] != today:
                logging.info("Running scheduled quality scan...")
                run_scheduled_quality_scan()
                _ran_today['quality_scan'] = today
                time.sleep(60)

            # 02:05 — Post daily summary to Slack (after scan finishes)
            if now.hour == 2 and now.minute == 5 and _ran_today['slack_summary'] != today:
                logging.info("Posting daily quality summary to Slack...")
                post_slack_summary()
                _ran_today['slack_summary'] = today
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
    """Read Slack webhook URL from environment or .env file."""
    url = os.environ.get('SLACK_WEBHOOK_URL', '').strip()
    if url:
        return url
    # Fallback: read from .env file in project root
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
    from dashboard.database import get_quality_scan_results, get_daily_checklists
    from config.hierarchy import get_all_clients as hierarchy_get_all_clients

    now = datetime.now()
    date = now.strftime('%Y-%m-%d')
    weekday = now.strftime('%A')

    scan_results = get_quality_scan_results(date)
    checklists = get_daily_checklists(date)
    total_clients = len(hierarchy_get_all_clients())

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

    if trader_stats:
        lines.append("👤 *Trader Breakdown:*")
        for t, s in sorted(trader_stats.items(), key=lambda x: x[1]['health_sum'] / max(x[1]['clients'], 1)):
            avg = round(s['health_sum'] / s['clients'], 1)
            emoji = '💚' if avg >= 90 else '🟡' if avg >= 70 else '🔴'
            lines.append(f"  {emoji} {t}: {s['clients']} clients, {s['issues']} issues, {avg}% health")
        lines.append("")

    lines.append(f"📋 Checklists submitted today: *{len(checklists)}*")

    return "\n".join(lines)


def post_slack_summary():
    """Build and post the daily quality summary to Slack."""
    try:
        text = _build_daily_summary_text()
        send_slack_message(text)
    except Exception as e:
        logging.error(f"Failed to build/post Slack summary: {e}")

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
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    return t
