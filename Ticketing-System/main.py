from website import create_app, db
from website.models import TicketAssignment, Ticket
from datetime import datetime

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=443, debug=True,use_reloader=False)
