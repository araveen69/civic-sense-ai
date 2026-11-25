"""Notification simulation module."""


def notify_department(department, tracking_id, category, priority):
    print(f"[NOTIFICATION] 📨 Alert sent to '{department}'")
    print(f"   -> Report {tracking_id} | Category: {category} | Priority: {priority}")
    return True