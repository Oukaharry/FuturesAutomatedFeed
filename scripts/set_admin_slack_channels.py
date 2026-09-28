#!/usr/bin/env python3
"""Set slack_channel_id for admins in config/hierarchy.json.

Usage:
  python scripts/set_admin_slack_channels.py \\
    "Marion Nyika=C0123ABC" "Dennis Muthee=C0456DEF"

Or edit CHANNELS below and run without arguments.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Optional bulk map — fill in and run: python scripts/set_admin_slack_channels.py
CHANNELS = {
    # "Marion Nyika": "C0123456789",
}


def _parse_pairs(argv):
    out = {}
    for arg in argv:
        if '=' not in arg:
            print(f"Skip (expected Admin Name=C0123...): {arg}")
            continue
        name, cid = arg.split('=', 1)
        name, cid = name.strip(), cid.strip()
        if not name or not cid:
            continue
        if not cid.startswith('C'):
            print(f"Warning: {name} channel id {cid!r} does not start with C")
        out[name] = cid
    return out


def main():
    mapping = dict(CHANNELS)
    mapping.update(_parse_pairs(sys.argv[1:]))
    if not mapping:
        print("No channels to set. Pass Admin=C0123... args or edit CHANNELS in this script.")
        sys.exit(1)

    from config.hierarchy import SYSTEM_HIERARCHY, reload_hierarchy, save_hierarchy

    reload_hierarchy()
    changed = 0
    for admin_name, channel_id in mapping.items():
        if admin_name not in SYSTEM_HIERARCHY.get('admins', {}):
            print(f"Unknown admin: {admin_name!r}")
            continue
        SYSTEM_HIERARCHY['admins'][admin_name]['slack_channel_id'] = channel_id
        print(f"  {admin_name} -> {channel_id}")
        changed += 1
    if not changed:
        print("Nothing updated.")
        sys.exit(1)
    save_hierarchy(SYSTEM_HIERARCHY)
    print(f"Updated {changed} admin(s) in hierarchy.json")


if __name__ == '__main__':
    main()
