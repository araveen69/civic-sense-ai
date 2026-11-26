import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import ActivityLog, Report, app


class ComplaintTimelineTests(unittest.TestCase):
    def test_tracking_page_shows_activity_in_chronological_order(self):
        report = SimpleNamespace(
            id=1,
            tracking_id='CS-123',
            image_path=None,
            category='pothole',
            status='In Progress',
            priority_level='High',
            ai_confidence=92,
            severity_score=0.8,
            assigned_department='Roads Department',
            location_address='Main Street',
            created_at=datetime(2026, 1, 2, 9, 0),
        )
        logs = [
            SimpleNamespace(
                action='Complaint submitted',
                performed_by='Reporter',
                timestamp=datetime(2026, 1, 2, 9, 0),
            ),
            SimpleNamespace(
                action='Status changed to In Progress',
                performed_by='admin',
                timestamp=datetime(2026, 1, 2, 10, 0),
            ),
        ]
        report_query = MagicMock()
        report_query.filter_by.return_value.first_or_404.return_value = report
        activity_query = MagicMock()
        activity_query.filter_by.return_value.order_by.return_value.all.return_value = logs

        with app.app_context(), \
                patch.object(Report, 'query', report_query), \
                patch.object(ActivityLog, 'query', activity_query):
            response = app.test_client().get('/track/CS-123')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Complaint activity timeline"', response.data)
        self.assertLess(
            response.data.index(b'Complaint submitted'),
            response.data.index(b'Status changed to In Progress'),
        )
        self.assertIn(b'Updated by admin', response.data)


if __name__ == '__main__':
    unittest.main()
