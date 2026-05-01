#!/usr/bin/env python3
"""
Delete a trader (by email) from hierarchy, user_credentials, and all clients under them.

Usage (from repo root):
  python scripts/delete_trader_by_email.py trader@example.com

One-liner (from repo root; set REPO to your clone path if not cwd):
  python -c "import sys,importlib.util;from pathlib import Path;r=str(Path('.').resolve());sys.path.insert(0,r);spec=importlib.util.spec_from_file_location('dt',Path(r)/'scripts/delete_trader_by_email.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.delete_trader_by_email('trader@example.com')"

Requires DB and config/hierarchy files to match your deployed environment.
"""
from __future__ import annotations

import os
import sys

# Repo root (parent of scripts/)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def _find_trader_in_hierarchy_by_email(hierarchy: dict, email: str) -> tuple[str, str]:
    """Return (admin_name, trader_name) if a trader lane has this email."""
    e = (email or "").lower().strip()
    if not e:
        return "", ""
    for admin_name, admin_data in (hierarchy.get("admins") or {}).items():
        for trader_name, trader_data in (admin_data.get("traders") or {}).items():
            te = (trader_data.get("email") or "").lower().strip()
            if te == e:
                return str(admin_name).strip(), str(trader_name).strip()
    return "", ""


def _find_admin_for_trader_key(hierarchy: dict, trader_name: str) -> str:
    """If trader login name is known, find which admin owns that lane."""
    tn = (trader_name or "").strip()
    if not tn:
        return ""
    for admin_name, admin_data in (hierarchy.get("admins") or {}).items():
        if tn in (admin_data.get("traders") or {}):
            return str(admin_name).strip()
    return ""


def _clients_and_admin_for_trader(hierarchy: dict, trader_name: str) -> tuple[list[str], str]:
    """All client names under this trader lane (first matching admin only) + admin name."""
    tn = (trader_name or "").strip()
    if not tn:
        return [], ""
    for admin_name, admin_data in (hierarchy.get("admins") or {}).items():
        lane = (admin_data.get("traders") or {}).get(tn)
        if not lane:
            continue
        names = []
        for c in lane.get("clients") or []:
            nm = (c.get("name") or "").strip()
            if nm:
                names.append(nm)
        return names, str(admin_name).strip()
    return [], ""


def _lookup_trader_credentials_by_email(email: str):
    """Match trader row by email (any is_active). Returns dict or None."""
    from dashboard.database import get_direct_connection

    e = (email or "").lower().strip()
    with get_direct_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, email, user_type, parent_admin, parent_trader, is_active
            FROM user_credentials
            WHERE user_type = 'trader' AND LOWER(TRIM(COALESCE(email, ''))) = ?
            ORDER BY is_active DESC
            LIMIT 5
            """,
            (e,),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    return _row_to_dict(rows[0])


def delete_trader_by_email(email: str) -> None:
    email = (email or "").strip().lower()
    if not email:
        print("No email provided.", file=sys.stderr)
        sys.exit(1)

    from config.hierarchy import (
        reload_hierarchy,
        remove_trader,
        save_hierarchy,
        SYSTEM_HIERARCHY,
        get_user_by_email,
    )
    from dashboard.database import (
        delete_user_credential,
        delete_client_data,
        get_direct_connection,
    )

    reload_hierarchy()

    hi = get_user_by_email(email)
    db_row = _lookup_trader_credentials_by_email(email)

    trader_name = ""
    admin = ""

    if hi and hi.get("user_type") == "trader":
        trader_name = (hi.get("username") or "").strip()
        admin = (hi.get("parent_admin") or "").strip()

    if db_row:
        trader_name = trader_name or (db_row.get("username") or "").strip()
        pa = db_row.get("parent_admin")
        admin = admin or (str(pa).strip() if pa is not None else "")

    ha, ht = _find_trader_in_hierarchy_by_email(SYSTEM_HIERARCHY, email)
    trader_name = trader_name or ht
    admin = admin or ha

    if trader_name and not admin:
        admin = _find_admin_for_trader_key(SYSTEM_HIERARCHY, trader_name)

    if not trader_name:
        if db_row:
            print(
                f"Found trader credential for {email!r} but login username is blank in DB; "
                "removing hierarchy lane(s) matched by email and user_credentials row.",
                file=sys.stderr,
            )
            try:
                for an in list((SYSTEM_HIERARCHY.get("admins") or {}).keys()):
                    traders = (SYSTEM_HIERARCHY.get("admins", {}).get(an) or {}).get("traders") or {}
                    for tn, td in list(traders.items()):
                        te = (td.get("email") or "").lower().strip()
                        if te != email:
                            continue
                        try:
                            with get_direct_connection() as conn:
                                cur = conn.cursor()
                                cur.execute("DELETE FROM api_keys WHERE trader = ?", (tn,))
                                conn.commit()
                        except Exception:
                            pass
                        for c in td.get("clients") or []:
                            cid = (c.get("name") or "").strip()
                            if cid:
                                try:
                                    with get_direct_connection() as conn:
                                        cur = conn.cursor()
                                        cur.execute("DELETE FROM api_keys WHERE client = ?", (cid,))
                                        conn.commit()
                                except Exception:
                                    pass
                                print(f"  Removing client {cid!r} (credentials + DB data)…")
                                delete_user_credential(cid, "client")
                                delete_client_data(cid)
                        remove_trader(an, tn)
                reg = SYSTEM_HIERARCHY.get("traders")
                if isinstance(reg, dict):
                    for tn, meta in list(reg.items()):
                        me = (meta.get("email") or "").lower().strip() if isinstance(meta, dict) else ""
                        if me == email:
                            del reg[tn]
                    save_hierarchy(SYSTEM_HIERARCHY)
                with get_direct_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        DELETE FROM user_credentials
                        WHERE user_type = 'trader' AND LOWER(TRIM(COALESCE(email, ''))) = ?
                        """,
                        (email,),
                    )
                    conn.commit()
            except Exception as ex:
                print(f"Error: {ex}", file=sys.stderr)
                sys.exit(1)
            print("Done (email-only / incomplete trader row).")
            sys.exit(0)
        if not trader_name:
            print(f"No trader found for email: {email}", file=sys.stderr)
            sys.exit(1)

    if not admin:
        client_names, guessed = _clients_and_admin_for_trader(SYSTEM_HIERARCHY, trader_name)
        admin = guessed
    else:
        client_names, _ = _clients_and_admin_for_trader(SYSTEM_HIERARCHY, trader_name)
        # If we know admin, still use full client list from that lane when possible
        try:
            lane = (
                SYSTEM_HIERARCHY.get("admins", {})
                .get(admin, {})
                .get("traders", {})
                .get(trader_name, {})
            )
            client_names = [
                (c.get("name") or "").strip()
                for c in (lane.get("clients") or [])
                if (c.get("name") or "").strip()
            ]
        except Exception:
            pass

    if not client_names:
        client_names, guessed_admin = _clients_and_admin_for_trader(SYSTEM_HIERARCHY, trader_name)
        if not admin and guessed_admin:
            admin = guessed_admin

    admin_disp = admin or "(unknown admin — will try all lanes / DB-only cleanup)"
    print(f"Found trader email {email!r} -> {trader_name!r} under admin {admin_disp!r}. Proceeding…")

    # API keys + sessions tied to this trader or their clients
    try:
        with get_direct_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM api_keys WHERE trader = ?", (trader_name,))
            for cid in client_names:
                cur.execute("DELETE FROM api_keys WHERE client = ?", (cid,))
            for uid, ut in [(trader_name, "trader"), *[(c, "client") for c in client_names]]:
                try:
                    cur.execute(
                        "DELETE FROM sessions WHERE user_identifier = ? AND user_type = ?",
                        (uid, ut),
                    )
                except Exception:
                    pass
            conn.commit()
    except Exception as ex:
        print(f"Warning: api_keys/sessions cleanup: {ex}", file=sys.stderr)

    for cid in client_names:
        print(f"  Removing client {cid!r} (credentials + DB data)…")
        delete_user_credential(cid, "client")
        delete_client_data(cid)

    print("  Removing trader from hierarchy…")
    removed = False
    if admin:
        if remove_trader(admin, trader_name):
            removed = True
    if not removed:
        for an in list((SYSTEM_HIERARCHY.get("admins") or {}).keys()):
            if remove_trader(an, trader_name):
                removed = True
                admin = admin or an
                break
    if not removed:
        # Lane key may differ from login name; remove by trader-lane email match.
        for an in list((SYSTEM_HIERARCHY.get("admins") or {}).keys()):
            traders = (SYSTEM_HIERARCHY.get("admins", {}).get(an) or {}).get("traders") or {}
            for tn, td in list(traders.items()):
                te = (td.get("email") or "").lower().strip()
                if te == email:
                    if remove_trader(an, tn):
                        removed = True
                        admin = admin or an
                        trader_name = trader_name or str(tn).strip()
                        break
            if removed:
                break
    if not removed:
        print(
            "Warning: trader lane not found in hierarchy (already removed or name mismatch). "
            "Continuing DB credential cleanup.",
            file=sys.stderr,
        )

    reg = SYSTEM_HIERARCHY.get("traders")
    if isinstance(reg, dict) and trader_name in reg:
        del reg[trader_name]
        save_hierarchy(SYSTEM_HIERARCHY)

    if trader_name:
        delete_user_credential(trader_name, "trader")
    # Catch orphan rows: username empty or duplicate keyed by email only
    try:
        with get_direct_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM user_credentials
                WHERE user_type = 'trader' AND LOWER(TRIM(COALESCE(email, ''))) = ?
                """,
                (email,),
            )
            conn.commit()
    except Exception as ex:
        print(f"Warning: email-based credential cleanup: {ex}", file=sys.stderr)

    print(f"Done. Trader {trader_name!r} / email {email!r} removed from DB and hierarchy (best effort).")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/delete_trader_by_email.py <email>", file=sys.stderr)
        sys.exit(1)
    delete_trader_by_email(sys.argv[1])


if __name__ == "__main__":
    main()
