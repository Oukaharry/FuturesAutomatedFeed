import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from .database import get_connection

class PhaseManager:
    """
    Manages the lifecycle of trading phases (Challenge -> Funded -> Farming)
    using a deterministic, database-driven approach.
    """

    @staticmethod
    def initialize_default_phases():
        """Idempotently populates default phase definitions if they don't exist."""
        defaults = [
            # Challenge Phase 1
            {
                "phase_name": "Challenge Phase 1",
                "phase_code": "CH", 
                "sequence_order": 1,
                "ruleset": json.dumps({"type": "CHALLENGE", "target_percent": 0.08, "daily_loss": 0.05, "max_loss": 0.10}),
                "next_phase_code": "CH2" # Assuming 2-step challenge for now, or straight to FD
            },
            # Challenge Phase 2 (Optional, many firms have 2 steps)
             {
                "phase_name": "Challenge Phase 2",
                "phase_code": "CH2", 
                "sequence_order": 2,
                "ruleset": json.dumps({"type": "CHALLENGE", "target_percent": 0.05}),
                "next_phase_code": "FD" 
            },
            # Funded Phase
            {
                "phase_name": "Funded Account",
                "phase_code": "FD",
                "sequence_order": 3,
                "ruleset": json.dumps({"type": "FUNDED", "payout_split": 0.80}),
                "next_phase_code": "FA"
            },
            # Farming Phase
            {
                "phase_name": "Farming Phase",
                "phase_code": "FA",
                "sequence_order": 4,
                "ruleset": json.dumps({"type": "ACCUMULATION"}),
                "next_phase_code": "FA" # Loops or stays in Farming
            }
        ]

        with get_connection() as conn:
            cursor = conn.cursor()
            for phase in defaults:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO phase_definitions 
                        (phase_name, phase_code, sequence_order, ruleset, next_phase_code)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        phase["phase_name"],
                        phase["phase_code"],
                        phase["sequence_order"],
                        phase["ruleset"],
                        phase["next_phase_code"]
                    ))
                except Exception as e:
                    print(f"Error seeding phase {phase['phase_code']}: {e}")
            conn.commit()

    @staticmethod
    def create_evaluation(
        account_signature: str,
        phase_code: str,
        start_date: str, # ISO Format YYYY-MM-DD
        parent_id: Optional[int] = None,
        reset_id: Optional[str] = None
    ) -> int:
        """
        Creates a new evaluation record.
        """
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get validation rules from definition
            cursor.execute("SELECT sequence_order, ruleset FROM phase_definitions WHERE phase_code=?", (phase_code,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Unknown phase code: {phase_code}")
            
            phase_number = row['sequence_order'] # Mapping sequence to phase_number for simplicity, or we can use auto-incrementing int
            
            # Use provided reset_id or inherit from parent
            final_reset_id = reset_id
            if not final_reset_id and parent_id:
                cursor.execute("SELECT reset_id FROM evaluations WHERE id=?", (parent_id,))
                parent = cursor.fetchone()
                if parent:
                    final_reset_id = parent['reset_id']
            
            cursor.execute('''
                INSERT INTO evaluations 
                (account_signature, phase_number, phase_type, status, start_date, parent_id, reset_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                account_signature, 
                phase_number, 
                phase_code, 
                'active', 
                start_date, 
                parent_id, 
                final_reset_id
            ))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def complete_phase(evaluation_id: int, status: str, end_date: str) -> Optional[int]:
        """
        Marks a phase as completed/failed and triggers the next phase creation if successful.
        Returns the ID of the newly created next phase, or None.
        """
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Update current phase
            cursor.execute('''
                UPDATE evaluations 
                SET status = ?, end_date = ?
                WHERE id = ?
            ''', (status, end_date, evaluation_id))
            
            if status != 'passed':
                conn.commit()
                return None
                
            # 2. Fetch current evaluation details to determine next step
            cursor.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,))
            current_eval = cursor.fetchone()
            
            if not current_eval:
                conn.commit()
                return None
                
            current_phase_code = current_eval['phase_type']
            account_sig = current_eval['account_signature']
            reset_id = current_eval['reset_id']
            
            # 3. Find next phase definition
            cursor.execute("SELECT next_phase_code FROM phase_definitions WHERE phase_code=?", (current_phase_code,))
            def_row = cursor.fetchone()
            
            if not def_row or not def_row['next_phase_code']:
                conn.commit()
                return None # End of chain
                
            next_code = def_row['next_phase_code']
            
            # 4. Calculate next start date (Next Day)
            # Ensure dates are date objects
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                next_start_dt = end_dt + timedelta(days=1)
                next_start_str = next_start_dt.strftime("%Y-%m-%d")
            except ValueError:
                # Fallback if date is not simple YYYY-MM-DD
                next_start_str = end_date 
            
            # 5. Create next phase
            # Call create_evaluation (need to pass connection or do it in same transaction? 
            # Doing here manually to keep transaction atomic)
            
            cursor.execute("SELECT sequence_order FROM phase_definitions WHERE phase_code=?", (next_code,))
            next_def = cursor.fetchone()
            next_seq = next_def['sequence_order'] if next_def else current_eval['phase_number'] + 1

            cursor.execute('''
                INSERT INTO evaluations 
                (account_signature, phase_number, phase_type, status, start_date, parent_id, reset_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                account_sig,
                next_seq,
                next_code,
                'active',
                next_start_str,
                evaluation_id,
                reset_id
            ))
            
            new_id = cursor.lastrowid
            conn.commit()
            return new_id

    @staticmethod
    def find_evaluation_for_trade(account_signature: str, trade_date_str: str) -> Optional[Dict]:
        """
        Deterministic O(1) matching of trade to evaluation using Date Windows.
        trade_date_str: YYYY-MM-DD
        """
        # We need to handle datetime strings potentially including time
        # The prompt says: "start_date <= trade.close_date <= end_date"
        # We assume start/end dates in DB are YYYY-MM-DD.
        # Trade date might be YYYY-MM-DD HH:MM:SS.
        
        trade_date_only = trade_date_str.split(' ')[0] if ' ' in trade_date_str else trade_date_str

        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Find evaluation where trade_date is >= start_date AND (end_date IS NULL OR trade_date <= end_date)
            # We treat NULL end_date as "Open/Active"
            cursor.execute('''
                SELECT * FROM evaluations 
                WHERE account_signature = ?
                AND start_date <= ?
                AND (end_date IS NULL OR end_date >= ?)
                ORDER BY start_date DESC
                LIMIT 1
            ''', (account_signature, trade_date_only, trade_date_only))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    @staticmethod
    def get_phase_chain(latest_evaluation_id: int) -> List[Dict]:
        """Traverses up the parent_id chain to get full history."""
        chain = []
        curr_id = latest_evaluation_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            while curr_id:
                cursor.execute("SELECT * FROM evaluations WHERE id=?", (curr_id,))
                row = cursor.fetchone()
                if not row:
                    break
                chain.append(dict(row))
                curr_id = row['parent_id']
                
        return list(reversed(chain)) # Return chronological order
