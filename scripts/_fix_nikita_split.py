"""Remove stale 7/21/2026 net override so 8/16-8/30 split is $0.

Stale override ($116,428.88) understated 7/21-8/15 and deferred split into
8/16-8/30 while daily net was flat. Run against local or prod DB via env vars.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_TYPE", "postgresql")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_DB", "tradeopss")

from dashboard.database import get_client_data, get_connection
from dashboard.watermark_service import canonical_client_stats_net, compute_waterlog_from_db

CLIENT_ID = "Nikita"
BAD_PERIOD = "7/21/2026"


def _period_row(wl, to_date):
    for p in wl.get("periods") or []:
        if p.get("to_date") == to_date:
            return p
    return None


def show(label, wl):
    p715 = _period_row(wl, "8/15/2026")
    p830 = _period_row(wl, "8/30/2026")
    print(f"\n{label}")
    if p715:
        print(f"  7/21-8/15: low={p715['low']} split={p715['profit_split']}")
    if p830:
        print(f"  8/16-8/30: low={p830['low']} split={p830['profit_split']}")


def main():
    data = get_client_data(CLIENT_ID) or {}
    live = canonical_client_stats_net(data)
    wl_before = compute_waterlog_from_db(CLIENT_ID, _live_net=live)
    show("BEFORE", wl_before)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM net_profit_overrides WHERE client_id = %s AND from_date = %s",
            (CLIENT_ID, BAD_PERIOD),
        )
        deleted = cur.rowcount
        conn.commit()
    print(f"\nDeleted net_profit_override rows: {deleted} ({CLIENT_ID} / {BAD_PERIOD})")

    wl_after = compute_waterlog_from_db(CLIENT_ID, _live_net=live)
    show("AFTER", wl_after)


if __name__ == "__main__":
    main()
