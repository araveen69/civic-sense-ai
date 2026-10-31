"""
Notification simulation module.
In production, integrate with Twilio (SMS) / SMTP (Email) / FCM (push).
"""

def notify_department(department, tracking_id, category, priority):
    print(f"[NOTIFICATION] 📨 Alert sent to '{department}'")
    print(f"   -> Report {tracking_id} | Category: {category} | Priority: {priority}")
    return True


def notify_citizen(email, tracking_id, status):
    print(f"[NOTIFICATION] 📧 Email sent to {email}: Your report {tracking_id} is now '{status}'")
    return True