import threading
import time
from datetime import datetime
import logging
from dashboard.database import get_all_clients
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
        clients = get_all_clients()  # Returns a dict: {client_id: client_data}
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        for client_id, client in clients.items():
            try:
                # evaluations is already parsed by get_all_clients -> get_client_data
                evals = client.get('evaluations', [])
                if not evals:
                    logging.info(f"Skipping {client_id}: no evaluations data")
                    continue

                # Use calculate_statistics — same formula as the dashboard
                # Formula: Net Profit = Payouts + Hedging + Farming - Challenge Fees + Discrepancy
                # Matches Excel: =B6+B3+B4+B5+B25
                from utils.data_processor import calculate_statistics
                stats = calculate_statistics(evals)
                net_profit = stats['profitability_completed']['net_profit']
                
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
