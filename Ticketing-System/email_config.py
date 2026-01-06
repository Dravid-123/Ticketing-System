"""
Email Configuration for Ticketing System
========================================

Simplified email configuration containing only essential settings.
The complex admin role configurations have been removed as they're not used.
"""

# Email Server Configuration
EMAIL_CONFIG = {
    # Gmail SMTP Configuration (recommended)
    "smtp_server": "NTDB.RDLTL.COM",
    "smtp_port": 25,
    "use_tls": True,
    "use_ssl": False,
    "use_auth": True,
    "sender_email": "emailadmin@gfad.com",
    "sender_password": "rdl@123",  # App Password, not regular password
    "timeout": 15,
    
    # Notification Settings
    "enabled": True,               # Set to False to disable all email notifications
    "debug": True                  # Set to True for detailed email logs
}

# Notification Triggers (controls which events send emails)
NOTIFICATION_TRIGGERS = {
    "ticket_created": True,        # Send email when ticket is created
    "ticket_assigned": True,       # Send email when ticket is assigned
    "status_changed": True,        # Send email when status changes
    "comment_added": True,         # Send email when user adds comment
    "ticket_reopened": True,       # Send email when ticket is reopened
    "ticket_closed": True,         # Send email when ticket is closed
    "ticket_solved": True          # Send email when ticket is marked solved
}

# Admin Groups Configuration (simplified)
ADMIN_GROUPS = {
    "it": {
        "admin_codes": ["1234"],
        "ticket_types": [
            "Laptop", "Desktop", "Workstation", "OS installation",
            "Network issues", "Network Request", "Private network", "New setup", "Software Installation",
            "Software Issue", "Server Issue", "Lan Ports Not working", "Adding users into Domain",
            "Port Request", "Fax Port Issue", "VOIP"
        ]
    },
    "hardware": {
        "admin_codes": ["1235"],
        "ticket_types": [
            "Printer Request", "Cartridge Request", "Printer Issue",
            "Paper Request", "Printer Movement Request", "Printer Movement to Wireless Lab"
        ]
    },
    "super": {
        "admin_codes": ["1236"],
        "ticket_types": "all"
    }
}

# Basic Admin Roles (simplified)
ADMIN_ROLES = {
    "1236": "Super Admin",
    "1235": "Hardware Admin", 
    "1234": "IT Admin"
}