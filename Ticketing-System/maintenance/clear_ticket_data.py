"""
Maintenance Script: Purge ALL application data (ALL tables)

Usage:
  1) Ensure the application environment is available (packages installed)
  2) Run from project root:
       python maintenance/clear_ticket_data.py [--no-reset]

Behavior:
  - Deletes all rows from ALL application tables (TicketAssignment, Notification, Ticket, User)
  - Resets SQLite autoincrement sequences for these tables by default (can skip with --no-reset)
  - Prints counts removed per table

Safety:
  - This script does NOT drop tables or schemas; it only deletes data
  - Requires the app context for correct DB bindings
  - Deletion order respects foreign key dependencies

WARNING:
  - This will remove ALL users and tickets. Use with caution.
"""

import sys
import os
from sqlalchemy import text

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from website import create_app, db
    from website.models import User, Ticket, Notification, TicketAssignment
except Exception as e:
    print(f"[ERROR] Unable to import app/models: {e}")
    sys.exit(1)


def clear_all_data(reset_sequences: bool = True) -> None:
    app = create_app()
    with app.app_context():
        try:
            # Count existing rows before deletion
            counts_before = {
                'ticket_assignments': db.session.query(TicketAssignment).count(),
                'notifications': db.session.query(Notification).count(),
                'tickets': db.session.query(Ticket).count(),
                'users': db.session.query(User).count(),
            }

            # Delete in FK-safe order: children first
            deleted = {}
            deleted['ticket_assignments'] = db.session.query(TicketAssignment).delete(synchronize_session=False)
            deleted['notifications'] = db.session.query(Notification).delete(synchronize_session=False)
            deleted['tickets'] = db.session.query(Ticket).delete(synchronize_session=False)
            deleted['users'] = db.session.query(User).delete(synchronize_session=False)
            db.session.commit()

            print("[INFO] Deleted rows:")
            for table in ('ticket_assignments', 'notifications', 'tickets', 'users'):
                print(f"  - {table}: {deleted.get(table, 0)} (was {counts_before.get(table, 0)})")

            if reset_sequences:
                try:
                    # Reset SQLite autoincrement counters so new entries start from 1 again
                    # Note: table names must match actual SQL tables
                    table_names = ['ticket_assignments', 'notification', 'ticket', 'user']
                    for name in table_names:
                        db.session.execute(text("DELETE FROM sqlite_sequence WHERE name = :name"), {"name": name})
                    db.session.commit()
                    print("[INFO] Reset SQLite autoincrement sequences for: " + ", ".join(table_names))
                except Exception as seq_err:
                    db.session.rollback()
                    print(f"[WARN] Could not reset SQLite sequences: {seq_err}")

            print("[DONE] Full data purge complete.")
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to clear data: {e}")
            sys.exit(2)


if __name__ == "__main__":
    # Allow flag --no-reset to skip sequence reset
    reset = True
    if any(arg.lower() in ("--no-reset", "--noreset") for arg in sys.argv[1:]):
        reset = False
    clear_all_data(reset_sequences=reset)
