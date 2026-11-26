import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import Report, app


class NotificationsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.report = SimpleNamespace(
            id=12,
            tracking_id='CS-123',
            category='street_light',
            location_address='Main Street',
            created_at=datetime(2026, 1, 2, 9, 30),
            reporter_name='Private Name',
            reporter_email='private@example.com',
        )

    def test_returns_recent_complaints_without_reporter_details(self):
        query = MagicMock()
        query.order_by.return_value.limit.return_value.all.return_value = [self.report]

        with app.app_context(), patch.object(Report, 'query', query):
            response = self.client.get('/api/notifications')

        self.assertEqual(response.status_code, 200)
        notification = response.get_json()['notifications'][0]
        self.assertEqual(notification, {
            'id': 12,
            'tracking_id': 'CS-123',
            'category': 'street_light',
            'location': 'Main Street',
            'created_at': 'Jan 02, 2026 09:30 AM UTC',
            'url': '/track/CS-123',
        })
        self.assertNotIn('reporter_name', notification)
        self.assertNotIn('reporter_email', notification)

    def test_returns_only_complaints_after_the_cursor(self):
        query = MagicMock()
        query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            self.report
        ]

        with app.app_context(), patch.object(Report, 'query', query):
            response = self.client.get('/api/notifications?after_id=11')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()['notifications'][0]['tracking_id'],
            'CS-123',
        )
        query.filter.assert_called_once()

    def test_rejects_invalid_notification_cursor(self):
        response = self.client.get('/api/notifications?after_id=invalid')

        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
