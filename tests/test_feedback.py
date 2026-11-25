import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import Feedback, Report, app


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_feedback_page_is_available_from_navigation(self):
        response = self.client.get('/feedback')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Share your feedback', response.data)
        self.assertIn(b'href="/feedback"', response.data)

    def test_valid_feedback_is_saved(self):
        with patch('app.db.session.add') as add, patch('app.db.session.commit') as commit:
            response = self.client.post('/feedback', data={
                'category': 'Suggestion',
                'rating': '5',
                'message': 'Please add a way to filter reports.',
                'name': 'Community member',
            })

        self.assertEqual(response.status_code, 302)
        saved_feedback = add.call_args.args[0]
        self.assertIsInstance(saved_feedback, Feedback)
        self.assertEqual(saved_feedback.category, 'Suggestion')
        self.assertEqual(saved_feedback.rating, 5)
        self.assertEqual(saved_feedback.message, 'Please add a way to filter reports.')
        self.assertEqual(saved_feedback.name, 'Community member')
        commit.assert_called_once_with()

    def test_invalid_feedback_is_not_saved(self):
        with patch('app.db.session.add') as add, patch('app.db.session.commit') as commit:
            response = self.client.post('/feedback', data={
                'category': 'Invalid',
                'rating': '8',
                'message': 'Not valid',
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please choose a valid feedback category.', response.data)
        add.assert_not_called()
        commit.assert_not_called()

    def test_invalid_rating_is_rejected(self):
        with patch('app.db.session.add') as add, patch('app.db.session.commit') as commit:
            response = self.client.post('/feedback', data={
                'category': 'General',
                'rating': 'not-a-rating',
                'message': 'The site was easy to use.',
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please select a rating from 1 to 5.', response.data)
        add.assert_not_called()
        commit.assert_not_called()

    def test_feedback_inbox_requires_admin_login(self):
        response = self.client.get('/admin/feedback')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/admin/login')

    def test_admin_can_view_feedback_inbox(self):
        feedback = SimpleNamespace(
            id=42,
            category='Suggestion',
            rating=5,
            message='Add more filters.',
            name='Community member',
            submitted_at=datetime(2026, 1, 1, 12, 0),
        )
        query = MagicMock()
        query.order_by.return_value.all.return_value = [feedback]
        with self.client.session_transaction() as browser_session:
            browser_session['admin_id'] = 1

        with app.app_context(), patch.object(Feedback, 'query', query):
            response = self.client.get('/admin/feedback')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Feedback Inbox', response.data)
        self.assertIn(b'Add more filters.', response.data)
        self.assertIn(b'Feedback #42', response.data)
        self.assertIn(b'Date: 2026-01-01', response.data)
        self.assertIn(b'Time: 12:00 PM', response.data)

    def test_admin_dashboard_shows_feedback_and_complaint_date_time(self):
        feedback = SimpleNamespace(
            id=43,
            category='Suggestion',
            rating=5,
            message='Please make the platform easier to navigate.',
            name='Community member',
            submitted_at=datetime(2026, 1, 1, 12, 0),
        )
        report = SimpleNamespace(
            id=1,
            tracking_id='CIV-260101-ABCDE',
            created_at=datetime(2026, 1, 2, 14, 35),
            image_path=None,
            category='pothole',
            priority_level='High',
            severity_score=8.5,
            assigned_department='Roads Department',
            status='Pending',
            reporter_name='Reporter',
            reporter_email='reporter@example.com',
        )
        report_query = MagicMock()
        report_query.order_by.return_value.all.return_value = [report]
        report_query.filter_by.return_value.count.return_value = 0
        feedback_query = MagicMock()
        feedback_query.order_by.return_value.limit.return_value.all.return_value = [feedback]
        with self.client.session_transaction() as browser_session:
            browser_session['admin_id'] = 1

        with app.app_context(), patch.object(Report, 'query', report_query), \
                patch.object(Feedback, 'query', feedback_query):
            response = self.client.get('/admin/dashboard')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'IMPROVE THE PLATFORM', response.data)
        self.assertIn(b'Please make the platform easier to navigate.', response.data)
        self.assertIn(b'View all feedback', response.data)
        self.assertIn(b'Feedback #43', response.data)
        self.assertIn(b'Date: 2026-01-01', response.data)
        self.assertIn(b'Time: 12:00 PM', response.data)
        self.assertIn(b'CIV-260101-ABCDE', response.data)
        self.assertIn(b'Date: 2026-01-02', response.data)
        self.assertIn(b'Time: 02:35 PM', response.data)


if __name__ == '__main__':
    unittest.main()
