import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import Report, app


class CivicAssistantTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_answers_reporting_questions(self):
        response = self.client.post(
            '/api/assistant',
            json={'question': 'How do I report a pothole?'}
        )

        self.assertEqual(response.status_code, 200)
        answer = response.get_json()['answer']
        self.assertIn('tracking ID', answer)
        self.assertIn('photo', answer)
        self.assertIn('required', answer)

    def test_assistant_widget_is_rendered_in_shared_layout(self):
        response = self.client.get('/admin/login')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="assistantLauncher"', response.data)
        self.assertIn(b'id="assistantPanel"', response.data)

    def test_looks_up_report_by_tracking_id(self):
        report = SimpleNamespace(
            tracking_id='CIV-240101-ABCDE',
            status='In Progress',
            priority_level='High',
            category='pothole',
            assigned_department='Roads Department',
            created_at=datetime(2024, 1, 1),
        )
        query = MagicMock()
        query.filter_by.return_value.first.return_value = report

        with app.app_context(), patch.object(Report, 'query', query):
            response = self.client.post(
                '/api/assistant',
                json={'question': 'What is the status of CIV-240101-ABCDE?'}
            )

        self.assertEqual(response.status_code, 200)
        answer = response.get_json()['answer']
        self.assertIn('In Progress', answer)
        self.assertIn('Roads Department', answer)
        self.assertIn('not a promised response time', answer)
        self.assertIn('activity timeline', answer)

    def test_explains_rejected_status_without_making_up_a_reason(self):
        response = self.client.post(
            '/api/assistant',
            json={'question': 'What does rejected mean?'}
        )

        self.assertEqual(response.status_code, 200)
        answer = response.get_json()['answer']
        self.assertIn('marked as rejected', answer)
        self.assertIn('reason may not be available', answer)

    def test_rejects_empty_questions(self):
        response = self.client.post('/api/assistant', json={'question': '  '})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Please enter a question', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
