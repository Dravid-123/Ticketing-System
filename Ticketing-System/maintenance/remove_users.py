"""
Maintenance Script: Remove specific users and all their related data

Usage:
  1) Optional: Back up your DB file first (website/database.db)
  2) Dry-run (default):
       python maintenance/remove_users.py
  3) Execute deletion:
       python maintenance/remove_users.py --execute

Behavior:
  - Finds users by name as specified in TARGETS below
  - Deletes, in FK-safe order, for each matched user:
      TicketAssignment (assigned_to == user)
      TicketAssignment (for tickets created by user)
      Notifications (user_id == user)
      Tickets (created by user)
      User record
  - Prints a summary of matches and deleted row counts

Safety:
  - Default is dry-run (no DB changes) unless --execute is provided
  - Works under app context using SQLAlchemy models

"""

import sys
import os
from typing import List, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from website import create_app, db
    from website.models import User, Ticket, Notification, TicketAssignment
    from sqlalchemy import or_, func
except Exception as e:
    print(f"[ERROR] Unable to import app/models: {e}")
    sys.exit(1)

# Targets to delete
# - ('Ravi', 'Swamy') => match first_name == Ravi AND last_name == Swamy (case-insensitive)
# - ('Pandurang', None) => match first_name == Pandurang AND last_name is NULL or empty/whitespace
TARGETS: List[Tuple[str, str | None]] = [
    ("Ravi", "Swamy"),
    ("Pandurang", None),
]


def _normalize(s: str | None) -> str:
    return (s or "").strip()


def find_target_users() -> List[User]:
    """Find users matching TARGETS (case-insensitive), deduplicated by id."""
    found: List[User] = []
    seen: set[int] = set()

    for first, last in TARGETS:
        q = User.query.filter(func.lower(func.trim(User.first_name)) == first.lower())
        if last is None:
            # last name empty/NULL
            q = q.filter(or_(User.last_name.is_(None), func.trim(User.last_name) == ""))
        else:
            q = q.filter(func.lower(func.trim(User.last_name)) == last.lower())
        for u in q.all():
            if u.id not in seen:
                seen.add(u.id)
                found.append(u)
    return found


def dry_run_report(users: List[User]) -> None:
    print("[DRY-RUN] The following users would be deleted (no DB changes made):")
    if not users:
        print("  - None found matching the criteria")
        return
    for u in users:
        print(
            f"  - id={u.id} name='{_normalize(u.first_name)} {_normalize(u.last_name)}' "
            f"employee_id='{_normalize(u.employee_id)}' email='{_normalize(u.email)}'"
        )
        # Show related counts for clarity
        assigned_to_me = db.session.query(TicketAssignment).filter(TicketAssignment.assigned_to == u.id).count()
        my_ticket_ids = [t.id for t in Ticket.query.filter(Ticket.user_id == u.id).all()]
        for_my_tickets = 0
        if my_ticket_ids:
            for_my_tickets = db.session.query(TicketAssignment).filter(TicketAssignment.ticket_id.in_(my_ticket_ids)).count()
        notif_cnt = db.session.query(Notification).filter(Notification.user_id == u.id).count()
        ticket_cnt = len(my_ticket_ids)
        print(
            f"    TicketAssignments(assigned_to_me)={assigned_to_me}, "
            f"TicketAssignments(for_my_tickets)={for_my_tickets}, Notifications={notif_cnt}, Tickets={ticket_cnt}"
        )


def execute_delete(users: List[User]) -> None:
    if not users:
        print("[INFO] No matching users found. Nothing to delete.")
        return

    total = {"assign_to": 0, "assign_for_tickets": 0, "notifications": 0, "tickets": 0, "users": 0}

    for u in users:
        print(f"[INFO] Deleting user id={u.id} name='{_normalize(u.first_name)} {_normalize(u.last_name)}'")
        # Delete assignments where this user is assignee
        del_assign_to = db.session.query(TicketAssignment).filter(TicketAssignment.assigned_to == u.id).delete(synchronize_session=False)
        total["assign_to"] += del_assign_to

        # Get user's ticket ids
        ticket_ids = [t.id for t in Ticket.query.filter(Ticket.user_id == u.id).all()]

        # Delete assignments for the user's tickets
        del_assign_for = 0
        if ticket_ids:
            del_assign_for = db.session.query(TicketAssignment).filter(TicketAssignment.ticket_id.in_(ticket_ids)).delete(synchronize_session=False)
        total["assign_for_tickets"] += del_assign_for

        # Delete notifications for the user
        del_notif = db.session.query(Notification).filter(Notification.user_id == u.id).delete(synchronize_session=False)
        total["notifications"] += del_notif

        # Delete tickets created by the user
        del_tickets = db.session.query(Ticket).filter(Ticket.user_id == u.id).delete(synchronize_session=False)
        total["tickets"] += del_tickets

        # Finally, delete the user
        del_user = db.session.query(User).filter(User.id == u.id).delete(synchronize_session=False)
        total["users"] += del_user

    # Commit once at the end
    db.session.commit()

    print("[DONE] Deletion complete. Rows deleted:")
    print(
        f"  TicketAssignments(assigned_to_user): {total['assign_to']}\n"
        f"  TicketAssignments(for_user_tickets): {total['assign_for_tickets']}\n"
        f"  Notifications: {total['notifications']}\n"
        f"  Tickets: {total['tickets']}\n"
        f"  Users: {total['users']}"
    )


def main():
    do_execute = any(arg.lower() == "--execute" for arg in sys.argv[1:])

    app = create_app()
    with app.app_context():
        users = find_target_users()
        if not do_execute:
            dry_run_report(users)
            print("\nRun with --execute to perform deletion.")
            return

        execute_delete(users)


if __name__ == "__main__":
    main()