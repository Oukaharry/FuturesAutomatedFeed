"""
_set_admin_slack_ids.py
-----------------------
Interactively set Slack Member IDs for each admin in hierarchy.json.

HOW TO USE
----------
1. Run this script from the project root:

       py _set_admin_slack_ids.py

2. For each admin you will be shown their current Slack ID (if any).
   - Paste the Slack Member ID (e.g. U0123ABCDEF) and press Enter to update.
   - Press Enter with no input to KEEP the existing value unchanged.
   - Type  clear  and press Enter to REMOVE an existing ID.

3. At the end confirm to save. The file is backed up automatically before writing.

HOW TO FIND A SLACK MEMBER ID
------------------------------
  Slack desktop: click the person's name → View profile → ⋮ More → Copy member ID
  The ID always starts with U and is ~11 characters, e.g. U0123ABCDEF

PRODUCTION USE
--------------
  Copy this script to your production server alongside hierarchy.json
  (or adjust HIERARCHY_FILE below) and run it the same way.
"""

import json
import os
import shutil
from datetime import datetime

# ── Path to hierarchy.json ────────────────────────────────────────────────────
HIERARCHY_FILE = os.path.join(os.path.dirname(__file__), "config", "hierarchy.json")

# ─────────────────────────────────────────────────────────────────────────────

def load():
    if not os.path.exists(HIERARCHY_FILE):
        print(f"ERROR: hierarchy.json not found at {HIERARCHY_FILE}")
        raise SystemExit(1)
    with open(HIERARCHY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save(data):
    # Backup first
    backup = HIERARCHY_FILE + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(HIERARCHY_FILE, backup)
    print(f"\n  Backup saved → {os.path.basename(backup)}")
    with open(HIERARCHY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"  hierarchy.json updated ✓\n")

def main():
    data = load()
    admins = data.get("admins", {})

    if not admins:
        print("No admins found in hierarchy.json.")
        return

    print("\n" + "=" * 60)
    print("  SET SLACK MEMBER IDs FOR ADMINS")
    print("=" * 60)
    print("  Press Enter to keep current value.")
    print("  Type  clear  to remove an existing ID.\n")

    changes = {}

    for admin_name, admin_data in admins.items():
        current_id = admin_data.get("slack_user_id", "")
        current_display = f'"{current_id}"' if current_id else "(none)"
        print(f"  Admin : {admin_name}")
        print(f"  Email : {admin_data.get('email', '(no email)')}")
        print(f"  Current Slack ID : {current_display}")

        raw = input("  New Slack Member ID → ").strip()

        if raw == "":
            print("  → Keeping unchanged.\n")
        elif raw.lower() == "clear":
            changes[admin_name] = ""
            print("  → Will clear Slack ID.\n")
        else:
            # Basic sanity check: Slack member IDs start with U or W and are 9-11 chars
            if not (raw[0] in ("U", "W") and raw.isalnum() and 9 <= len(raw) <= 12):
                confirm = input(f'  ⚠  "{raw}" doesn\'t look like a typical Slack member ID (U/W + digits). Use it anyway? [y/N] ').strip().lower()
                if confirm != "y":
                    print("  → Skipped.\n")
                    continue
            changes[admin_name] = raw
            print(f"  → Will set to: {raw}\n")

    if not changes:
        print("No changes to make. Exiting.")
        return

    print("-" * 60)
    print("SUMMARY OF CHANGES:")
    for name, new_id in changes.items():
        old_id = admins[name].get("slack_user_id", "(none)")
        arrow = f'"{old_id}" → "{new_id}"' if new_id else f'"{old_id}" → (cleared)'
        print(f"  {name}: {arrow}")

    confirm = input("\nSave changes to hierarchy.json? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted. No changes written.")
        return

    for admin_name, new_id in changes.items():
        data["admins"][admin_name]["slack_user_id"] = new_id

    save(data)
    print("Done. Restart your Flask app to pick up the new values.\n")

if __name__ == "__main__":
    main()
