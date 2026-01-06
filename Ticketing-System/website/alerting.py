import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
import threading

# Import email configuration from external config file
try:
    import sys
    import os
    # Add parent directory to path to import email_config
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    from email_config import EMAIL_CONFIG, NOTIFICATION_TRIGGERS, ADMIN_GROUPS, ADMIN_ROLES
except ImportError:
    # Fallback configuration if email_config.py is not found
    EMAIL_CONFIG = {
        "smtp_server": "NTDB.RDLTL.COM",
        "smtp_port": 25,
        "sender_email": "mailadmin@rdltl.com",
        "sender_password": "rdl@123",
        "use_tls": True,
        "enabled": True,
        "debug": False
    }
    NOTIFICATION_TRIGGERS = {
        "ticket_created": True,
        "ticket_assigned": True,
        "status_changed": True,
        "comment_added": True,
        "ticket_reopened": True,
        "ticket_closed": True,
        "ticket_solved": True
    }
    ADMIN_GROUPS = {
        "it": {"admin_codes": ["1234"], "ticket_types": [
            "Laptop", "Desktop", "Workstation", "OS installation", "Network issues", "Network Request",
            "Private network", "New setup", "Server Issue", "Lan Ports Not working", "Adding users into Domain",
            "Port Request", "Fax Port Issue", "VOIP"]},
        "hardware": {"admin_codes": ["1235"], "ticket_types": ["Printer Request", "Cartridge Request", "Printer Issue", "Paper Request", "Printer Movement Request", "Printer Movement to Wireless Lab"]},
        "super": {"admin_codes": ["1236"], "ticket_types": "all"}
    }
    ADMIN_ROLES = {}

# Set up logging for email notifications
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _send_email_async_wrapper(app, recipient_email, subject, body, html_body=None):
    with app.app_context():
        send_email_alert(recipient_email, subject, body, html_body)

def send_email_alert_async(recipient_email, subject, body, html_body=None):
    from flask import current_app
    app = current_app._get_current_object()
    thread = threading.Thread(target=_send_email_async_wrapper, args=[app, recipient_email, subject, body, html_body])
    thread.start()


# Use the same time formatter
from . import server_local_format

def _get_employee_id(ticket):
    """
    Retrieve employee ID strictly from the User table.
    Prefers ticket.creator.employee_id; if unavailable (e.g., detached instance), queries by ticket.user_id.
    Returns "N/A" if not found.
    """
    # 1) Prefer relationship
    try:
        if hasattr(ticket, "creator") and getattr(ticket.creator, "employee_id", None):
            return ticket.creator.employee_id
    except Exception:
        pass
    # 2) Fallback: direct lookup by user_id
    try:
        user_id = getattr(ticket, "user_id", None)
        if user_id:
            from .models import User
            user = User.query.get(user_id)
            if user and getattr(user, "employee_id", None):
                return user.employee_id
    except Exception:
        pass
    # 3) Not available
    return "N/A"

def send_email_alert(recipient_email, subject, body, html_body=None):
    """
    Send email alert to specified recipient
    
    Args:
        recipient_email (str): Email address of recipient
        subject (str): Email subject
        body (str): Plain text body
        html_body (str, optional): HTML formatted body
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not EMAIL_CONFIG["enabled"]:
        logger.info(f"Email notifications disabled - would have sent: {subject}")
        return False
        
    if not recipient_email:
        logger.warning("No recipient email provided")
        return False
        
    try:
        # Create message
        message = MIMEMultipart('alternative')
        message["From"] = EMAIL_CONFIG["sender_email"]
        message["To"] = recipient_email
        message["Subject"] = subject
        
        # Add plain text part
        text_part = MIMEText(body, "plain")
        message.attach(text_part)
        
        # Add HTML part if provided
        if html_body:
            html_part = MIMEText(html_body, "html")
            message.attach(html_part)
        
        # Log configuration being used for transparency
        smtp_server = EMAIL_CONFIG.get("smtp_server")
        smtp_port = EMAIL_CONFIG.get("smtp_port")
        use_ssl = EMAIL_CONFIG.get("use_ssl", False)
        use_tls = EMAIL_CONFIG.get("use_tls", False)
        use_auth = EMAIL_CONFIG.get("use_auth", True)
        logger.info(
            f"Preparing to send email via {smtp_server}:{smtp_port} | SSL={use_ssl} | TLS={use_tls} | AUTH={use_auth}"
        )

        # Send email with timeout and Gmail fallback between STARTTLS:587 and SSL:465
        last_error = None
        timeout = EMAIL_CONFIG.get("timeout", 30)

        cfg_server = smtp_server
        cfg_port = smtp_port
        cfg_use_ssl = EMAIL_CONFIG.get("use_ssl", False)
        cfg_use_tls = EMAIL_CONFIG.get("use_tls", False)

        attempts = [(cfg_server, cfg_port, cfg_use_ssl, cfg_use_tls)]
        # If using Gmail, add a fallback attempt on the alternate port/mode
        if cfg_server == "smtp.gmail.com":
            if cfg_use_ssl:
                # Fallback to STARTTLS on 587
                attempts.append(("smtp.gmail.com", 587, False, True))
            else:
                # Fallback to SSL on 465
                attempts.append(("smtp.gmail.com", 465, True, False))

        for host, port, try_ssl, try_tls in attempts:
            try:
                logger.info(f"Attempting SMTP connection: {host}:{port} | SSL={try_ssl} | TLS={try_tls}")
                if try_ssl:
                    with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                        if EMAIL_CONFIG.get("debug"):
                            try:
                                server.set_debuglevel(1)
                            except Exception:
                                pass
                        try:
                            server.ehlo()
                        except Exception:
                            pass
                        if EMAIL_CONFIG.get("use_auth", True) and EMAIL_CONFIG.get("sender_password"):
                            try:
                                server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
                            except Exception as e:
                                logger.warning(f"SMTP AUTH failed over SSL, attempting to send without auth: {e}")
                        send_errors = server.sendmail(EMAIL_CONFIG["sender_email"], recipient_email, message.as_string())
                        if send_errors:
                            logger.error(f"SMTP server refused recipients: {send_errors}")
                            return False
                else:
                    with smtplib.SMTP(host, port, timeout=timeout) as server:
                        if EMAIL_CONFIG.get("debug"):
                            try:
                                server.set_debuglevel(1)
                            except Exception:
                                pass
                        try:
                            server.ehlo()
                        except Exception:
                            pass
                        if try_tls:
                            try:
                                server.starttls()
                                try:
                                    server.ehlo()
                                except Exception:
                                    pass
                            except Exception as e:
                                logger.warning(f"SMTP STARTTLS failed, continuing without TLS: {e}")
                        if EMAIL_CONFIG.get("use_auth", True) and EMAIL_CONFIG.get("sender_password"):
                            try:
                                server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
                            except Exception as e:
                                logger.warning(f"SMTP AUTH failed, attempting to send without auth: {e}")
                        send_errors = server.sendmail(EMAIL_CONFIG["sender_email"], recipient_email, message.as_string())
                        if send_errors:
                            logger.error(f"SMTP server refused recipients: {send_errors}")
                            return False

                logger.info(f"Email sent successfully to {recipient_email}: {subject}")
                return True
            except Exception as e:
                last_error = e
                logger.error(f"SMTP attempt failed for {host}:{port} (SSL={try_ssl} TLS={try_tls}): {e}")
                continue

        logger.error(f"All SMTP attempts failed for {recipient_email}: {last_error}")
        return False
        
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_email}: {e}")
        return False

def send_ticket_created_notification(ticket, admins):
    """
    Send notification when a new ticket is created
    
    Args:
        ticket: Ticket object
        admins: List of admin users who should receive notification
    """
    if not EMAIL_CONFIG["enabled"] or not admins or not NOTIFICATION_TRIGGERS.get("ticket_created", True):
        return
        
    subject = f"New Ticket Created: #{ticket.id} - {ticket.title}"
    
    # Determine which admins should receive this ticket based on ticket type
    relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
    
    for admin in relevant_admins:
        if admin.email:
            body = create_ticket_created_email_body(ticket, admin)
            html_body = create_ticket_created_html_body(ticket, admin)
            send_email_alert_async(admin.email, subject, body, html_body)

def send_ticket_assigned_notification(ticket, assignment, assigned_admin):
    """
    Send notification when a ticket is assigned to an admin
    
    Args:
        ticket: Ticket object
        assignment: TicketAssignment object
        assigned_admin: User object of the assigned admin
    """
    if not EMAIL_CONFIG["enabled"] or not assigned_admin or not assigned_admin.email or not NOTIFICATION_TRIGGERS.get("ticket_assigned", True):
        return
        
    subject = f"Ticket Assigned: #{ticket.id} - {ticket.title}"
    body = create_ticket_assigned_email_body(ticket, assignment, assigned_admin)
    html_body = create_ticket_assigned_html_body(ticket, assignment, assigned_admin)
    
    send_email_alert_async(assigned_admin.email, subject, body, html_body)
    
    try:
        from .models import User
        admins = User.query.filter_by(accountType="admin").all()
        relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
        for admin in relevant_admins:
            if admin.email and admin.email != assigned_admin.email:
                grp_body = create_ticket_assigned_group_email_body(ticket, assignment, assigned_admin, admin)
                grp_html = create_ticket_assigned_group_html_body(ticket, assignment, assigned_admin, admin)
                send_email_alert_async(admin.email, subject, grp_body, grp_html)
    except Exception as e:
        logger.warning(f"Could not load admins for assignment group notification: {e}")

def send_ticket_status_changed_notification(ticket, old_status, new_status, admins):
    """
    Send notification when ticket status changes
    
    Args:
        ticket: Ticket object
        old_status: Previous status
        new_status: New status
        admins: List of admin users
    """
    if not EMAIL_CONFIG["enabled"] or not admins or not NOTIFICATION_TRIGGERS.get("status_changed", True):
        return
        
    subject = f"Ticket Status Updated: #{ticket.id} - {old_status} → {new_status}"
    
    relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
    assigned = ticket.assignment.user if (ticket.assignment and ticket.assignment.user and ticket.assignment.user.email) else None
    if assigned:
        body = create_status_change_email_body(ticket, old_status, new_status, assigned)
        html_body = create_status_change_html_body(ticket, old_status, new_status, assigned)
        send_email_alert_async(assigned.email, subject, body, html_body)
    for admin in relevant_admins:
        if admin.email and (not assigned or admin.email != assigned.email):
            body = create_status_change_email_body(ticket, old_status, new_status, admin)
            html_body = create_status_change_html_body(ticket, old_status, new_status, admin)
            send_email_alert_async(admin.email, subject, body, html_body)

def send_ticket_comment_notification(ticket, comment, comment_author, admins):
    """
    Send notification when a comment is added to a ticket
    
    Args:
        ticket: Ticket object
        comment: Comment text
        comment_author: User who added the comment
        admins: List of admin users
    """
    if not EMAIL_CONFIG["enabled"] or not admins or not NOTIFICATION_TRIGGERS.get("comment_added", True):
        return
        
    subject = f"New Comment on Ticket #{ticket.id}: {ticket.title}"
    
    if comment_author.accountType != 'admin':
        relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
        for admin in relevant_admins:
            if admin.email:
                body = create_comment_email_body(ticket, comment, comment_author, admin)
                html_body = create_comment_html_body(ticket, comment, comment_author, admin)
                send_email_alert_async(admin.email, subject, body, html_body)

def filter_admins_by_ticket_type(ticket_type, admins):
    """
    Enhanced admin filtering based on ticket type using admin groups configuration
    
    Args:
        ticket_type: Type of the ticket
        admins: List of all admin users
    
    Returns:
        List of relevant admin users with logging
    """
    if not admins:
        logger.warning("No admin users provided for notification filtering")
        return []
    
    if not ticket_type:
        logger.warning("No ticket type provided, sending to all admins")
        return admins
    
    relevant_admins = []
    super_admins = []
    it_admins = []
    hardware_admins = []
    
    for admin in admins:
        admin_code = getattr(admin, 'admin_code', None)
        admin_name = f"{admin.first_name} {admin.last_name or ''}".strip()
        
        if not admin.email:
            logger.warning(f"Admin {admin_name} (code: {admin_code}) has no email address - skipping")
            continue
            
        if admin_code == '1236':  # Super Admin
            super_admins.append(admin)
            relevant_admins.append(admin)
        elif admin_code == '1235':  # Hardware Admin
            hardware_admins.append(admin)
        elif admin_code == '1234':  # IT Admin
            it_admins.append(admin)
        else:
            logger.warning(f"Admin {admin_name} has unknown admin_code: {admin_code}")
    
    ticket_group = determine_ticket_group(ticket_type)
    
    if ticket_group == 'hardware':
        relevant_admins.extend(hardware_admins)
        logger.info(f"Ticket type '{ticket_type}' -> Hardware Admin Group + Super Admins")
    elif ticket_group == 'it':
        relevant_admins.extend(it_admins)
        logger.info(f"Ticket type '{ticket_type}' -> IT Admin Group + Super Admins")
    else:
        relevant_admins.extend(it_admins)
        relevant_admins.extend(hardware_admins)
        logger.warning(f"Unknown ticket type '{ticket_type}' -> Sending to ALL admin groups")
    
    admin_names = [f"{admin.first_name} {admin.last_name or ''}".strip() for admin in relevant_admins]
    logger.info(f"Email notifications will be sent to: {', '.join(admin_names)}")
    
    return relevant_admins if relevant_admins else admins

def determine_ticket_group(ticket_type):
    """
    Determine which admin group should handle a specific ticket type
    
    Args:
        ticket_type: The type of the ticket
        
    Returns:
        'it', 'hardware', or 'unknown'
    """
    if not ticket_type:
        return 'unknown'
    
    for group_name, group_config in ADMIN_GROUPS.items():
        if group_name == 'super':
            continue
            
        group_ticket_types = group_config.get('ticket_types', [])
        if isinstance(group_ticket_types, list):
            if any(ticket_type.lower() == t.lower() for t in group_ticket_types):
                return group_name
    
    logger.warning(f"Ticket type '{ticket_type}' not found in any admin group configuration")
    return 'unknown'

def get_admin_group_summary():
    """
    Get a summary of current admin group configuration for debugging
    
    Returns:
        Dictionary with group information
    """
    summary = {}
    for group_name, group_config in ADMIN_GROUPS.items():
        summary[group_name] = {
            'name': group_config.get('name', group_name),
            'admin_codes': group_config.get('admin_codes', []),
            'ticket_count': len(group_config.get('ticket_types', [])) if isinstance(group_config.get('ticket_types'), list) else 'all',
            'description': group_config.get('description', 'No description')
        }
    return summary

def create_ticket_created_email_body(ticket, admin):
    """Create plain text email body for ticket creation"""
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {admin.first_name} {admin.last_name or ''},

A new ticket has been created in the ticketing system.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Description: {ticket.desc}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Created on: {server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}
- Project: {ticket.project or 'N/A'}
- Project Manager: {ticket.project_manager or 'N/A'}
- Location: {ticket.location or 'N/A'}
- Cubical: {ticket.cubical or 'N/A'}
- Request Type: {ticket.ticket_type or 'N/A'}
- Status: {ticket.status or 'Pending'}

Please log into the admin dashboard to assign and manage this ticket.

Best regards,
Ticketing System
    """

def create_ticket_created_html_body(ticket, admin):
    """Create HTML email body for ticket creation"""
    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 10px;">
                New Ticket Created
            </h2>
            
            <p>Hello <strong>{admin.first_name} {admin.last_name or ''}</strong>,</p>
            
            <p>A new ticket has been created in the ticketing system.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="color: #2c5aa0; margin-top: 0;">Ticket Details:</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{ticket.desc}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created by:</td><td>{ticket.username}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created on:</td><td>{server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Project:</td><td>{ticket.project or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Project Manager:</td><td>{ticket.project_manager or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Location:</td><td>{ticket.location or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Cubical:</td><td>{ticket.cubical or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Request Type:</td><td>{ticket.ticket_type or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Status:</td>
                        <td><span style="background-color: #ffc107; padding: 2px 8px; border-radius: 3px; color: #000;">{ticket.status or 'Pending'}</span></td></tr>
                </table>
            </div>
            
            <p style="margin-top: 20px;">Please log into the admin dashboard to assign and manage this ticket.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def create_ticket_assigned_email_body(ticket, assignment, assigned_admin):
    """Create plain text email body for ticket assignment"""
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {assigned_admin.first_name} {assigned_admin.last_name or ''},

A ticket has been assigned to you in the ticketing system.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Description: {ticket.desc}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Created on: {server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}
- Project: {ticket.project or 'N/A'}
- Location: {ticket.location or 'N/A'}
- Request Type: {ticket.ticket_type or 'N/A'}
- Status: {assignment.status}
- Assigned on: {server_local_format(assignment.assigned_date, '%d-%m-%Y %I:%M %p') if assignment.assigned_date else 'N/A'}

{f"- Closed on: {server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}" if assignment.status == 'Closed' else ""}

{f"Admin Comment: {assignment.comment}" if assignment.comment else ""}

Please review and take appropriate action on this ticket.

Best regards,
Ticketing System
    """

def _parse_admin_comment_blocks(comment_lines):
    """Group comment lines into individual admin comment entries."""
    blocks = []
    current_block = []
    for line in comment_lines:
        header_match = line.startswith('---[') and ']' in line
        if header_match:
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)
    return blocks


def _build_comment_entry_block(block_lines):
    """Build an HTML block for a single admin comment entry."""
    header = block_lines[0] if block_lines else ""
    content = block_lines[1:] if len(block_lines) > 1 else []

    timestamp = ""
    author = "Admin"
    if header.startswith('---['):
        end_ts = header.find(']')
        if end_ts != -1:
            timestamp = header[4:end_ts]
            author = header[end_ts + 1:].strip('- ') or author

    body_text = '\n'.join(content).strip()
    if not body_text:
        body_text = "No additional details provided."

    return f"""
        <div style="border-top: 1px solid #c8dbf4;">
            <div style="background-color: #2c5aa0; color: #fff; padding: 10px 15px; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600;">{author}</span>
                <span style="font-size: 12px;">{timestamp}</span>
            </div>
            <div style="background-color: #fff; padding: 15px; color: #333; white-space: pre-wrap;">
                {body_text}
            </div>
        </div>
    """


def create_ticket_assigned_html_body(ticket, assignment, assigned_admin):
    """Create HTML email body for ticket assignment"""
    comment_section = ""
    if assignment.comment and assignment.comment.strip():
        formatted_comment = assignment.comment.strip()
        comment_lines = [line.rstrip() for line in formatted_comment.splitlines() if line.strip()]
        if comment_lines:
            blocks = _parse_admin_comment_blocks(comment_lines)
            if blocks:
                # Extract just the text from the latest comment block
                latest_block_lines = blocks[-1]
                latest_comment_text = '\n'.join(latest_block_lines[1:]).strip() if len(latest_block_lines) > 1 else ""
                if latest_comment_text:
                    comment_section = f"""
                    <div style="background-color: #e9f2fb; padding: 15px; border-radius: 5px; border-left: 4px solid #2c5aa0; margin-top: 20px;">
                        <h4 style="margin-top: 0; color: #2c5aa0;">Latest Admin Comment:</h4>
                        <p style="margin-bottom: 0; white-space: pre-wrap; font-size: 14px;">{latest_comment_text}</p>
                    </div>
                    """

    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 10px;">
                Ticket Assigned to You
            </h2>
            
            <p>Hello <strong>{assigned_admin.first_name} {assigned_admin.last_name or ''}</strong>,</p>
            
            <p>A ticket has been assigned to you in the ticketing system.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="color: #28a745; margin-top: 0;">Ticket Details:</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{ticket.desc}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created by:</td><td>{ticket.username}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created on:</td><td>{server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Project:</td><td>{ticket.project or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Location:</td><td>{ticket.location or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Request Type:</td><td>{ticket.ticket_type or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Status:</td><td><span style="background-color: #17a2b8; padding: 2px 8px; border-radius: 3px; color: #fff;">{assignment.status}</span></td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Assigned on:</td><td>{server_local_format(assignment.assigned_date, '%d-%m-%Y %I:%M %p') if assignment.assigned_date else 'N/A'}</td></tr>
                    {f"<tr><td style='padding: 5px 0; font-weight: bold;'>Closed on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>" if assignment.status == 'Closed' else ""}
                </table>
            </div>
            
            {comment_section}
            
            <p style="margin-top: 20px;">Please review and take appropriate action on this ticket.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def create_ticket_assigned_group_email_body(ticket, assignment, assigned_admin, recipient_admin):
    """Plain text email body for notifying other admins about an assignment"""
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {recipient_admin.first_name} {recipient_admin.last_name or ''},

A ticket has been assigned to {assigned_admin.first_name} {assigned_admin.last_name or ''} in the ticketing system.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Description: {ticket.desc}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Created on: {server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}
- Project: {ticket.project or 'N/A'}
- Location: {ticket.location or 'N/A'}
- Request Type: {ticket.ticket_type or 'N/A'}
- Status: {assignment.status}
- Assigned on: {server_local_format(assignment.assigned_date, '%d-%m-%Y %I:%M %p') if assignment.assigned_date else 'N/A'}

Please review and take appropriate action on this ticket if needed.

Best regards,
Ticketing System
    """

def create_ticket_assigned_group_html_body(ticket, assignment, assigned_admin, recipient_admin):
    """Create HTML email body for notifying other admins about an assignment"""
    comment_section = ""
    if assignment.comment and assignment.comment.strip():
        formatted_comment = assignment.comment.strip()
        comment_lines = [line.rstrip() for line in formatted_comment.splitlines() if line.strip()]
        if comment_lines:
            blocks = _parse_admin_comment_blocks(comment_lines)
            if blocks:
                # Extract just the text from the latest comment block
                latest_block_lines = blocks[-1]
                latest_comment_text = '\n'.join(latest_block_lines[1:]).strip() if len(latest_block_lines) > 1 else ""
                if latest_comment_text:
                    comment_section = f"""
                    <div style="background-color: #e9f2fb; padding: 15px; border-radius: 5px; border-left: 4px solid #2c5aa0; margin-top: 20px;">
                        <h4 style="margin-top: 0; color: #2c5aa0;">Latest Admin Comment:</h4>
                        <p style="margin-bottom: 0; white-space: pre-wrap; font-size: 14px;">{latest_comment_text}</p>
                    </div>
                    """



    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 10px;">
                Ticket Assigned in Your Group
            </h2>
            
            <p>Hello <strong>{recipient_admin.first_name} {recipient_admin.last_name or ''}</strong>,</p>
            
            <p>
                A ticket has been assigned to <strong>{assigned_admin.first_name} {assigned_admin.last_name or ''}</strong> in the ticketing system.
            </p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="color: #28a745; margin-top: 0;">Ticket Details:</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{ticket.desc}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created by:</td><td>{ticket.username}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created on:</td><td>{server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Project:</td><td>{ticket.project or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Location:</td><td>{ticket.location or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Request Type:</td><td>{ticket.ticket_type or 'N/A'}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Status:</td><td><span style="background-color: #17a2b8; padding: 2px 8px; border-radius: 3px; color: #fff;">{assignment.status}</span></td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Assigned on:</td><td>{server_local_format(assignment.assigned_date, '%d-%m-%Y %I:%M %p') if assignment.assigned_date else 'N/A'}</td></tr>
                </table>
            </div>
            
            {comment_section}
            
            <p style="margin-top: 20px;">Please review and take appropriate action on this ticket if needed.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def create_status_change_email_body(ticket, old_status, new_status, admin):
    """Create plain text email body for status change"""
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {admin.first_name} {admin.last_name or ''},

The status of ticket #{ticket.id} has been updated.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Created on: {server_local_format(ticket.date, '%d-%m-%Y %I:%M %p')}
- Previous Status: {old_status}
- New Status: {new_status}
- Updated on: {server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}

{f"- Closed on: {server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}" if new_status == 'Closed' else ""}

Please check the admin dashboard for more details.

Best regards,
Ticketing System
    """

def create_status_change_html_body(ticket, old_status, new_status, admin):
    """Create HTML email body for status change"""
    status_color = {
        'Pending': '#ffc107',
        'In Progress': '#17a2b8', 
        'Solved': '#28a745',
        'Closed': '#6c757d'
    }
    
    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #17a2b8; border-bottom: 2px solid #17a2b8; padding-bottom: 10px;">
                Ticket Status Updated
            </h2>
            
            <p>Hello <strong>{admin.first_name} {admin.last_name or ''}</strong>,</p>
            
            <p>The status of ticket #{ticket.id} has been updated.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created by:</td><td>{ticket.username}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Previous Status:</td><td><span style="background-color: {status_color.get(old_status, '#6c757d')}; padding: 2px 8px; border-radius: 3px; color: #fff;">{old_status}</span></td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">New Status:</td><td><span style="background-color: {status_color.get(new_status, '#6c757d')}; padding: 2px 8px; border-radius: 3px; color: #fff;">{new_status}</span></td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Updated on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>
                    {f"<tr><td style='padding: 5px 0; font-weight: bold;'>Closed on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>" if new_status == 'Closed' else ""}
                </table>
            </div>
            
            <p style="margin-top: 20px;">Please check the admin dashboard for more details.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def create_comment_email_body(ticket, comment, comment_author, admin):
    """Create plain text email body for new comment"""
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {admin.first_name} {admin.last_name or ''},

A new comment has been added to ticket #{ticket.id}.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Comment by: {comment_author.first_name} {comment_author.last_name or ''}
- Comment: {comment}
- Added on: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}

Please review the comment and take appropriate action.

Best regards,
Ticketing System
    """

def create_comment_html_body(ticket, comment, comment_author, admin):
    """Create HTML email body for new comment"""
    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #fd7e14; border-bottom: 2px solid #fd7e14; padding-bottom: 10px;">
                New Comment Added
            </h2>
            
            <p>Hello <strong>{admin.first_name} {admin.last_name or ''}</strong>,</p>
            
            <p>A new comment has been added to ticket #{ticket.id}.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Created by:</td><td>{ticket.username}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Comment by:</td><td>{comment_author.first_name} {comment_author.last_name or ''}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Added on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>
                </table>
            </div>
            
            <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #fd7e14;">
                <h4 style="margin-top: 0; color: #fd7e14;">Comment:</h4>
                <p style="margin-bottom: 0; white-space: pre-wrap;">{comment}</p>
            </div>
            
            <p style="margin-top: 20px;">Please review the comment and take appropriate action.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def create_admin_comment_email_body(ticket, comment, admin, user):
    """Create plain text email body for admin comment to user"""
    admin_name = f"{admin.first_name} {admin.last_name or ''}".strip() if admin else 'Admin'
    user_name = f"{user.first_name} {user.last_name or ''}".strip() if user else 'User'
    employee_id = _get_employee_id(ticket)
    return f"""
Hello {user_name},

An administrator has added a new comment to your ticket #{ticket.id}.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Employee ID: {employee_id}
- Comment by: {admin_name}
- Comment: {comment}
- Added on: {server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}

Please review the comment and take appropriate action or reply if needed from your tickets page.

Best regards,
Ticketing System
    """

def create_admin_comment_html_body(ticket, comment, admin, user):
    """Create HTML email body for admin comment to user (mirrors user->admin style)"""
    admin_name = f"{admin.first_name} {admin.last_name or ''}".strip() if admin else 'Admin'
    user_name = f"{user.first_name} {user.last_name or ''}".strip() if user else 'User'
    employee_id = _get_employee_id(ticket)
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #fd7e14; border-bottom: 2px solid #fd7e14; padding-bottom: 10px;">
                New Comment Added
            </h2>
            
            <p>Hello <strong>{user_name}</strong>,</p>
            
            <p>An administrator has added a new comment to your ticket #{ticket.id}.</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Comment by:</td><td>{admin_name}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Added on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>
                </table>
            </div>
            
            {f'''
                <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #fd7e14; margin-top: 20px;">
                    <h4 style="margin-top: 0; color: #c67c00;">Comment:</h4>
                    <p style="margin-bottom: 0; white-space: pre-wrap; font-size: 14px;">{comment}</p>
                </div>
            ''' if comment and comment.strip() else ""}
            
            <p style="margin-top: 20px;">
                Please log into your account and open the ticket to reply or review further details.
            </p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def send_admin_comment_notification(ticket, comment, admin, user):
    """Send an email to the ticket owner when an admin adds/updates a comment"""
    if not EMAIL_CONFIG.get("enabled", False):
        return False
    if not user or not getattr(user, 'email', None):
        logger.warning("Ticket owner has no email - skipping admin comment notification")
        return False
    subject = f"New Admin Comment on Ticket #{ticket.id}: {ticket.title}"
    body = create_admin_comment_email_body(ticket, comment, admin, user)
    html_body = create_admin_comment_html_body(ticket, comment, admin, user)
    return send_email_alert_async(user.email, subject, body, html_body)

def send_admin_group_comment_notification(ticket, comment, author_admin, admins):
    """Send an email to other admins in the group when an admin adds a comment."""
    if not EMAIL_CONFIG.get("enabled", False):
        return False
    
    subject = f"New Admin Comment on Ticket #{ticket.id}: {ticket.title}"
    
    # Filter to get relevant admins, excluding the author
    relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
    
    for recipient_admin in relevant_admins:
        if recipient_admin.email and recipient_admin.id != author_admin.id:
            body = create_admin_group_comment_email_body(ticket, comment, author_admin, recipient_admin)
            html_body = create_admin_group_comment_html_body(ticket, comment, author_admin, recipient_admin)
            send_email_alert_async(recipient_admin.email, subject, body, html_body)
    
    return True

def create_admin_group_comment_email_body(ticket, comment, author_admin, recipient_admin):
    """Create plain text email body for admin-to-admin comment notification."""
    author_name = f"{author_admin.first_name} {author_admin.last_name or ''}".strip()
    recipient_name = f"{recipient_admin.first_name} {recipient_admin.last_name or ''}".strip()
    employee_id = _get_employee_id(ticket)
    
    return f"""
Hello {recipient_name},

A new comment has been added by {author_name} to ticket #{ticket.id}.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Comment by: {author_name}
- Added on: {server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}

Comment:
{comment}

Please review the comment in the admin dashboard.

Best regards,
Ticketing System
    """

def create_admin_group_comment_html_body(ticket, comment, author_admin, recipient_admin):
    """Create HTML email body for admin-to-admin comment notification with blue theme."""
    author_name = f"{author_admin.first_name} {author_admin.last_name or ''}".strip()
    recipient_name = f"{recipient_admin.first_name} {recipient_admin.last_name or ''}".strip()
    employee_id = _get_employee_id(ticket)
    
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0; border-bottom: 2px solid #2c5aa0; padding-bottom: 10px;">
                New Admin Comment Added
            </h2>
            <p>Hello <strong>{recipient_name}</strong>,</p>
            <p>A new comment has been added by <strong>{author_name}</strong> to ticket #{ticket.id}.</p>
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Comment by:</td><td>{author_name}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Added on:</td><td>{server_local_format(datetime.now(), '%d-%m-%Y %I:%M %p')}</td></tr>
                </table>
            </div>
            <div style="background-color: #e9f2fb; padding: 15px; border-radius: 5px; border-left: 4px solid #2c5aa0; margin-top: 20px;">
                <h4 style="margin-top: 0; color: #2c5aa0;">Comment:</h4>
                <p style="margin-bottom: 0; white-space: pre-wrap; font-size: 14px;">{comment}</p>
            </div>
            <p style="margin-top: 20px;">Please review the comment in the admin dashboard.</p>
        </div>
    </body>
    </html>
    """

def create_ticket_reopened_email_body(ticket, user, reason, admin):
    """Create plain text email body for ticket reopen notification"""
    user_name = f"{user.first_name} {user.last_name or ''}".strip() if user else ticket.username
    employee_id = _get_employee_id(ticket)
    admin_name = f"{admin.first_name} {admin.last_name or ''}".strip() if admin else 'Admin'
    
    return f"""
[Warning !] Exercise caution – External Mail.

Hello {admin_name},

Ticket #{ticket.id} ({ticket.title}) has been REOPENED by the user.
Original Status: Closed
User: {user_name}
Employee ID: {employee_id}
Reason for reopening: {reason}

Ticket ID: #{ticket.id}
Title: {ticket.title}
User: {user_name}
Employee ID: {employee_id}
Reopened on: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}

Reason for reopening:
{reason}

Please review this ticket in the admin dashboard and provide additional support.

Best regards,
Ticketing System
    """

def create_ticket_reopened_html_body(ticket, user, reason, admin):
    """Create HTML email body for ticket reopen notification (matching the New Comment Added style exactly)"""
    user_name = f"{user.first_name} {user.last_name or ''}".strip() if user else ticket.username
    admin_name = f"{admin.first_name} {admin.last_name or ''}".strip() if admin else 'Admin'
    employee_id = _get_employee_id(ticket)
    
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            
            <h2 style="color: #fd7e14; border-bottom: 2px solid #fd7e14; padding-bottom: 10px; margin-bottom: 25px;">
                Ticket Reopened - Action Required
            </h2>
            
            <p>Hello <strong>{admin_name}</strong>,</p>
            
            <p>Ticket #{ticket.id} ({ticket.title}) has been <strong>REOPENED</strong> by the user.</p>
            <p><strong>Original Status:</strong> Closed</p>
            <p><strong>User:</strong> {user_name}</p>
            <p><strong>Reason for reopening:</strong> {reason}</p>
            
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px 0; font-weight: bold; width: 150px;">Ticket ID:</td><td>#{ticket.id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Title:</td><td>{ticket.title}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">User:</td><td>{user_name}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Employee ID:</td><td>{employee_id}</td></tr>
                    <tr><td style="padding: 5px 0; font-weight: bold;">Reopened on:</td><td>{datetime.now().strftime('%d-%m-%Y %I:%M %p')}</td></tr>
                </table>
            </div>
            
            <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #fd7e14;">
                <h4 style="margin-top: 0; color: #fd7e14;">Reason for reopening:</h4>
                <p style="margin-bottom: 0; white-space: pre-wrap;">{reason}</p>
            </div>
            
            <p style="margin-top: 20px;">Please review this ticket in the admin dashboard and provide additional support.</p>
            
            <p style="margin-top: 20px; color: #666;">
                Best regards,<br>
                Ticketing System
            </p>
        </div>
    </body>
    </html>
    """

def send_ticket_reopened_notification(ticket, user, reason, admins):
    """
    Send notification when a ticket is reopened by a user
    
    Args:
        ticket: Ticket object
        user: User who reopened the ticket
        reason: Reason for reopening
        admins: List of admin users who should receive notification
    """
    if not EMAIL_CONFIG["enabled"] or not admins or not NOTIFICATION_TRIGGERS.get("ticket_reopened", True):
        return
        
    subject = f"[External] REOPENED: Ticket #{ticket.id} - Action Required"
    
    relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
    
    for admin in relevant_admins:
        if admin.email:
            body = create_ticket_reopened_email_body(ticket, user, reason, admin)
            html_body = create_ticket_reopened_html_body(ticket, user, reason, admin)
            send_email_alert_async(admin.email, subject, body, html_body)

def send_email_notification(*args, **kwargs):
    """Backward compatibility wrapper"""
    return send_email_alert(*args, **kwargs)

def test_admin_group_configuration(admins=None):
    """
    Test and display the current admin group configuration
    
    Args:
        admins: List of admin users (optional, will query if not provided)
    
    Returns:
        Dictionary with test results
    """
    if admins is None:
        try:
            from .models import User
            admins = User.query.filter_by(accountType="admin").all()
        except ImportError:
            return {"error": "Cannot import User model for testing"}
    
    results = {
        "group_config": get_admin_group_summary(),
        "admin_users": [],
        "ticket_type_tests": [],
        "warnings": []
    }
    
    for admin in admins:
        admin_info = {
            "name": f"{admin.first_name} {admin.last_name or ''}".strip(),
            "email": admin.email,
            "admin_code": getattr(admin, 'admin_code', None),
            "group": "unknown"
        }
        
        admin_code = getattr(admin, 'admin_code', None)
        if admin_code == '1236':
            admin_info["group"] = "super"
        elif admin_code == '1235':
            admin_info["group"] = "hardware"
        elif admin_code == '1234':
            admin_info["group"] = "it"
        
        if not admin.email:
            results["warnings"].append(f"Admin {admin_info['name']} has no email address")
        
        results["admin_users"].append(admin_info)
    
    sample_tickets = [
        "Laptop", "Printer Request", "Desktop", "Cartridge Request",
        "Network issues", "Printer Issue", "Unknown Ticket Type"
    ]
    
    for ticket_type in sample_tickets:
        filtered_admins = filter_admins_by_ticket_type(ticket_type, admins)
        recipient_names = [f"{admin.first_name} {admin.last_name or ''}".strip() for admin in filtered_admins]
        
        results["ticket_type_tests"].append({
            "ticket_type": ticket_type,
            "recipients": recipient_names,
            "count": len(filtered_admins)
        })
    
    return results

def send_test_notifications(test_ticket_types=None):
    """
    Send test email notifications for different ticket types
    
    Args:
        test_ticket_types: List of ticket types to test (optional)
    
    Returns:
        Results of test notifications
    """
    if not EMAIL_CONFIG.get("enabled", False):
        return {"error": "Email notifications are disabled in configuration"}
    
    if test_ticket_types is None:
        test_ticket_types = ["Laptop", "Printer Request", "Network issues"]
    
    try:
        from .models import User
        admins = User.query.filter_by(accountType="admin").all()
    except ImportError:
        return {"error": "Cannot import User model for testing"}
    
    results = []
    
    for ticket_type in test_ticket_types:
        relevant_admins = filter_admins_by_ticket_type(ticket_type, admins)
        
        sent_count = 0
        for admin in relevant_admins:
            if admin.email:
                subject = f"TEST: Admin Group Notification - {ticket_type}"
                body = f"""
This is a TEST email notification for the enhanced admin group system.

Test Details:
- Ticket Type: {ticket_type}
- Your Admin Code: {getattr(admin, 'admin_code', 'N/A')}
- Your Group: {get_admin_group_by_code(getattr(admin, 'admin_code', None))}
- Test Time: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}

If you received this email, the admin group notification system is working correctly for your group.

This is an automated test - no action required.
                """
                
                if send_email_alert_async(admin.email, subject, body):
                    sent_count += 1
        
        results.append({
            "ticket_type": ticket_type,
            "targeted_admins": len(relevant_admins),
            "emails_sent": sent_count,
            "success": sent_count > 0
        })
    
    return results

def get_admin_group_by_code(admin_code):
    """
    Get the group name for an admin code
    
    Args:
        admin_code: The admin code to look up
        
    Returns:
        Group name or 'unknown'
    """
    for group_name, group_config in ADMIN_GROUPS.items():
        if admin_code in group_config.get('admin_codes', []):
            return group_config.get('name', group_name)
    return 'unknown'

def validate_admin_group_setup():
    """
    Validate the admin group setup and return any issues
    
    Returns:
        Dictionary with validation results
    """
    issues = []
    warnings = []
    
    if not ADMIN_GROUPS:
        issues.append("ADMIN_GROUPS configuration is empty or missing")
        return {"issues": issues, "warnings": warnings, "valid": False}
    
    required_groups = ['it', 'hardware', 'super']
    for group in required_groups:
        if group not in ADMIN_GROUPS:
            issues.append(f"Missing required admin group: {group}")
        else:
            group_config = ADMIN_GROUPS[group]
            if 'admin_codes' not in group_config:
                issues.append(f"Group '{group}' missing admin_codes configuration")
            if 'ticket_types' not in group_config:
                warnings.append(f"Group '{group}' missing ticket_types configuration")
    
    all_codes = []
    for group_name, group_config in ADMIN_GROUPS.items():
        codes = group_config.get('admin_codes', [])
        for code in codes:
            if code in all_codes:
                warnings.append(f"Admin code '{code}' appears in multiple groups")
            else:
                all_codes.append(code)
    
    return {
        "issues": issues,
        "warnings": warnings,
        "valid": len(issues) == 0,
        "total_admin_codes": len(all_codes)
    }

def send_ticket_assignment_notification(ticket, assigned_user, assigning_admin, comment=None):
    """
    Send email notification when a ticket is assigned to an admin
    
    Args:
        ticket: The ticket object
        assigned_user: The admin user the ticket is assigned to
        assigning_admin: The admin who is doing the assignment
        comment: Optional comment from the assigning admin
    """
    if not EMAIL_CONFIG.get("enabled", False):
        logger.info("Email notifications are disabled")
        return {"success": False, "reason": "Email disabled"}
    
    if not NOTIFICATION_TRIGGERS.get("ticket_assigned", False):
        logger.info("Ticket assignment notifications are disabled")
        return {"success": False, "reason": "Assignment notifications disabled"}
    
    if not assigned_user.email:
        logger.warning(f"Assigned user {assigned_user.first_name} {assigned_user.last_name} has no email address")
        return {"success": False, "reason": "No email address"}
    
    try:
        subject = f"Ticket #{ticket.id} Assigned to You - {ticket.title}"
        
        assigning_admin_name = f"{assigning_admin.first_name} {assigning_admin.last_name or ''}".strip()
        assigned_user_name = f"{assigned_user.first_name} {assigned_user.last_name or ''}".strip()
        employee_id = _get_employee_id(ticket)
        
        body = f"""
Hello {assigned_user_name},

A ticket has been assigned to you by {assigning_admin_name}.

Ticket Details:
- Ticket ID: #{ticket.id}
- Title: {ticket.title}
- Description: {ticket.desc}
- Created by: {ticket.username}
- Employee ID: {employee_id}
- Project: {ticket.project or 'N/A'}
- Location: {ticket.location or 'N/A'}
- Request Type: {ticket.ticket_type or 'N/A'}
- Category: {ticket.category or 'N/A'}
- Status: {ticket.status or 'Pending'}
"""
        
        if comment:
            body += f"\nAssignment Comment:\n{comment}\n"
        
        body += """
Please log into the admin dashboard to manage this ticket.

Best regards,
Ticketing System
        """
        
        class _AssignCtx: pass
        _assign = _AssignCtx()
        _assign.status = ticket.status or "Pending"
        try:
            _assign.assigned_date = datetime.now()
        except Exception:
            _assign.assigned_date = None
        _assign.comment = comment or ""
        html_body = create_ticket_assigned_html_body(ticket, _assign, assigned_user)
        success = send_email_alert_async(assigned_user.email, subject, body, html_body)

        try:
            from .models import User
            admins = User.query.filter_by(accountType="admin").all()
            relevant_admins = filter_admins_by_ticket_type(ticket.ticket_type, admins)
            for admin in relevant_admins:
                if admin.email and admin.email != assigned_user.email:
                    grp_body = f"""
Hello {admin.first_name} {admin.last_name or ''},

Ticket #{ticket.id} - {ticket.title} has been assigned to {assigned_user_name} by {assigning_admin_name}.

Please check the admin dashboard for details.

Best regards,
Ticketing System
                    """
                    grp_html = create_ticket_assigned_group_html_body(ticket, _assign, assigned_user, admin)
                    send_email_alert_async(admin.email, subject, grp_body, grp_html)
        except Exception as e:
            logger.warning(f"Could not load admins for assignment group notification: {e}")
        
        if success:
            logger.info(f"Assignment notification sent to {assigned_user_name} ({assigned_user.email}) for ticket #{ticket.id}")
        else:
            logger.error(f"Failed to send assignment notification to {assigned_user_name} ({assigned_user.email}) for ticket #{ticket.id}")
        
        return {"success": bool(success)}
        
    except Exception as e:
        logger.error(f"Error sending ticket assignment notification: {str(e)}")
        return {"success": False, "error": str(e)}
