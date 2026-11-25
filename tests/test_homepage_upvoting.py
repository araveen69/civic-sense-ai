import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import Report, app


class HomepageUpvotingTests(unittest.TestCase):
    def test_homepage_shows_active_report_upvote_controls(self):
        report = SimpleNamespace(
            id=12,
            category='pothole',
            tracking_id='CS-123',
            priority_level='Medium',
            status='Pending',
            upvotes=4,
            location_address='Main Street',
            image_path=None,
        )
        query = MagicMock()
        query.count.return_value = 1
        query.filter_by.return_value.count.return_value = 1
        query.order_by.return_value.limit.return_value.all.return_value = []
        query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [report]

        with app.app_context():
            with patch.object(Report, 'query', query):
                response = app.test_client().get('/')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'COMMUNITY UPVOTING', response.data)
        self.assertIn(b'Upvote (', response.data)
        self.assertIn(b'>4</span>', response.data)


if __name__ == '__main__':
    unittest.main()
