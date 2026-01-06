from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func
from datetime import datetime

# --------------------
# Existing Models
# --------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(150), unique=True)
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))
    accountType = db.Column(db.String(50))
    admin_code = db.Column(db.String(50))
    admin_role = db.Column(db.String(150))
    
    # Add these two new columns
    security_question = db.Column(db.String(250))
    security_answer = db.Column(db.String(250)) # This will store the hashed answer

    tickets = db.relationship('Ticket', backref='creator', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)


class Ticket(db.Model):
    id = db.Column(db.String(20), primary_key=True)
    title = db.Column(db.String(150))
    desc = db.Column(db.Text)
    location = db.Column(db.String(100))
    ticket_type = db.Column(db.String(100))
    category = db.Column(db.String(50))  # 'Software' or 'Hardware'
    project = db.Column(db.String(100))
    project_manager = db.Column(db.String(100))
    cubical = db.Column(db.String(50))
    username = db.Column(db.String(150))
    status = db.Column(db.String(50))
    date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    movement_from = db.Column(db.String(255), nullable=True)
    movement_to = db.Column(db.String(255), nullable=True)
    assigned = db.Column(db.String(150))  # kept for legacy
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # Optimistic locking version field
    version = db.Column(db.Integer, default=1, nullable=False)
    priority = db.Column(db.String(50), nullable=True)
    # One-to-one relationship with TicketAssignment
    assignment = db.relationship('TicketAssignment', back_populates='ticket', uselist=False)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(200))
    status = db.Column(db.String(50))
    date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

# --------------------
# NEW MODEL: TicketAssignment
# --------------------
class TicketAssignment(db.Model):
    __tablename__ = "ticket_assignments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.String(20), db.ForeignKey('ticket.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default="Pending")
    assigned_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    closed_date = db.Column(db.DateTime(timezone=True), nullable=True)
    # Optimistic locking version field
    eta = db.Column(db.String(50))
    version = db.Column(db.Integer, default=1, nullable=False)

    # Relationship with Ticket, linked back
    ticket = db.relationship('Ticket', back_populates='assignment')

    # Relationship with User (assigned user)
    user = db.relationship('User', backref=db.backref('assigned_tickets', lazy=True))


# TicketRemark model removed as requested
