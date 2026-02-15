from dashboard.phase_manager import PhaseManager
from dashboard.database import init_database, get_connection
import os

# Initialize database (creates tables if not exist)
init_database()

# Seed phases
PhaseManager.initialize_default_phases()

def test_chain():
    print("Testing Dynamic Phase Chain...")
    
    # Simulate a new Challenge Phase 1 starting today (2026-02-14)
    # Reset ID: R1
    ev_id = PhaseManager.create_evaluation(
        account_signature="FNFT12345",
        phase_code="CH",
        start_date="2026-02-14",
        reset_id="R1"
    )
    print(f"Created Evaluation {ev_id} (CH Phase 1)")

    # Simulate passing Phase 1 on 2026-02-20
    next_ev_id = PhaseManager.complete_phase(ev_id, "passed", end_date="2026-02-20")
    print(f"Passed Phase 1. Next Evaluation ID: {next_ev_id}")
    
    # Verify next phase details
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evaluations WHERE id=?", (next_ev_id,))
        next_ev = cursor.fetchone()
        print(f"Next Phase Details: Phase {next_ev['phase_number']} ({next_ev['phase_type']})")
        print(f"Start Date: {next_ev['start_date']} (Should be 2026-02-21)")
        print(f"Parent ID: {next_ev['parent_id']} (Should be {ev_id})")

    # Simulate passing Phase 2 (CH2) on 2026-02-25
    final_ev_id = PhaseManager.complete_phase(next_ev_id, "passed", end_date="2026-02-25")
    print(f"Passed Phase 2. Next Evaluation ID: {final_ev_id}")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evaluations WHERE id=?", (final_ev_id,))
        final_ev = cursor.fetchone()
        print(f"Final Phase Details: Phase {final_ev['phase_number']} ({final_ev['phase_type']})")

    # Test Matching Logic
    print("\n--- Testing Trade Matching ---")
    
    # Trade on 2026-02-15 (Should match Phase 1)
    match1 = PhaseManager.find_evaluation_for_trade("FNFT12345", "2026-02-15 10:00:00")
    print(f"Trade (2026-02-15) -> Matches ID {match1['id']} ({match1['phase_type']})")
    
    # Trade on 2026-02-22 (Should match Phase 2)
    match2 = PhaseManager.find_evaluation_for_trade("FNFT12345", "2026-02-22 14:30:00")
    print(f"Trade (2026-02-22) -> Matches ID {match2['id']} ({match2['phase_type']})")

    # Trade on 2026-03-01 (Should match Funded Phase / Active)
    match3 = PhaseManager.find_evaluation_for_trade("FNFT12345", "2026-03-01 09:00:00")
    print(f"Trade (2026-03-01) -> Matches ID {match3['id']} ({match3['phase_type']})")

if __name__ == "__main__":
    try:
        test_chain()
    except Exception as e:
        import traceback
        traceback.print_exc()
