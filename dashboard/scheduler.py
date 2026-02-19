import threading
import time
from datetime import datetime
import logging
from dashboard.database import get_all_clients
from dashboard.financial_overview import calculate_propfirm_overview, get_payouts_history
# Circular import potential? financial_overview might import database. Yes.
# But database imports are usually fine if functions are used inside other functions.

from dashboard.watermark_service import save_daily_profit

stop_event = threading.Event()

def run_scheduler():
    logging.info("Starting Daily Watermark Scheduler...")
    while not stop_event.is_set():
        try:
            now = datetime.now()
            # Check if it's close to midnight (e.g., 00:00 - 00:05)
            # OR Check if we haven't run today.
            # Ideally, we want to capture the value at the END of the day (23:59) or START of next (00:00).
            # Let's say we run at 00:00.
            
            # Simple approach: Check every minute. If time is 00:00, run.
            # To avoid multiple runs in same minute, we can sleep 60s.
            
            if now.hour == 0 and now.minute == 0:
                logging.info("Running midnight watermark update...")
                update_all_clients_watermarks()
                time.sleep(60) # Sleep to avoid double run
            
            time.sleep(30) # Check every 30s
            
        except Exception as e:
            logging.error(f"Scheduler error: {e}")
            time.sleep(60)

def update_all_clients_watermarks():
    try:
        clients = get_all_clients()
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        for client in clients:
            client_id = client['client_id']
            try:
                # Calculate Net Profit Complete
                # We need evaluations data. client object has 'evaluations' as stringified JSON or dict?
                # database.get_all_clients returns row objects which behave like dicts but fields might be strings.
                import json
                evals = client['evaluations']
                if isinstance(evals, str):
                    evals = json.loads(evals)
                    
                # We need calculate_propfirm_overview logic re-used.
                # But that function takes (evaluations, payout_history).
                # Payout history is fetched via get_payouts_history(client_id).
                
                payouts = get_payouts_history(client_id)
                overview = calculate_propfirm_overview(evals, payouts)
                
                # Net Profit Complete is usually in overview['total_net_profit'] or similar?
                # Let's check keys in financial_overview.
                net_profit = overview.get('net_profit', 0.0) 
                
                # Save
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
