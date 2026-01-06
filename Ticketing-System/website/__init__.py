from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
from sqlalchemy import text
from datetime import datetime


db = SQLAlchemy()
BASE_DIR = path.dirname(path.abspath(__file__))
DB_PATH = path.join(BASE_DIR, "database.db")
DB_URI = 'sqlite:///' + DB_PATH.replace('\\', '/')


def server_local_format(value=None, fmt='%d-%m-%Y %I:%M %p'):
    """Format a datetime value in server local time; fallback to now() if None.
    - If value is a datetime: convert to local tz if aware; leave naive as local.
    - If value is a string: best-effort parse ISO-like and format.
    - If value is None: use current time.
    - Backward-compat: if a single string with '%' is passed, treat it as fmt.
    """
    # Backward-compat mode: server_local_format('%d-%m-%Y %I:%M %p')
    if isinstance(value, str) and '%' in value and fmt == '%d-%m-%Y %I:%M %p':
        fmt = value
        value = None

    dt = None
    if value is None:
        dt = datetime.now()
    else:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                # Handle common ISO strings including those ending in 'Z'
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except Exception:
                # Fallback: ignore parsing failure and show the raw string
                return value
        else:
            # Unknown type: show raw value
            return str(value)

    try:
        # Convert aware datetimes to local time; leave naive as-is (treated as local)
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.astimezone()
    except Exception:
        pass

    return dt.strftime(fmt)


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'qwerty'
    app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    from .views import views
    from .auth import auth

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    # Ensure all models are imported for create_all() to work
    from website.models import (
        User, Ticket, Notification, TicketAssignment
    )

    create_database(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    # Register custom Jinja filters and globals
    app.jinja_env.filters['server_local_format'] = server_local_format
    app.add_template_filter(server_local_format, 'server_local_format')
    # Expose as a callable in templates (so you can use {{ server_local_format() }})
    app.jinja_env.globals['server_local_format'] = server_local_format
    app.add_template_global(server_local_format, name='server_local_format')

    return app


def create_database(app):
    # Always ensure tables exist and run lightweight migrations for existing databases.
    with app.app_context():
        # Ensure models are imported before create_all (done in create_app)
        db.create_all()
        try:
            # Verify critical tables exist; if not, attempt create_all again
            res = db.session.execute(text('PRAGMA table_info("user")')).mappings().all()
            if not res:
                print('[DB] user table missing after create_all; attempting re-create...')
                db.create_all()
        except Exception as e:
            print(f'[DB] Verification check failed: {e}')
        try:
            migrate_schema()
        except Exception as e:
            # Non-fatal: continue starting the app even if migration check fails
            print(f'DB migration skipped: {e}')


def migrate_schema():
    """Lightweight, SQLite-safe migrations to keep the existing DB in sync with models.
    Only adds missing nullable or defaulted columns and relies on create_all() for new tables.
    """
    engine = db.engine
    with engine.begin() as conn:
        # Ensure User table has new columns
        user_cols = [row['name'] for row in conn.execute(text('PRAGMA table_info("user")')).mappings()]
        if 'employee_id' not in user_cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN employee_id VARCHAR(50)'))
        if 'admin_code' not in user_cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN admin_code VARCHAR(10)'))
        if 'admin_role' not in user_cols:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN admin_role VARCHAR(50)'))
        if 'last_name' not in user_cols:
            conn.execute(text("ALTER TABLE \"user\" ADD COLUMN last_name VARCHAR(150) DEFAULT ''"))

        # Ensure Ticket table has the optimistic locking column
        ticket_cols = [row['name'] for row in conn.execute(text('PRAGMA table_info("ticket")')).mappings()]
        if 'version' not in ticket_cols:
            conn.execute(text('ALTER TABLE "ticket" ADD COLUMN version INTEGER DEFAULT 1 NOT NULL'))
        if 'date' not in ticket_cols:
            conn.execute(text('ALTER TABLE "ticket" ADD COLUMN date TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
        if 'priority' not in ticket_cols:
            conn.execute(text('ALTER TABLE "ticket" ADD COLUMN priority VARCHAR(50)'))

        # Ensure TicketAssignment table has the new eta column
        assign_cols = [row['name'] for row in conn.execute(text('PRAGMA table_info("ticket_assignments")')).mappings()]
        if 'eta' not in assign_cols:
            conn.execute(text('ALTER TABLE "ticket_assignments" ADD COLUMN eta VARCHAR(50)'))
        if 'closed_date' not in assign_cols: # This was the issue. The type was missing.
            conn.execute(text('ALTER TABLE "ticket_assignments" ADD COLUMN closed_date TIMESTAMP'))
