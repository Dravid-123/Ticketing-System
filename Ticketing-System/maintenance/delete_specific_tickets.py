import sys
import os
from sqlalchemy import not_, or_

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from website import create_app, db
    from website.models import Ticket, TicketAssignment
except Exception as e:
    print(f"[ERROR] Unable to import app/models: {e}")
    sys.exit(1)


def delete_specific_tickets() -> None:
    app = create_app()
    with app.app_context():
        try:
            tickets_to_delete = db.session.query(Ticket).filter(
                not_(
                    or_(
                        Ticket.id.like('it%'),
                        Ticket.id.like('hw%')
                    )
                )
            ).all()

            num_deleted = len(tickets_to_delete)

            if num_deleted:
                ticket_ids = [ticket.id for ticket in tickets_to_delete]
                db.session.query(TicketAssignment).filter(
                    TicketAssignment.ticket_id.in_(ticket_ids)
                ).delete(synchronize_session=False)

                for ticket in tickets_to_delete:
                    db.session.delete(ticket)

            db.session.commit()

            print(f"[INFO] Deleted {num_deleted} tickets that did not start with 'it' or 'hw'.")
            print("[DONE] Specific ticket deletion complete.")

        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to delete specific tickets: {e}")
            sys.exit(2)


if __name__ == "__main__":
    delete_specific_tickets()
