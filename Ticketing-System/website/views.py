from flask import Blueprint, render_template, request, flash, jsonify, redirect, url_for, Response
from flask import stream_with_context
from flask_login import login_required, current_user
from .models import Ticket, Notification, User, TicketAssignment
from . import db
import json
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
import threading
import queue

# Helper function to get full name
def get_full_name(user):
    if not user:
        return "Unknown"
    if user.last_name and user.last_name.strip():
        return f"{user.first_name} {user.last_name}"
    else:
        return user.first_name

# Helper: find relevant admins for a ticket based on category (Software -> IT, Hardware -> Hardware)
# Super Admin (1236) always included
def get_relevant_admins_for_ticket(ticket):
    try:
        category = (ticket.category or '').strip().lower()
        q = User.query.filter_by(accountType='admin')
        if category == 'software':
            return q.filter(User.admin_code.in_(['1234', '1236'])).all()  # IT + Super
        if category == 'hardware':
            return q.filter(User.admin_code.in_(['1235', '1236'])).all()  # Hardware + Super
        # Fallback: all admins
        return q.all()
    except Exception:
        # On any failure, return all admins to avoid missing critical notifications
        return User.query.filter_by(accountType='admin').all()

# Helper function to synchronize ticket data between main ticket table and assignment table
def sync_ticket_assignment_data():
    """
    Utility function to synchronize ticket data between Ticket and TicketAssignment tables.
    This ensures both tables have consistent status and assignment information.
    """
    try:
        assignments = TicketAssignment.query.all()
        for assignment in assignments:
            ticket = assignment.ticket
            if ticket:
                # Update ticket status and assigned user from assignment data
                ticket.status = assignment.status
                if assignment.user:
                    ticket.assigned = get_full_name(assignment.user)
                else:
                    ticket.assigned = "Unassigned"
        
        db.session.commit()
        return {"success": True, "message": f"Synchronized {len(assignments)} ticket assignments"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

views = Blueprint('views', __name__)

# -------------------
# SIMPLE IN-PROCESS EVENT BUS FOR CROSS-ROLE REFRESH
# -------------------
# Two channels: 'user_updates' (events caused by users) and 'admin_updates' (events caused by admins).
# Each subscriber gets its own queue; producers put messages on the channel.
_event_channels = {
    'user_updates': [],   # admins listen here
    'admin_updates': []   # users listen here
}
_event_lock = threading.Lock()

class _EventSubscriber:
    def __init__(self):
        self.q = queue.Queue(maxsize=100)
        self.alive = True
    def put(self, msg):
        try:
            self.q.put_nowait(msg)
        except queue.Full:
            # Drop oldest to avoid blocking
            try:
                _ = self.q.get_nowait()
            except Exception:
                pass
            try:
                self.q.put_nowait(msg)
            except Exception:
                pass
    def get(self, timeout=25):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None
    def close(self):
        self.alive = False


def _subscribe(channel_name):
    sub = _EventSubscriber()
    with _event_lock:
        _event_channels.setdefault(channel_name, []).append(sub)
    return sub


def _publish(channel_name, payload):
    with _event_lock:
        subs = list(_event_channels.get(channel_name, []))
    for s in subs:
        s.put(payload)


def _unsubscribe(channel_name, subscriber):
    with _event_lock:
        if channel_name in _event_channels and subscriber in _event_channels[channel_name]:
            _event_channels[channel_name].remove(subscriber)

# SSE endpoint for admins to listen to user-side updates, and users to listen to admin-side updates.
@views.route('/events')
@login_required
def sse_events():
    role = getattr(current_user, 'accountType', None)
    if role == 'admin':
        channel = 'user_updates'   # admins get events when users update
    else:
        channel = 'admin_updates'  # users get events when admins update

    subscriber = _subscribe(channel)

    @stream_with_context
    def event_stream():
        try:
            # Send an initial comment to establish the stream
            yield ': connected\n\n'
            while True:
                msg = subscriber.get(timeout=25)
                if msg is None:
                    # Keep-alive to prevent timeouts through proxies
                    yield ': keep-alive\n\n'
                else:
                    yield f"data: {json.dumps(msg)}\n\n"
        finally:
            _unsubscribe(channel, subscriber)
            subscriber.close()

    return Response(event_stream(), mimetype='text/event-stream')

# -------------------
# LIGHTWEIGHT CHANGE DETECTION ENDPOINT
# -------------------
@views.route('/data-version')
def data_version():
    """
    Returns a scoped "version" that changes only when data relevant to the
    current user/view is updated. This prevents unnecessary page reloads.
    - For regular users: watches their own tickets and related assignments, plus their notifications.
    - For admins: watches tickets they can see (by admin_code rules) and related assignments, plus their notifications.
    """
    try:
        from flask_login import current_user

        # Base queries
        ticket_q = db.session.query(func.coalesce(func.max(Ticket.id), 0))
        assign_q = (
            db.session.query(func.coalesce(func.max(TicketAssignment.id), 0))
            .join(Ticket, TicketAssignment.ticket_id == Ticket.id)
        )
        # Only notifications for the current user (not global), to avoid noise
        notif_q = db.session.query(func.coalesce(func.max(Notification.id), 0)).filter(
            Notification.user_id == getattr(current_user, 'id', None)
        )

        # Scope by role
        is_admin = getattr(current_user, 'accountType', None) == 'admin'
        if is_admin:
            admin_code = getattr(current_user, 'admin_code', None)
            if admin_code == '1236':
                # Super admin: all tickets visible
                pass  # no extra filter
            elif admin_code == '1235':  # Hardware
                allowed_types = [
                    'Printer Request', 'Cartridge Request', 'Printer Issue',
                    'Paper Request', 'Printer Movement Request', 'Printer Movement to Wireless Lab'
                ]
                ticket_q = ticket_q.filter(Ticket.ticket_type.in_(allowed_types))
                assign_q = assign_q.filter(Ticket.ticket_type.in_(allowed_types))
            elif admin_code == '1234':  # IT
                allowed_types = [
                    'Laptop', 'Desktop', 'Workstation', 'OS installation',
                    'Network issues', 'Private network', 'New setup',
                    'Server Issue', 'Lan Ports Not working', 'Adding users into Domain',
                    'Port Request', 'Fax Port Issue', 'VOIP'
                ]
                ticket_q = ticket_q.filter(Ticket.ticket_type.in_(allowed_types))
                assign_q = assign_q.filter(Ticket.ticket_type.in_(allowed_types))
            else:
                # Unknown admin scope -> return a stable version to avoid constant reloads
                version = "unauth-0"
                return jsonify({"version": version})
        else:
            # Regular user: only their tickets
            user_id = getattr(current_user, 'id', None)
            ticket_q = ticket_q.filter(Ticket.user_id == user_id)
            assign_q = assign_q.filter(Ticket.user_id == user_id)

        # Also include "own" events from the opposite side via SSE: do nothing here

        ticket_max_id = ticket_q.scalar() or 0
        assign_max_id = assign_q.scalar() or 0
        notif_max_id = notif_q.scalar() or 0

        version = f"t{ticket_max_id}-a{assign_max_id}-n{notif_max_id}"
        return jsonify({"version": version})
    except Exception as e:
        # Return a stable version with error info to avoid thrashing reloads
        return jsonify({"version": "0", "error": str(e)}), 200

# -------------------
# USER ROUTES
# -------------------

@views.route('/admin/export-excel', methods=['GET'])
@login_required
def export_admin_excel():
    """Export all admin-visible tickets to an Excel-compatible .xls (HTML) file
    with two stacked tables: Tickets, then Ticket Assignments.
    Ignores pagination and uses admin_code scoping.
    """
    try:
        if getattr(current_user, 'accountType', None) != 'admin':
            return jsonify({'success': False, 'error': 'Forbidden'}), 403

        # Scope tickets by admin_code, consistent with other views
        admin_code = getattr(current_user, 'admin_code', None)
        q = db.session.query(Ticket).options(
            joinedload(Ticket.creator),
            joinedload(Ticket.assignment).joinedload(TicketAssignment.user)
        ).outerjoin(TicketAssignment, TicketAssignment.ticket_id == Ticket.id)
        if admin_code == '1236':
            pass  # Super admin: all tickets
        elif admin_code == '1235':  # Hardware
            allowed_types = [
                'Printer Request', 'Cartridge Request', 'Printer Issue',
                'Paper Request', 'Printer Movement Request', 'Printer Movement to Wireless Lab'
            ]
            q = q.filter(db.or_(
                Ticket.ticket_type.in_(allowed_types),
                db.and_(Ticket.ticket_type == 'Others', Ticket.category == 'Hardware')
            ))
        elif admin_code == '1234':  # IT
            allowed_types = [
                'Laptop', 'Desktop', 'Workstation', 'OS installation',
                'Network issues', 'Private network', 'New setup',
                'Server Issue', 'Lan Ports Not working', 'Adding users into Domain',
                'Port Request', 'Fax Port Issue', 'VOIP'
            ]
            q = q.filter(db.or_(
                Ticket.ticket_type.in_(allowed_types),
                db.and_(Ticket.ticket_type == 'Others', Ticket.category == 'Software')
            ))
        else:
            # Unknown or missing admin scope => no data
            q = q.filter(False)

        tickets = q.all()

        from html import escape
        def fmt_dt(dt):
            try:
                if not dt:
                    return ''
                if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
                    dt = dt.astimezone()
                return dt.strftime('%d-%m-%Y %H:%M')
            except Exception:
                return str(dt) if dt is not None else ''

        # Build HTML content for Excel
        html_parts = []
        html_parts.append('<html><head><meta charset="utf-8"></head><body>')

        # 1) Tickets table (same columns as admin table, except actions)
        html_parts.append('<table border="1">')
        headers = [
            'Ticket ID', 'Title', 'Description', 'Created by', 'Created on',
            'Project', 'Project Manager', 'Location', 'Cubical', 'Request Type',
            'Category', 'Assigned to', 'Assigned Time', 'Status', 'Comment'
        ]
        html_parts.append('<tr>' + ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr>')

        for t in tickets:
            assignment = getattr(t, 'assignment', None)
            if t.creator:
                created_by = f"{t.creator.first_name} {t.creator.last_name or ''}".strip()
            else:
                created_by = t.username or ''
            assigned_to_name = ''
            assigned_time = ''
            status = t.status or ''
            comment = ''
            if assignment:
                if assignment.user:
                    assigned_to_name = f"{assignment.user.first_name} {assignment.user.last_name or ''}".strip()
                assigned_time = fmt_dt(assignment.assigned_date)
                status = assignment.status or status
                comment = assignment.comment or ''

            row = [
                str(t.id or ''),
                t.title or '',
                t.desc or '',
                created_by,
                fmt_dt(t.date),
                t.project or '',
                t.project_manager or '',
                t.location or '',
                t.cubical or '',
                t.ticket_type or '',
                t.category or '',
                assigned_to_name or 'Unassigned',
                assigned_time,
                status or '',
                comment
            ]
            html_parts.append('<tr>' + ''.join(f'<td>{escape(v)}</td>' for v in row) + '</tr>')

        html_parts.append('</table>')
        html_parts.append('</body></html>')

        content = ''.join(html_parts)
        filename = f"admin_tickets_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xls"
        return Response(content, headers={
            'Content-Type': 'application/vnd.ms-excel; charset=utf-8',
            'Content-Disposition': f'attachment; filename={filename}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@views.route('/')
def home():
    try:
        if current_user.is_authenticated and current_user.accountType == "admin":
            return redirect(url_for('views.adminDashboard'))
    except Exception as e:
        print(e)

    return render_template('home.html', user=current_user)


@views.route('/stats')
def stats():
    """Lightweight stats for homepage impact counters."""
    try:
        # Total tickets resolved (Closed or Solved) - consider either Ticket.status or assignment.status
        total_resolved = (
            db.session.query(func.count(Ticket.id))
            .outerjoin(TicketAssignment, TicketAssignment.ticket_id == Ticket.id)
            .filter(
                or_(
                    func.lower(func.trim(Ticket.status)).in_(['closed', 'solved']),
                    func.lower(func.trim(TicketAssignment.status)).in_(['closed', 'solved'])
                )
            )
            .scalar()
            or 0
        )

        # Average resolution time in hours (best-effort):
        # Use time from ticket creation to assignment date for tickets marked Closed/Solved
        pairs = (
            db.session.query(Ticket.date, TicketAssignment.assigned_date)
            .join(TicketAssignment, TicketAssignment.ticket_id == Ticket.id)
            .filter(
                func.lower(func.trim(Ticket.status)).in_(['closed', 'solved'])
            )
            .all()
        )
        diffs = []
        for created_at, assigned_at in pairs:
            if created_at and assigned_at:
                try:
                    diffs.append((assigned_at - created_at).total_seconds() / 3600.0)
                except Exception:
                    pass
        avg_hours = round(sum(diffs) / len(diffs), 1) if diffs else 0.0

        # Active admins count
        active_admins = db.session.query(
            db.func.count()
        ).select_from(User).filter(User.accountType == 'admin').scalar() or 0

        return jsonify({
            'success': True,
            'total_resolved': int(total_resolved or 0),
            'avg_resolution_hours': float(avg_hours),
            'active_admins': int(active_admins)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'total_resolved': 0, 'avg_resolution_hours': 0.0, 'active_admins': 0})


# -------------------
# REPORTS (SUPER ADMIN ONLY) + API endpoints for Chart.js
# -------------------
def _period_range(period):
    """Return (start, end) datetimes for a given period string."""
    now = datetime.now()
    today = datetime(now.year, now.month, now.day)
    if period == 'daily':
        start = today
        end = now
    elif period == 'weekly':
        start = today - timedelta(days=7)
        end = now
    elif period == 'monthly':
        start = today - timedelta(days=30)
        end = now
    elif period == 'yearly':
        start = today - timedelta(days=365)
        end = now
    elif period == 'all':
        # For 'all', we don't need a specific start/end, but return non-None to avoid errors
        start = datetime.min
        end = now
    else: # Default to monthly if period is unknown
        start = today - timedelta(days=30)
        end = now
    return start, end


def _get_kpi_data(period='all', admin_type='all', admin_id='all'):
    """
    Internal helper to fetch KPI data based on a time period.
    This is not a web endpoint.
    All KPI calculations are based on the 'Ticket' table status.
    """
    admin_type = (admin_type or 'all').lower()
    admin_id = admin_id or 'all'

    start, end = _period_range(period)

    try:
        # Base query for tickets
        q = db.session.query(
            func.lower(func.trim(Ticket.status)).label('status'),
            func.count(Ticket.id).label('count')
        )

        # Apply period filter
        if period != 'all':
            q = q.filter(Ticket.date.between(start, end))

        # Apply admin filters if provided
        if admin_type != 'all' or (admin_id and admin_id != 'all'):
            q = q.outerjoin(TicketAssignment, Ticket.id == TicketAssignment.ticket_id).outerjoin(User, TicketAssignment.assigned_to == User.id)
            if admin_type == 'it':
                q = q.filter(User.admin_code == '1234')
            elif admin_type == 'hardware':
                q = q.filter(User.admin_code == '1235')
            if admin_id and admin_id != 'all':
                q = q.filter(User.id == int(admin_id))

        # Group by status to get counts
        results = q.group_by(Ticket.status).all()

        # --- KPI Calculations ---
        kpis = {
            'total_created': 0,
            'solved_closed': 0,
            'in_progress': 0,
            'pending': 0
        }

        for row in results:
            status = row.status
            count = row.count
            kpis['total_created'] += count
            if status in ['closed', 'solved']:
                kpis['solved_closed'] += count
            elif status == 'in progress':
                kpis['in_progress'] += count
            elif status == 'pending':
                kpis['pending'] += count

        return {
            'success': True,
            'total_created': int(kpis['total_created']),
            'solved_closed': int(kpis['solved_closed']),
            'in_progress': int(kpis['in_progress']),
            'pending': int(kpis['pending'])
        }
    except Exception as e:
        print(f"Error in _get_kpi_data: {e}")
        return {'success': False, 'error': str(e)}


@views.route('/reports')
@login_required
def admin_reports():
    # Only Super Admin (admin_code == '1236') may view reports
    if getattr(current_user, 'accountType', None) != 'admin' or getattr(current_user, 'admin_code', None) != '1236':
        return redirect(url_for('views.adminDashboard'))

    # provide list of admins for the filter dropdown
    admins = User.query.filter_by(accountType='admin').all()
    return render_template(
        'reports.html', 
        user=current_user, 
        admins=admins,
        export_url=url_for('views.export_admin_excel')
    )


@views.route('/api/report-kpis')
@login_required
def api_report_kpis():
    # Super admin only
    if getattr(current_user, 'accountType', None) != 'admin' or getattr(current_user, 'admin_code', None) != '1236':
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    period = request.args.get('period', 'all')
    admin_type = request.args.get('admin_type', 'all')
    admin_id = request.args.get('admin_id', 'all')
    data = _get_kpi_data(period, admin_type, admin_id)
    return jsonify(data)

@views.route('/api/daily-status-chart')
@login_required
def api_daily_status_chart():
    # Super admin only
    if getattr(current_user, 'accountType', None) != 'admin' or getattr(current_user, 'admin_code', None) != '1236':
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    # Filters
    period = request.args.get('period', 'monthly') # Default to monthly
    admin_type = (request.args.get('admin_type') or 'all').lower()
    admin_id = request.args.get('admin_id', 'all')
    start, end = _period_range(period)
    days = (end.date() - start.date()).days + 1

    # prepare labels
    labels = []
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        labels.append(d.strftime('%Y-%m-%d'))

    # Build base query: group by ticket creation date and status
    q = db.session.query(func.date(Ticket.date).label('day'), Ticket.status, func.count(Ticket.id))
    q = q.filter(Ticket.date >= start, Ticket.date <= end)

    # Apply admin filters by joining assigned user when necessary
    if admin_type != 'all' or (admin_id and admin_id != 'all'):
        q = q.outerjoin(TicketAssignment, Ticket.id == TicketAssignment.ticket_id).outerjoin(User, TicketAssignment.assigned_to == User.id)
        if admin_type == 'it':
            q = q.filter(User.admin_code == '1234')
        elif admin_type == 'hardware':
            q = q.filter(User.admin_code == '1235')
        # admin_id filter
        if admin_id and admin_id != 'all':
            try:
                aid = int(admin_id)
                q = q.filter(User.id == aid)
            except Exception:
                pass

    q = q.group_by(func.date(Ticket.date), Ticket.status)
    rows = q.all()

    # Normalize statuses and build a map: day -> status -> count
    status_map = {}
    for day_label in labels:
        status_map[day_label] = {'Pending': 0, 'In Progress': 0, 'Solved': 0}

    def norm_status(s):
        if not s:
            return 'Pending'
        s = (s or '').strip().lower()
        if 'progress' in s:
            return 'In Progress'
        if s in ('closed', 'solved'):
            return 'Solved'
        if 'pending' in s or s == 'pending':
            return 'Pending'
        return s.title()

    for day, status, count in rows:
        try:
            day_key = day
            if isinstance(day_key, datetime):
                day_key = day_key.date().strftime('%Y-%m-%d')
            status_n = norm_status(status)
            if day_key in status_map:
                if status_n not in status_map[day_key]:
                    status_map[day_key][status_n] = 0
                status_map[day_key][status_n] += int(count or 0)
        except Exception:
            continue

    # Build datasets in order Pending, In Progress, Solved
    pending_data = [status_map[d]['Pending'] for d in labels]
    progress_data = [status_map[d]['In Progress'] for d in labels]
    solved_data = [status_map[d]['Solved'] for d in labels]

    datasets = [
        {'label': 'Pending', 'data': pending_data, 'backgroundColor': 'rgba(255, 193, 7, 0.8)'},
        {'label': 'In Progress', 'data': progress_data, 'backgroundColor': 'rgba(23, 162, 184, 0.8)'},
        {'label': 'Solved/Closed', 'data': solved_data, 'backgroundColor': 'rgba(40, 167, 69, 0.8)'}
    ]

    return jsonify({'success': True, 'labels': labels, 'datasets': datasets})


@views.route('/api/category-distribution-chart')
@login_required
def api_category_distribution_chart():
    # Super admin only
    if getattr(current_user, 'accountType', None) != 'admin' or getattr(current_user, 'admin_code', None) != '1236':
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    period = request.args.get('period', 'daily')
    start, end = _period_range(period)

    try:
        rows = (
            db.session.query(Ticket.category, func.count(Ticket.id))
            .filter(Ticket.date >= start, Ticket.date <= end)
            .group_by(Ticket.category)
            .all()
        )

        labels = []
        data = []
        for cat, cnt in rows:
            labels.append(cat or 'Unknown')
            data.append(int(cnt or 0))

        return jsonify({'success': True, 'labels': labels, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@views.route('/api/status-distribution-chart')
@login_required
def api_status_distribution_chart():
    # Super admin only
    if getattr(current_user, 'accountType', None) != 'admin' or getattr(current_user, 'admin_code', None) != '1236':
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    period = request.args.get('period', 'all')
    admin_type = request.args.get('admin_type', 'all')
    admin_id = request.args.get('admin_id', 'all')
    
    try:
        kpi_data = _get_kpi_data(period, admin_type, admin_id)
        if not kpi_data or not kpi_data.get('success'):
            return jsonify({'success': False, 'error': 'Failed to get KPI data for chart'}), 500

        labels = ['Pending', 'In Progress', 'Solved/Closed']
        data = [
            kpi_data.get('pending', 0),
            kpi_data.get('in_progress', 0),
            kpi_data.get('solved_closed', 0)
        ]
        return jsonify({'success': True, 'labels': labels, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Helper function to generate the next ticket ID based on category
def generate_next_ticket_id(category):
    """Generates the next ticket ID like IT001 or HW001."""
    prefix = ''
    if category and category.lower() == 'software':
        prefix = 'IT'
    elif category and category.lower() == 'hardware':
        prefix = 'HW'
    else:
        # Fallback for other categories if any
        prefix = 'GEN'

    # Find the last ticket with the same prefix
    last_ticket = Ticket.query.filter(Ticket.id.like(f'{prefix}%')).order_by(Ticket.id.desc()).first()

    if last_ticket:
        # Extract number and increment
        last_num_str = last_ticket.id.replace(prefix, '')
        next_num = int(last_num_str) + 1
    else:
        # First ticket of this type
        next_num = 1

    return f'{prefix}{next_num:03d}'

@views.route('/support', methods=['GET', 'POST'])
@login_required
def support():
    if request.method == 'POST':
        title = request.form.get('ticket_title')
        desc = request.form.get('desc')
        location = request.form.get('location')
        ticket_type = request.form.get('ticket_type')
        category = request.form.get('category')  # Get the software/hardware category
        project = request.form.get('project')
        project_manager = request.form.get('project_manager')
        cubical = request.form.get('cubical')
        priority = request.form.get('priority', 'Medium')
        # Get the new movement fields
        movement_from = request.form.get('movement_from')
        movement_to = request.form.get('movement_to')

        if not title or not desc or not location or not ticket_type or not category:
            flash("Please fill in all required fields including category selection", category='error')
            return redirect(url_for('views.support'))

        # Generate the custom ticket ID
        ticket_id = generate_next_ticket_id(category)

        new_ticket = Ticket(
            id=ticket_id,  # Set the custom ID
            title=title, 
            desc=desc,
            location=location,
            ticket_type=ticket_type,
            category=category.capitalize() if category else None,  # Store as "Software" or "Hardware"
            project=project,
            project_manager=project_manager,
            cubical=cubical,
            movement_from=movement_from if ticket_type == 'Printer Movement Request' else None,
            movement_to=movement_to if ticket_type == 'Printer Movement Request' else None,
            priority=priority,
            username=current_user.first_name,
            status="Pending",
            user_id=current_user.id
        )
        db.session.add(new_ticket)

        flash("Ticket Opened! We'll contact you soon.", category='success')

        new_notification = Notification(
            message="New Ticket Created!", status="success", user_id=current_user.id)
        db.session.add(new_notification)

        # Notify relevant admins (by ticket category) about the new ticket
        try:
            relevant_admins = get_relevant_admins_for_ticket(new_ticket)
            admin_notes = []
            for admin in relevant_admins:
                admin_notes.append(Notification(
                    message=f"New {new_ticket.category or ''} Ticket #{new_ticket.id}: {title}",
                    status="info",
                    user_id=admin.id
                ))
            if admin_notes:
                db.session.add_all(admin_notes)
            db.session.commit()
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to create admin notifications for new ticket: {e}")

        # Publish user-side update so admins refresh
        try:
            _publish('user_updates', {"type": "ticket_created", "ticket_id": new_ticket.id})
        except Exception:
            pass

        # Send email notification to relevant admins
        try:
            from .alerting import send_ticket_created_notification
            admins = User.query.filter_by(accountType="admin").all()
            send_ticket_created_notification(new_ticket, admins)
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send ticket creation notification: {e}")

        return redirect(url_for('views.tickets'))

    return render_template('support.html', user=current_user)


@views.route('/user-delete-ticket/<string:ticket_id>', methods=['POST'])
@login_required
def user_delete_ticket(ticket_id):
    """User soft-deletes their own ticket: set status Closed with concurrency protection."""
    ticket = Ticket.query.get(ticket_id)
    if not ticket or ticket.user_id != current_user.id:
        return redirect(url_for('views.tickets'))
    
    try:
        # Directly set status to Closed and append a closure comment
        old_status = ticket.status
        ticket.status = 'Closed'
        # Ensure assignment exists for comment history
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()

        # Set closure time
        closure_time = datetime.now().astimezone()

        if not assignment:
            assignment = TicketAssignment(ticket_id=ticket_id, status=ticket.status, closed_date=closure_time)
            db.session.add(assignment)
        # Append user closure marker
        user_name = get_full_name(current_user)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        existing_comment = assignment.comment or ''
        closure_text = f"--- {user_name} ({timestamp}) ---\nClosed by user"
        assignment.comment = (existing_comment + ("\n\n" if existing_comment.strip() else "") + closure_text)
        assignment.status = ticket.status 
        assignment.closed_date = closure_time # Store closure time
        
        from flask import flash
        flash('Ticket deleted from your view (closed).', 'success')

        # Notify assigned admin or relevant admin group that user closed their ticket
        try:
            assigned = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
            user_name = get_full_name(current_user)
            if assigned and assigned.user:
                note = Notification(
                    message=f"Ticket #{ticket_id} closed by user {user_name}",
                    status="warning",
                    user_id=assigned.user.id
                )
                db.session.add(note)
            else:
                for admin in get_relevant_admins_for_ticket(ticket):
                    note = Notification(
                        message=f"Ticket #{ticket_id} closed by user {user_name}",
                        status="warning",
                        user_id=admin.id
                    )
                    db.session.add(note)
            db.session.commit()
            # Publish user-side update so admins refresh
            try:
                _publish('user_updates', {"type": "ticket_closed_by_user", "ticket_id": ticket_id})
            except Exception:
                pass
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to notify admins about user ticket closure: {e}")
        
    except Exception as e:
        from flask import flash
        flash(f'Error closing ticket: {e}', 'error')
    
    return redirect(url_for('views.tickets'))


@views.route('/admin-delete-ticket/<string:ticket_id>', methods=['POST'])
@login_required
def admin_delete_ticket(ticket_id):
    """Admin hard-delete a ticket (and its assignment) with concurrency protection."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if getattr(current_user, 'accountType', None) != 'admin':
        if is_ajax: return jsonify({"success": False, "error": "Forbidden"}), 403
        return redirect(url_for('views.home'))
    
    try:
        # Get ticket with version for concurrency check
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            if is_ajax: return jsonify({"success": False, "error": "Ticket not found"}), 404
            from flask import flash
            flash('Ticket not found.', 'error')
            return redirect(url_for('views.adminDashboard'))
        
        # Store ticket info for logging
        ticket_title = ticket.title
        ticket_version = ticket.version
        
        # Delete with optimistic locking check
        # Delete assignment first if exists
        if ticket.assignment:
            assignment_version = ticket.assignment.version
            db.session.delete(ticket.assignment)
        
        # Delete notifications related to this ticket
        Notification.query.filter_by(user_id=ticket.user_id).filter(
            Notification.message.contains(f'Ticket #{ticket_id}')
        ).delete(synchronize_session=False)
        
        # Delete the ticket itself
        db.session.delete(ticket)
        db.session.commit()
        
        admin_name = get_full_name(current_user)
        print(f"[TICKET DELETE] Ticket #{ticket_id} '{ticket_title}' permanently deleted by admin {admin_name}")
        
        from flask import flash
        flash(f'Ticket "{ticket_title}" deleted permanently.', 'success')
        if is_ajax: return jsonify({"success": True, "message": "Ticket deleted."})
        
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Error deleting ticket: {e}', 'error')
        if is_ajax: return jsonify({"success": False, "error": str(e)}), 500
    
    return redirect(url_for('views.adminDashboard'))




@views.route('/tickets')
@login_required
def tickets():
    # User dashboard with pagination (10 per page)
    page = request.args.get('page', default=1, type=int)
    per_page = 10
    search_query = request.args.get('q', default='', type=str)

    # Define custom sort order for status
    from sqlalchemy import case
    status_order = case(
        (Ticket.status == 'Pending', 1),
        (Ticket.status == 'In Progress', 2),
        (Ticket.status == 'Closed', 3),
        (Ticket.status == 'Solved', 4),
        else_=5
    )

    base_q = (
        Ticket.query
        .options(
            joinedload(Ticket.creator),
            joinedload(Ticket.assignment).joinedload(TicketAssignment.user)
        )
        .filter(Ticket.user_id == current_user.id)
        .order_by(status_order, Ticket.date.desc())
    )

    if search_query:
        search_term = f"%{search_query}%"
        base_q = base_q.filter(
            or_(
                Ticket.id.ilike(search_term),
                Ticket.title.ilike(search_term),
                Ticket.desc.ilike(search_term),
                Ticket.project.ilike(search_term),
                Ticket.location.ilike(search_term),
                Ticket.status.ilike(search_term)
            )
        )

    total = base_q.count()
    open_tickets = base_q.offset((page - 1) * per_page).limit(per_page).all()

    notifications = Notification.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'tickets.html',
        user=current_user,
        notifications=notifications,
        open_tickets=open_tickets,
        page=page,
        per_page=per_page,
        total=total,
        pages=(total + per_page - 1) // per_page,
        search_query=search_query
    )


@views.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)


# -------------------
# ADMIN ROUTES
# -------------------
@views.route('/admin-dashboard')
@login_required
def adminDashboard():
    # Only admins can view dashboard
    if getattr(current_user, 'accountType', None) != 'admin':
        return redirect(url_for('views.home'))

    # Pagination parameters
    page = request.args.get('page', default=1, type=int)
    per_page = 10
    search_query = request.args.get('q', default='', type=str)

    # Filter tickets by admin role based on admin_code
    from sqlalchemy import case
    admin_code = getattr(current_user, 'admin_code', None)
    base_q = Ticket.query.options(
        joinedload(Ticket.creator),
        joinedload(Ticket.assignment).joinedload(TicketAssignment.user)
    )

    # Define custom sort order for status
    status_order = case(
        (Ticket.status == 'Pending', 1),
        (Ticket.status == 'In Progress', 2),
        (Ticket.status == 'Closed', 3),
        (Ticket.status == 'Solved', 4),
        else_=5
    )

    if admin_code == '1236':  # Super Admin: access all tickets
        base_q = base_q.order_by(status_order, Ticket.date.desc())
    elif admin_code == '1235':  # Hardware Admin
        allowed_types = [
            'Printer Request', 'Cartridge Request', 'Printer Issue',
            'Paper Request', 'Printer Movement Request', 'Printer Movement to Wireless Lab'
        ]
        base_q = base_q.filter(db.or_(
            Ticket.ticket_type.in_(allowed_types),
            db.and_(Ticket.ticket_type == 'Others', Ticket.category == 'Hardware')
        )).order_by(status_order, Ticket.date.desc())
    elif admin_code == '1234':  # IT Admin
        allowed_types = [
            'Laptop', 'Desktop', 'Workstation', 'OS installation',
            'Network issues', 'Private network', 'New setup',
            'Server Issue', 'Lan Ports Not working', 'Adding users into Domain',
            'Port Request', 'Fax Port Issue', 'VOIP'
        ]
        base_q = base_q.filter(db.or_(
            Ticket.ticket_type.in_(allowed_types),
            db.and_(Ticket.ticket_type == 'Others', Ticket.category == 'Software')
        )).order_by(status_order, Ticket.date.desc())
    else:
        # Fallback: no access if code invalid
        flash_msg = "Invalid or missing admin code."
        try:
            from flask import flash
            flash(flash_msg, 'error')
        except Exception:
            pass
        return redirect(url_for('auth.login'))

    if search_query:
        search_term = f"%{search_query}%"
        base_q = base_q.join(User, Ticket.user_id == User.id, isouter=True).filter(
            or_(
                Ticket.id.ilike(search_term),
                Ticket.title.ilike(search_term),
                Ticket.desc.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term),
                Ticket.project.ilike(search_term),
                Ticket.location.ilike(search_term),
                Ticket.status.ilike(search_term)
            )
        )

    total = base_q.count()
    allTicket = base_q.offset((page - 1) * per_page).limit(per_page).all()

    support_users = User.query.filter_by(accountType="admin").all()  # Only admins
    notifications = Notification.query.filter_by(user_id=current_user.id).all()  # Or filter as needed
    return render_template(
        'admin_dashboard.html', 
        user=current_user, 
        allTicket=allTicket, 
        support_users=support_users, 
        notifications=notifications,
        page=page,
        per_page=per_page,
        total=total,
        pages=(total + per_page - 1) // per_page,
        search_query=search_query
    )

@views.route('/user-management')
@login_required
def userManagement():
    # Show all users to any admin (Super, IT, Hardware). Regular users see only themselves.
    if getattr(current_user, 'accountType', None) == 'admin':
        allUsers = User.query.all()
    else:
        allUsers = [current_user]
    return render_template('user_management.html', user=current_user, allUsers=allUsers)


# -------------------
# USER MANAGEMENT ROUTES
# -------------------
@views.route('/add-user', methods=['POST'])
@login_required
def add_user():
    """Add a new user"""
    if getattr(current_user, 'accountType', None) != 'admin':
        return jsonify({"success": False, "error": "Admin access required"}), 403
    
    try:
        # Get form data
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        account_type = request.form.get('account_type', 'user')
        admin_code = request.form.get('admin_code', '').strip()
        admin_role = request.form.get('admin_role', '').strip()
        
        # Validation
        if not first_name or not email or not password:
            return jsonify({"success": False, "error": "First name, email, and password are required"}), 400
        
        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({"success": False, "error": "Email already registered"}), 400
        
        # Password hashing
        from werkzeug.security import generate_password_hash
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        # Create new user
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=hashed_password,
            accountType=account_type,
            admin_code=admin_code if account_type == 'admin' else None,
            admin_role=admin_role if account_type == 'admin' else None
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": f"User '{first_name} {last_name}' added successfully",
            "user_id": new_user.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@views.route('/get-user/<int:user_id>')
@login_required
def get_user(user_id):
    """Get user details for editing"""
    requester_is_admin = getattr(current_user, 'accountType', None) == 'admin'

    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    # Permission rules:
    # - Regular users: only their own details
    # - Super Admin (1236): can access any user, including admins
    # - Regular Admins: cannot access other admins
    if not requester_is_admin and current_user.id != user_id:
        return jsonify({"success": False, "error": "Access denied"}), 403
    if requester_is_admin:
        if getattr(current_user, 'admin_code', None) == '1236':
            pass  # super admin allowed
        elif user.accountType == 'admin' and user_id != current_user.id:
            return jsonify({"success": False, "error": "Cannot access admin account details"}), 403

    return jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name or '',
            "email": user.email,
            "accountType": user.accountType,
            "admin_code": user.admin_code or '',
            "admin_role": user.admin_role or ''
        }
    })


@views.route('/edit-user', methods=['POST'])
@login_required
def edit_user():
    """Edit an existing user"""
    try:
        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"success": False, "error": "User ID required"}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        
        requester_is_admin = getattr(current_user, 'accountType', None) == 'admin'
        is_self = int(user_id) == current_user.id
        
        # Permission rules:
        # - Regular users can edit only themselves (and cannot escalate to admin)
        # - Super Admin (1236) can edit any user including admins
        # - Regular Admins can edit non-admin users; cannot edit other admins (can edit self)
        if not requester_is_admin and not is_self:
            return jsonify({"success": False, "error": "Access denied"}), 403
        if requester_is_admin:
            if getattr(current_user, 'admin_code', None) == '1236':
                pass  # super admin allowed
            elif user.accountType == 'admin' and not is_self:
                return jsonify({"success": False, "error": "Cannot edit admin accounts"}), 403
        
        # Get form data
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower() # May not be present
        password = request.form.get('password', '').strip()
        account_type = request.form.get('account_type', user.accountType)
        admin_code = request.form.get('admin_code', '').strip()
        admin_role = request.form.get('admin_role', '').strip()
        
        # Validation
        if not first_name:
            return jsonify({"success": False, "error": "First name and email are required"}), 400
        
        # Only validate and update email if it was provided in the form
        if email:
            # Check if email already exists for different user
            existing_user = User.query.filter(User.email == email, User.id != user_id).first()
            if existing_user:
                return jsonify({"success": False, "error": "Email already registered to another user"}), 400
            user.email = email
        
        # Update user fields
        user.first_name = first_name
        user.last_name = last_name

        # Role-based access control
        current_user_admin_code = getattr(current_user, 'admin_code', None)
        is_super_admin = current_user_admin_code == '1236'
        target_is_admin = user.accountType == 'admin'
        
        if requester_is_admin:
            if is_super_admin and not is_self:
                # Super Admin (1236) can edit OTHERS and change any roles
                # But even Super Admin cannot change their own role (prevents accidental self-demotion)
                user.accountType = account_type
                user.admin_code = admin_code if account_type == 'admin' else None
                user.admin_role = admin_role if account_type == 'admin' else None
                print(f"[ADMIN] Super Admin {current_user.email} modified user {user.email} (roles: {account_type}, {admin_code})")
            elif is_super_admin and is_self:
                # Super Admin editing themselves - cannot change own role
                user.accountType = user.accountType
                user.admin_code = user.admin_code
                user.admin_role = user.admin_role
                print(f"[ADMIN] Super Admin {current_user.email} edited their own profile (roles preserved)")
            else:
                # Regular Admins (1234, 1235) have limited access
                if target_is_admin and not is_self:
                    # Cannot edit other admins
                    return jsonify({
                        "success": False, 
                        "error": "You don't have permission to edit admin users. Contact a Super Administrator."
                    }), 403
                elif is_self:
                    # Admins editing themselves - cannot change their own role
                    user.accountType = user.accountType
                    user.admin_code = user.admin_code
                    user.admin_role = user.admin_role
                    print(f"[ADMIN] Admin {current_user.email} edited their own profile (roles preserved)")
                else:
                    # Regular admins can edit regular users AND change their roles
                    user.accountType = account_type
                    user.admin_code = admin_code if account_type == 'admin' else None
                    user.admin_role = admin_role if account_type == 'admin' else None
                    print(f"[ADMIN] Admin {current_user.email} edited regular user {user.email} (roles: {account_type}, {admin_code})")
        else:
            # Regular users can only edit themselves and cannot change roles
            if not is_self:
                return jsonify({
                    "success": False, 
                    "error": "You can only edit your own profile"
                }), 403
            
            # Preserve existing role settings
            user.accountType = user.accountType
            user.admin_code = user.admin_code
            user.admin_role = user.admin_role
            
            # Security monitoring for attempted role changes
            if (request.form.get('account_type') and request.form.get('account_type') != user.accountType) or \
               (request.form.get('admin_code') and request.form.get('admin_code') != (user.admin_code or '')):
                print(f"[SECURITY] User {current_user.email} attempted to modify their own role/admin privileges")
                
            print(f"[USER] Regular user {current_user.email} edited their own profile")
        
        # Update password if provided
        if password:
            from werkzeug.security import generate_password_hash
            user.password = generate_password_hash(password, method='pbkdf2:sha256')
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": f"User '{first_name} {last_name}' updated successfully"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@views.route('/delete-user', methods=['POST'])
@login_required
def delete_user():
    """Delete a user with concurrency protection"""
    try:
        user_id = request.form.get('user_id')
        if not user_id:
            # Try JSON data as fallback
            data = request.get_json()
            user_id = data.get('user_id') if data else None
            
        if not user_id:
            return jsonify({"success": False, "error": "User ID required"}), 400
        
        # Directly delete user with role-based permissions
        target = User.query.get(user_id)
        if not target:
            return jsonify({"success": False, "error": "User not found"}), 404

        requester_is_admin = getattr(current_user, 'accountType', None) == 'admin'
        is_super_admin = requester_is_admin and getattr(current_user, 'admin_code', None) == '1236'
        is_self = int(user_id) == current_user.id
        target_is_admin = target.accountType == 'admin'

        if is_self:
            return jsonify({"success": False, "error": "Cannot delete your own account"}), 403
        if not requester_is_admin:
            return jsonify({"success": False, "error": "Admin access required"}), 403
        if not is_super_admin and target_is_admin:
            return jsonify({"success": False, "error": "You don't have permission to delete admin users"}), 403

        # Clean up related records
        Notification.query.filter_by(user_id=target.id).delete(synchronize_session=False)
        TicketAssignment.query.filter_by(assigned_to=target.id).delete(synchronize_session=False)
        user_tickets = Ticket.query.filter_by(user_id=target.id).all()
        for t in user_tickets:
            if t.assignment:
                db.session.delete(t.assignment)
            db.session.delete(t)
        db.session.delete(target)
        db.session.commit()
        return jsonify({"success": True, "message": f"User '{target.first_name} {target.last_name or ''}' deleted successfully"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@views.route('/edit-ticket')
@login_required
def edit_ticket():
    ticket = json.loads(request.data)
    ticketId = ticket['ticketId']
    current_ticket = Ticket.query.get(ticketId)
    return render_template('edit_ticket.html',  user=current_user, ticket=current_ticket)


@views.route('/close-ticket/<string:ticket_id>', methods=['POST'])
@login_required
def close_ticket():
    """Close a ticket with concurrency protection"""
    try:
        ticket_data = json.loads(request.data)
        ticket_id = ticket_data['ticketId']
        
        # Directly update status to Closed
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({"success": False, "error": "Ticket not found"}), 404
        old_status = ticket.status
        ticket.status = "Closed"

        closure_time = datetime.now().astimezone()
        
        assignment = ticket.assignment
        if not assignment:
            # Create an assignment record if one doesn't exist, to store the closure info
            assignment = TicketAssignment(ticket_id=ticket_id)
            db.session.add(assignment)

        assignment.status = "Closed"
        assignment.closed_date = closure_time  # Store closure time
        db.session.commit()
        
        # Get ticket for notifications (separate transaction)
        ticket = Ticket.query.get(ticket_id)
        if ticket:
            admin_name = get_full_name(current_user)
            print(f"[TICKET CLOSE] Ticket #{ticket_id} closed by admin {admin_name}")
            
            # Create notification (separate transaction for non-critical operation)
            try:
                new_notification = Notification(
                    message=f"Your ticket was closed by {admin_name}. If the issue persists, please add a comment to reopen it.", 
                    status="error", 
                    user_id=ticket.user_id
                )
                db.session.add(new_notification)
                db.session.commit()
            except Exception as e:
                print(f"[NOTIFICATION ERROR] Failed to create notification: {e}")
            
            # Send email notification about status change
            try:
                from .alerting import send_ticket_status_changed_notification
                admins = User.query.filter_by(accountType="admin").all()
                send_ticket_status_changed_notification(ticket, old_status, "Closed", admins)
            except Exception as e:
                print(f"[EMAIL ERROR] Failed to send status change notification: {e}")
            # Publish admin-side update so users refresh
            try:
                _publish('admin_updates', {"type": "ticket_closed", "ticket_id": ticket_id})
            except Exception:
                pass
        
        return jsonify({"success": True, "message": "Ticket closed successfully"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@views.route('/solve-ticket/<string:ticket_id>', methods=['POST'])
@login_required
def solve_ticket():
    """Mark a ticket as solved with concurrency protection"""
    try:
        ticket_data = json.loads(request.data)
        ticket_id = ticket_data['ticketId']
        
        # Directly update status to Solved
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({"success": False, "error": "Ticket not found"}), 404
        old_status = ticket.status
        ticket.status = "Solved"
        if ticket.assignment:
            assignment = ticket.assignment
        else:
            # Create an assignment record if one doesn't exist, to store the solved info
            assignment = TicketAssignment(ticket_id=ticket_id)
            db.session.add(assignment)

        assignment.status = "Solved"
        assignment.closed_date = datetime.now().astimezone()  # Store solved time
        db.session.commit()
        
        # Get ticket for notifications (separate transaction)
        ticket = Ticket.query.get(ticket_id)
        if ticket:
            admin_name = get_full_name(current_user)
            print(f"[TICKET SOLVE] Ticket #{ticket_id} marked as solved by admin {admin_name}")
            
            # Create notification (separate transaction for non-critical operation)
            try:
                new_notification = Notification(
                    message=f"Your ticket was marked as solved by {admin_name}. If you have a new related issue, please create a new ticket.", 
                    status="success", 
                    user_id=ticket.user_id
                )
                db.session.add(new_notification)
                db.session.commit()
            except Exception as e:
                print(f"[NOTIFICATION ERROR] Failed to create notification: {e}")
            
            # Send email notification about status change
            try:
                from .alerting import send_ticket_status_changed_notification
                admins = User.query.filter_by(accountType="admin").all()
                send_ticket_status_changed_notification(ticket, old_status, "Solved", admins)
            except Exception as e:
                print(f"[EMAIL ERROR] Failed to send status change notification: {e}")
            # Publish admin-side update so users refresh
            try:
                _publish('admin_updates', {"type": "ticket_solved", "ticket_id": ticket_id})
            except Exception:
                pass
        
        return jsonify({"success": True, "message": "Ticket marked as solved successfully"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@views.route('/reopen-ticket/<string:ticket_id>', methods=['POST'])
@login_required
def reopen_ticket(ticket_id):
    """Allow users to reopen closed/solved tickets with a reason"""
    try:
        # Get data from request
        if request.is_json:
            data = request.get_json()
            ticket_id = data.get('ticketId')
            reopen_reason = data.get('reason')
        else:
            ticket_id = request.form.get('ticket_id')
            reopen_reason = request.form.get('reason')
        
        # Validate inputs
        if not ticket_id or not reopen_reason:
            msg = "Ticket ID and reason are required"
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for('views.tickets'))
        
        # Get ticket
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            msg = "Ticket not found"
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 404
            flash(msg, "error")
            return redirect(url_for('views.tickets'))
        
        # Permission check: only ticket owner can reopen
        if ticket.user_id != current_user.id:
            msg = "You can only reopen your own tickets"
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 403
            flash(msg, "error")
            return redirect(url_for('views.tickets'))
        
        # Check if ticket can be reopened - only allow "closed" tickets, not "solved"
        current_status = (ticket.status or '').lower()
        if current_status != 'closed':
            if current_status == 'solved':
                msg = "Solved tickets cannot be reopened. If you have a new issue, please create a new ticket."
            else:
                msg = f"Ticket is already {ticket.status}. Only closed tickets can be reopened."
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "warning")
            return redirect(url_for('views.tickets'))
        
        # Store the original status for logging
        original_status = ticket.status

        # Directly set status to Pending and append a reopen comment
        ticket.status = 'Pending'
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        if not assignment:
            assignment = TicketAssignment(ticket_id=ticket_id, status='Pending', assigned_date=None)  # do not set assigned time on reopen
            db.session.add(assignment)
        else:
            assignment.status = 'Pending'

        user_name = get_full_name(current_user)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        reopen_comment = f"--- {user_name} ({timestamp}) ---\nTicket reopened: {reopen_reason}"
        existing_comment = assignment.comment or ''
        assignment.comment = (existing_comment + ("\n\n" if existing_comment.strip() else "") + reopen_comment)

        db.session.commit()
        
        # Log the reopening
        user_name = get_full_name(current_user)
        print(f"[TICKET REOPEN] Ticket #{ticket_id} reopened by user {user_name} - Reason: {reopen_reason}")
        
        # Fetch assignment for notification routing
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()

        # Send notification to assigned admin
        if assignment and assignment.user:
            try:
                note = Notification(
                    message=f"Ticket #{ticket_id} REOPENED by {user_name}: {reopen_reason}",
                    status="warning",
                    user_id=assignment.user.id
                )
                db.session.add(note)
                db.session.commit()
            except Exception as e:
                print(f'[NOTIFY][ERROR] {e}')
        
        # Send email notification using proper template
        try:
            from .alerting import send_ticket_reopened_notification
            admins = User.query.filter_by(accountType="admin").all()
            send_ticket_reopened_notification(ticket, current_user, reopen_reason, admins)
        except Exception as e:
            print(f'[EMAIL][ERROR] Failed to send ticket reopened notification: {e}')
        
        # Publish user-side update so admins refresh
        try:
            _publish('user_updates', {"type": "ticket_reopened", "ticket_id": ticket_id})
        except Exception:
            pass

        success_msg = f"Ticket #{ticket_id} has been reopened successfully. The assigned admin has been notified."
        
        if request.is_json:
            return jsonify({
                "success": True,
                "message": success_msg,
                "new_status": "Pending"
            })
        else:
            flash(success_msg, "success")
            return redirect(url_for('views.tickets'))
            
    except Exception as e:
        error_msg = f"Error reopening ticket: {str(e)}"
        print(f"[REOPEN ERROR] {error_msg}")
        
        if request.is_json:
            return jsonify({"success": False, "error": error_msg}), 500
        else:
            flash(error_msg, "error")
            return redirect(url_for('views.tickets'))


# -------------------
# NEW: Get Ticket Details (with assignment info)
# -------------------
@views.route('/get-ticket-details/<string:ticket_id>')
@login_required
def get_ticket_details(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket not found'}), 404

    assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()

    # Get creator's full name
    created_by_name = "Unknown"
    if ticket.creator:
        created_by_name = get_full_name(ticket.creator)
    elif ticket.username:
        created_by_name = ticket.username
    return jsonify({
        'id': ticket.id,
        'title': ticket.title,
        'project': ticket.project,
        'project_manager': ticket.project_manager,
        'location': ticket.location,
        'cubical': ticket.cubical,
        'ticket_type': ticket.ticket_type,
        'desc': ticket.desc,
        'username': ticket.username,
        'created_by': created_by_name,
        'category': ticket.category,
        'priority': ticket.priority,
        'date': ticket.date.strftime('%Y-%m-%d %H:%M:%S') if ticket.date else None,
        'movement_from': ticket.movement_from,
        'movement_to': ticket.movement_to,
        'status': assignment.status if assignment else "Pending",
        'assigned': get_full_name(assignment.user) if assignment and assignment.user else "Not Assigned",
        'assigned_user_id': assignment.assigned_to if assignment else None,
        'eta': assignment.eta if assignment else None,
        'comment': assignment.comment if assignment else ""
    })


@views.route('/update-ticket-priority/<string:ticket_id>', methods=['POST'])
@login_required
def update_ticket_priority(ticket_id):
    """Allows a user to update the priority of their own ticket."""
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404

    # Security check: only the ticket owner can change priority
    if ticket.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    data = request.get_json()
    new_priority = data.get('priority')
    if new_priority not in ['High', 'Medium', 'Low']:
        return jsonify({'success': False, 'error': 'Invalid priority value'}), 400

    try:
        ticket.priority = new_priority
        db.session.commit()

        # Publish an event to notify admins of the change
        _publish('user_updates', {"type": "priority_changed", "ticket_id": ticket_id, "priority": new_priority})

        return jsonify({'success': True, 'message': 'Priority updated successfully.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@views.route('/update-ticket-eta/<string:ticket_id>', methods=['POST'])
@login_required
def update_ticket_eta(ticket_id):
    """Allows an admin to update the ETA of a ticket directly."""
    if getattr(current_user, 'accountType', None) != 'admin':
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404

    data = request.get_json()
    new_eta = data.get('eta')

    try:
        # Get or create an assignment record to store the ETA
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        if not assignment:
            assignment = TicketAssignment(
                ticket_id=ticket_id,
                status=ticket.status or "Pending",
                assigned_date=None # Do not set assigned time on ETA update
            )
            db.session.add(assignment)

        assignment.eta = new_eta
        db.session.commit()

        # Publish an event to notify users of the change
        _publish('admin_updates', {"type": "eta_changed", "ticket_id": ticket_id, "eta": new_eta})

        return jsonify({'success': True, 'message': 'ETA updated successfully.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------
# NEW: Get Ticket Comments History (SIMPLIFIED)
# -------------------
@views.route('/get-ticket-comments/<string:ticket_id>')
@login_required
def get_ticket_comments(ticket_id):
    """Get comment history from TicketAssignment and Remarks."""
    try:
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({'success': False, 'error': 'Ticket not found'}), 404

        # Permissions: admin or ticket owner
        is_admin = getattr(current_user, 'accountType', None) == 'admin'
        is_owner = ticket.user_id == current_user.id
        if not (is_admin or is_owner):
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        comments = []
        
        # Get assignment comments (from admins)
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        
        if assignment and assignment.comment and assignment.comment.strip():
            # Parse assignment comments with improved logic
            import re
            text = assignment.comment
            
            # Split by common patterns
            admin_pattern = r'^---\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s+(.+?)---\s*$'
            user_pattern = r'^---\s*(.+?)\s*\((\d{4}-\d{2}-\d{2} \d{2}:\d{2})\)\s*---\s*$'
            
            lines = text.split('\n')
            current_comment = None
            
            for line in lines:
                # Check for admin comment marker
                admin_match = re.match(admin_pattern, line)
                if admin_match:
                    # Save previous comment if exists
                    if current_comment and current_comment['text'].strip():
                        comments.append(current_comment)
                    # Start new admin comment
                    current_comment = {
                        'user_name': admin_match.group(2),
                        'timestamp': admin_match.group(1),
                        'text': '',
                        'type': 'admin'
                    }
                    continue
                    
                # Check for user comment marker
                user_match = re.match(user_pattern, line)
                if user_match:
                    # Save previous comment if exists
                    if current_comment and current_comment['text'].strip():
                        comments.append(current_comment)
                    # Start new user comment
                    current_comment = {
                        'user_name': user_match.group(1),
                        'timestamp': user_match.group(2),
                        'text': '',
                        'type': 'user'
                    }
                    continue
                    
                # Add line to current comment
                if current_comment:
                    if current_comment['text']:
                        current_comment['text'] += '\n' + line
                    else:
                        current_comment['text'] = line
                else:
                    # Legacy comment without header - treat as initial admin comment
                    if assignment.user:
                        admin_name = get_full_name(assignment.user)
                    else:
                        admin_name = 'Admin'
                    
                    timestamp = assignment.assigned_date.strftime('%Y-%m-%d %H:%M') if assignment.assigned_date else 'N/A'
                    current_comment = {
                        'user_name': admin_name,
                        'timestamp': timestamp,
                        'text': line,
                        'type': 'admin'
                    }
            
            # Add the last comment
            if current_comment and current_comment['text'].strip():
                comments.append(current_comment)
        
        # Note: Remark model was removed, all comments are stored in TicketAssignment.comment
        # The parsing logic above already handles both admin and user comments
        
        # If no comments found, show default message
        if not comments:
            comments.append({
                'user_name': 'System',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'text': 'No comments available yet. Add a comment when assigning this ticket.',
                'type': 'system'
            })
        
        # Sort comments by timestamp
        def parse_timestamp(ts_str):
            try:
                return datetime.strptime(ts_str, '%Y-%m-%d %H:%M')
            except:
                return datetime.min
        
        comments.sort(key=lambda c: parse_timestamp(c.get('timestamp', 'N/A')))
        comments.reverse() # <-- ADD THIS LINE
        
        return jsonify({'success': True, 'comments': comments})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------
# UPDATE COMMENT (if needed)
# -------------------
@views.route("/update-comment/<string:ticket_id>", methods=["POST"])
@login_required
def update_comment(ticket_id):
    # Helper to detect AJAX
    def is_ajax():
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
               'application/json' in (request.headers.get('Accept') or '')

    # Resolve redirect target based on role
    def redirect_target():
        return url_for("views.adminDashboard") if getattr(current_user, 'accountType', None) == 'admin' else url_for("views.tickets")

    # Load ticket first (needed for permission and creating assignment if missing)
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        msg = "Ticket not found"
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 404
        flash(msg, "danger")
        return redirect(redirect_target())

    # Permission: admin OR ticket owner can update
    is_admin = getattr(current_user, 'accountType', None) == 'admin'
    is_owner = ticket.user_id == current_user.id
    if not (is_admin or is_owner):
        msg = "Unauthorized action"
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "danger")
        return redirect(redirect_target())
    
    # NEW: Prevent users (non-admins) from updating comments on closed tickets
    current_status = (ticket.status or '').lower()
    if not is_admin and current_status in ('closed',):
        msg = "Cannot update comments on closed tickets. Please use 'Reopen Ticket' if issue persists."
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "warning")
        return redirect(redirect_target())

    # Get or create assignment record to store the comment
    assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
    if not assignment:
        assignment = TicketAssignment(
            ticket_id=ticket_id,
            assigned_to=None,
            comment=None,
            status=ticket.status or "Pending",
            assigned_date=None  # do not set assigned time on comment creation
        )
        db.session.add(assignment)
        db.session.flush()  # ensure assignment gets an ID before commit if needed

    comment_val = request.json.get("comment") if request.is_json else request.form.get("comment")
    assignment.comment = comment_val

    # Defaults for response flags used by frontend
    reopened = False
    notify_sent = False
    email_sent = False

    # Regular comment update - no automatic reopening
    db.session.commit()

    # In-app notifications for comment updates
    try:
        # If admin updated comment -> notify ticket owner
        if is_admin:
            owner = ticket.creator
            if owner:
                note = Notification(
                    message=f"Admin {get_full_name(current_user)} updated a comment on Ticket #{ticket_id}",
                    status="info",
                    user_id=owner.id
                )
                db.session.add(note)
                db.session.commit()
        else:
            # User updated comment -> notify assigned admin or relevant admin group
            assigned = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
            notified_any = False
            if assigned and assigned.user:
                note = Notification(
                    message=f"User {get_full_name(current_user)} updated a comment on Ticket #{ticket_id}",
                    status="info",
                    user_id=assigned.user.id
                )
                db.session.add(note)
                db.session.commit()
                notified_any = True
            if not notified_any:
                # Notify relevant admin group (IT or Hardware)
                for admin in get_relevant_admins_for_ticket(ticket):
                    note = Notification(
                        message=f"User {get_full_name(current_user)} updated a comment on Ticket #{ticket_id}",
                        status="info",
                        user_id=admin.id
                    )
                    db.session.add(note)
                db.session.commit()
    except Exception as e:
        print(f"[NOTIFICATION ERROR] Failed to create comment update notifications: {e}")

    # Send email notification for new comment (user->admin and admin->user)
    try:
        from .alerting import send_ticket_comment_notification, send_admin_comment_notification
        if comment_val and comment_val.strip():
            if not is_admin:  # User adding comment - notify admins
                admins = User.query.filter_by(accountType="admin").all()
                send_ticket_comment_notification(ticket, comment_val, current_user, admins)
                email_sent = True
            else:
                # Admin adding/updating comment - notify ticket owner
                owner = ticket.creator
                if owner and owner.email:
                    send_admin_comment_notification(ticket, comment_val, current_user, owner)
                    email_sent = True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send comment notification: {e}")

    # Publish SSE event to trigger UI refresh for the other side only when updates occur
    try:
        if is_admin:
            _publish('admin_updates', {"type": "comment_updated", "ticket_id": ticket_id})  # notify users
        else:
            _publish('user_updates', {"type": "comment_updated", "ticket_id": ticket_id})   # notify admins
    except Exception:
        pass

    if is_ajax():
        return jsonify({
            "success": True,
            "comment": assignment.comment,
            "reopened": reopened,
            "notify_sent": notify_sent,
            "email_sent": email_sent
        })

    if reopened:
        flash("Ticket has been automatically REOPENED because the issue was not resolved. The assigned admin has been notified.", "warning")
    else:
        flash("Comment updated successfully!", "success")
    return redirect(redirect_target())


# -------------------
# ADMIN: Sync Ticket Assignment Data
# -------------------
@views.route('/sync-ticket-data', methods=['POST'])
@login_required
def sync_ticket_data():
    """Admin-only route to synchronize ticket assignment data"""
    if current_user.accountType != "admin":
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    result = sync_ticket_assignment_data()
    return jsonify(result)


# -------------------
# NEW: Add Remark to Ticket
# -------------------
@views.route("/add-remark/<string:ticket_id>", methods=["POST"])
@login_required
def add_remark(ticket_id):
    """Add a new remark to a ticket (appends to history, doesn't overwrite)"""
    # Helper to detect AJAX
    def is_ajax():
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
               'application/json' in (request.headers.get('Accept') or '')

    # Resolve redirect target based on role
    def redirect_target():
        return url_for("views.adminDashboard") if getattr(current_user, 'accountType', None) == 'admin' else url_for("views.tickets")

    # Load ticket first
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        msg = "Ticket not found"
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 404
        flash(msg, "danger")
        return redirect(redirect_target())

    # Permission: admin OR ticket owner can add remarks
    is_admin = getattr(current_user, 'accountType', None) == 'admin'
    is_owner = ticket.user_id == current_user.id
    if not (is_admin or is_owner):
        msg = "Unauthorized action"
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "danger")
        return redirect(redirect_target())
    
    # Prevent users (non-admins) from adding remarks on solved tickets
    current_status = (ticket.status or '').lower()
    if not is_admin and current_status in ('solved',):
        msg = "Cannot add remarks to solved tickets. Please create a new ticket for new issues."
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 403
        flash(msg, "warning")
        return redirect(redirect_target())

    # Get the remark text
    remark_text = request.json.get("remark") if request.is_json else request.form.get("remark")
    
    if not remark_text or not remark_text.strip():
        msg = "Remark cannot be empty"
        if is_ajax():
            return jsonify({"success": False, "error": msg}), 400
        flash(msg, "warning")
        return redirect(redirect_target())

    try:
        # Directly append remark to assignment comment history
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        if not assignment:
            assignment = TicketAssignment(ticket_id=ticket_id, status=ticket.status or 'Pending', assigned_date=None)  # do not set assigned time on remark
            db.session.add(assignment)

        user_name = get_full_name(current_user)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        existing_comment = assignment.comment or ''
        if is_admin:
            new_entry = f"---[{timestamp}] {user_name}---\n{remark_text.strip()}"
        else:
            new_entry = f"--- {user_name} ({timestamp}) ---\n{remark_text.strip()}"
        assignment.comment = (existing_comment + ("\n\n" if existing_comment.strip() else "") + new_entry)
        assignment.status = ticket.status or assignment.status
        db.session.commit()

        assignment_comment = assignment.comment

        # In-app notifications for new remark
        try:
            if is_admin:
                # Admin added remark -> notify owner
                owner = ticket.creator
                if owner:
                    note = Notification(
                        message=f"Admin {get_full_name(current_user)} added a comment on Ticket #{ticket_id}",
                        status="info",
                        user_id=owner.id
                    )
                    db.session.add(note)
                    db.session.commit()
            else:
                # User added remark -> notify assigned admin or relevant admin group
                assigned = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
                notified_any = False
                if assigned and assigned.user:
                    note = Notification(
                        message=f"User {get_full_name(current_user)} added a comment on Ticket #{ticket_id}",
                        status="info",
                        user_id=assigned.user.id
                    )
                    db.session.add(note)
                    db.session.commit()
                    notified_any = True
                if not notified_any:
                    for admin in get_relevant_admins_for_ticket(ticket):
                        note = Notification(
                            message=f"User {get_full_name(current_user)} added a comment on Ticket #{ticket_id}",
                            status="info",
                            user_id=admin.id
                        )
                        db.session.add(note)
                    db.session.commit()
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to create remark notifications: {e}")

        # Send email notification for new comment (user->admin and admin->user)
        try:
            from .alerting import (
                send_ticket_comment_notification, 
                send_admin_comment_notification,
                send_admin_group_comment_notification
            )
            from .models import User

            if not is_admin:  # User adding comment - notify admins
                admins = User.query.filter_by(accountType="admin").all()
                send_ticket_comment_notification(ticket, remark_text, current_user, admins)
            else:
                # Admin adding comment:
                # 1. Notify the ticket owner (user)
                owner = ticket.creator
                if owner and owner.email:
                    send_admin_comment_notification(ticket, remark_text, current_user, owner)
                # 2. Notify other relevant admins in the group
                try:
                    admins = User.query.filter_by(accountType="admin").all()
                    send_admin_group_comment_notification(ticket, remark_text, current_user, admins)
                except Exception as e_group:
                    print(f"[EMAIL ERROR] Failed to send admin group comment notification: {e_group}")

        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send comment notification: {e}")

        if is_ajax():
            return jsonify({
                "success": True,
                "message": "Comment added successfully",
                "comment": assignment_comment
            })

        flash("Comment added successfully", "success")
        return redirect(redirect_target())
        
    except Exception as e:
        error_msg = f"Error adding remark: {str(e)}"
        if is_ajax():
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "danger")
        return redirect(redirect_target())


# -------------------
# NEW: Get Assignable Users
# -------------------
@views.route('/get-assignable-users', methods=['POST'])
@login_required
def get_assignable_users():
    """Get list of admin users that can be assigned to tickets based on category"""
    print(f"[DEBUG] get_assignable_users called by user: {current_user.first_name} (type: {getattr(current_user, 'accountType', None)})")
    
    if getattr(current_user, 'accountType', None) != 'admin':
        print("[DEBUG] Access denied - not admin")
        return jsonify({"success": False, "error": "Admin access required"}), 403
    
    try:
        category = request.form.get('category', '').strip().lower()
        print(f"[DEBUG] Requested category: '{category}'")
        
        # Filter admin users by category and current user's privileges
        current_admin_code = getattr(current_user, 'admin_code', None)
        is_super_admin = current_admin_code == '1236'

        allowed_codes = None
        if category == 'software':
            allowed_codes = ['1234'] + (['1236'] if is_super_admin else [])  # IT Admin (+ Super Admin if allowed)
        elif category == 'hardware':
            allowed_codes = ['1235'] + (['1236'] if is_super_admin else [])  # Hardware Admin (+ Super Admin if allowed)

        if allowed_codes is not None:
            admin_users = User.query.filter_by(accountType='admin').filter(User.admin_code.in_(allowed_codes)).all()
        else:
            if is_super_admin:
                admin_users = User.query.filter_by(accountType='admin').all()
            else:
                # Exclude Super Admin from list for non-super admins
                admin_users = User.query.filter_by(accountType='admin').filter(User.admin_code != '1236').all()
        print(f"[DEBUG] Found {len(admin_users)} admin users for category '{category}' (is_super_admin={is_super_admin})")
        
        users_list = []
        for user in admin_users:
            user_data = {
                'id': user.id,
                'name': get_full_name(user),
                'first_name': user.first_name,
                'last_name': user.last_name or '',
                'admin_code': user.admin_code or '',
                'admin_role': user.admin_role or '',
                'email': user.email
            }
            users_list.append(user_data)
            print(f"[DEBUG] Added user: {user_data['name']} (ID: {user_data['id']}, Code: {user_data['admin_code']})")
        
        response_data = {
            "success": True,
            "users": users_list,
            "debug_info": {
                "category_received": category,
                "user_count": len(users_list),
                "current_user": current_user.first_name
            }
        }
        
        print(f"[DEBUG] Returning response with {len(users_list)} users")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[DEBUG] Error in get_assignable_users: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# -------------------
# NEW: Get Ticket Details for Assignment
# -------------------
@views.route('/get-ticket-assignment-details/<string:ticket_id>', methods=['GET'])
@login_required
def get_ticket_assignment_details(ticket_id):
    """Get ticket details for assignment modal"""
    if getattr(current_user, 'accountType', None) != 'admin':
        return jsonify({"success": False, "error": "Admin access required"}), 403
    
    try:
        # Get ticket
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({"success": False, "error": "Ticket not found"}), 404
        
        # Get assignment details if exists
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        
        response_data = {
            "success": True,
            "ticket_id": ticket.id,
            "title": ticket.title,
            "status": assignment.status if assignment else ticket.status,
            "assigned_user_id": assignment.assigned_to if assignment else None,
            "category": ticket.category
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# -------------------
# NEW: Assign Ticket
# -------------------
@views.route('/assign-ticket', methods=['POST'])
@login_required
def assign_ticket():
    """Assign a ticket to an admin user with concurrency protection"""
    if getattr(current_user, 'accountType', None) != 'admin':
        return jsonify({"success": False, "error": "Admin access required"}), 403
    
    try:
        ticket_id = request.form.get('ticket_id')
        user_id = request.form.get('user_id')
        status = request.form.get('status', 'Pending')
        comment = request.form.get('comment', '').strip()
        
        # Validate inputs
        if not ticket_id or not user_id:
            return jsonify({"success": False, "error": "Ticket ID and User ID are required"}), 400
        
        # Directly assign or update assignment
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({"success": False, "error": "Ticket not found"}), 404

        # Get priority from form, but default to the ticket's CURRENT priority if not provided
        # This ensures that if the form sends an empty priority, we still keep the old one.
        new_priority = request.form.get('priority')
        if not new_priority or new_priority not in ['High', 'Medium', 'Low']:
            new_priority = ticket.priority # Keep existing priority

        assigned_user = User.query.get(user_id)
        if not assigned_user or assigned_user.accountType != 'admin':
            return jsonify({"success": False, "error": "Invalid admin user selected"}), 400
        
        assignment = TicketAssignment.query.filter_by(ticket_id=ticket_id).first()
        action_type = "assigned"
        if assignment:
            action_type = "updated"
            assignment.assigned_to = int(user_id)
            assignment.status = status
            # Only update the date if the ticket is not already closed/solved
            if status in ['Closed', 'Solved']:
                if not assignment.closed_date: # Set closure date only if not already set
                    assignment.closed_date = datetime.now().astimezone()
            else:
                assignment.assigned_date = datetime.now().astimezone() # Set/update assignment time
                assignment.closed_date = None # Clear closed date if re-assigned
        else:
            assignment = TicketAssignment(
                ticket_id=ticket_id,
                assigned_to=int(user_id),
                status=status
            )
            if status in ['Closed', 'Solved']:
                assignment.closed_date = datetime.now().astimezone()
            assignment.assigned_date = datetime.now().astimezone()
            db.session.add(assignment)

        if comment and comment.strip():
            admin_name = get_full_name(current_user)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            prefix = f"---[{timestamp}] {admin_name}---\n"
            existing = assignment.comment or ''
            assignment.comment = (existing + ("\n\n" if existing.strip() else "") + prefix + comment.strip())

        # Record status transition history if changed
        try:
            from .models import TicketStatusHistory
            old_status = (ticket.status or '').strip()
            new_status = (status or '').strip()
            if old_status.lower() != new_status.lower():
                hist = TicketStatusHistory( # This will now work with string IDs
                    ticket_id=ticket_id,
                    old_status=old_status or None,
                    new_status=new_status,
                    changed_by=getattr(current_user, 'id', None)
                )
                db.session.add(hist)
        except Exception as _:
            pass

        ticket.status = status
        ticket.priority = new_priority
        ticket.assigned = get_full_name(assigned_user)
        db.session.commit()
        
        # Send notification to assigned user (separate transaction for non-critical operation)
        try:
            notification_message = f"Ticket #{ticket_id} has been {action_type} to you by {get_full_name(current_user)}"
            notification = Notification(
                message=notification_message,
                status="info",
                user_id=int(user_id)
            )
            db.session.add(notification)
            db.session.commit()
            
            # Notify the ticket owner that their ticket was assigned
            try:
                owner_note = Notification(
                    message=f"Your ticket #{ticket_id} has been assigned to {get_full_name(assigned_user)}",
                    status="info",
                    user_id=ticket.user_id
                )
                db.session.add(owner_note)
                db.session.commit()
            except Exception as e:
                print(f"[NOTIFICATION ERROR] Failed to notify ticket owner of assignment: {e}")
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to create notification: {e}")
            # Don't fail the assignment for notification errors
        
        # Send email notification (separate from main transaction)
        try:
            from .alerting import send_ticket_assigned_notification
            send_ticket_assigned_notification(ticket, assignment, assigned_user)
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send assignment notification: {e}")
            # Don't fail the assignment for email errors
        
        # Publish SSE events so UIs refresh only when assignments change
        try:
            _publish('user_updates', {"type": "ticket_assigned", "ticket_id": ticket_id})   # notify admins
            _publish('admin_updates', {"type": "ticket_assigned", "ticket_id": ticket_id})  # notify user
        except Exception:
            pass
        
        message_text = f"Ticket {action_type} successfully to {assigned_user.first_name} {assigned_user.last_name or ''}".strip()
        return jsonify({
            "success": True,
            "message": message_text,
            "assigned_to": get_full_name(assigned_user),
            "status": status,
            "action_type": action_type
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Assignment failed: {str(e)}"}), 500
