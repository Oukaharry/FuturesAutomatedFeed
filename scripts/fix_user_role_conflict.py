import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from dashboard.database import get_connection  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Deactivate duplicate user_credentials roles for an email.")
    ap.add_argument("--email", required=True, help="Email address to fix")
    ap.add_argument(
        "--keep",
        default="client",
        choices=["client", "admin", "trader"],
        help="Which user_type to keep active (default: client)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would change",
    )
    args = ap.parse_args()

    email_norm = args.email.strip().lower()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, email, user_type, is_active, last_login, created_at
            FROM user_credentials
            WHERE lower(email) = ?
            ORDER BY id ASC
            """,
            (email_norm,),
        )
        rows = cur.fetchall() or []

        if not rows:
            print(f"No rows found for email={args.email!r}")
            return

        print("Found rows:")
        for r in rows:
            print(
                f"- id={r.get('id')} username={r.get('username')!r} user_type={r.get('user_type')!r} "
                f"is_active={r.get('is_active')} last_login={r.get('last_login')!r}"
            )

        to_deactivate = [r for r in rows if (r.get("user_type") or "").strip() != args.keep and int(r.get("is_active") or 0) == 1]

        if not to_deactivate:
            print(f"Nothing to deactivate (keep={args.keep!r}).")
            return

        print("\nWill deactivate:")
        for r in to_deactivate:
            print(f"- id={r.get('id')} user_type={r.get('user_type')!r} username={r.get('username')!r}")

        if args.dry_run:
            print("\nDry-run: no changes applied.")
            return

        cur.execute(
            """
            UPDATE user_credentials
            SET is_active = 0, updated_at = now()::text
            WHERE lower(email) = ? AND user_type != ? AND is_active = 1
            """,
            (email_norm, args.keep),
        )
        conn.commit()
        print(f"\nDeactivated {cur.rowcount} row(s) for email={args.email!r} (kept {args.keep!r}).")


if __name__ == "__main__":
    main()

