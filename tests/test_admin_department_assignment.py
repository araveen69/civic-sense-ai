import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import ActivityLog, Report, app, db


class AdminDepartmentAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['admin_id'] = 1
            session['admin_name'] = 'admin'

    def test_assigns_department_and_records_activity(self):
        report = SimpleNamespace(
            id=1,
            assigned_department='Sanitation Department',
            tracking_id='CIV-260101-ABCDE',
            category='pothole',
            priority_level='High',
        )
        report_query = MagicMock()
        report_query.get_or_404.return_value = report

        with app.app_context(), \
                patch.object(Report, 'query', report_query), \
                patch.object(db.session, 'add') as add, \
                patch.object(db.session, 'commit') as commit, \
                patch('app.notify_department') as notify:
            response = self.client.post(
                '/admin/assign_department/1',
                data={'department': 'Roads & Infrastructure Department'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['department'], 'Roads & Infrastructure Department')
        self.assertEqual(report.assigned_department, 'Roads & Infrastructure Department')
        self.assertIsInstance(add.call_args.args[0], ActivityLog)
        self.assertEqual(add.call_args.args[0].action,
                         'Department changed to Roads & Infrastructure Department')
        commit.assert_called_once()
        notify.assert_called_once_with(
            'Roads & Infrastructure Department', 'CIV-260101-ABCDE', 'pothole', 'High'
        )

    def test_rejects_department_not_in_configured_options(self):
        with app.app_context(), patch.object(Report, 'query') as report_query:
            response = self.client.post(
                '/admin/assign_department/1',
                data={'department': 'Unlisted Department'},
            )

        self.assertEqual(response.status_code, 400)
        report_query.get_or_404.assert_not_called()

    def test_requires_admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()

        response = self.client.post(
            '/admin/assign_department/1',
            data={'department': 'Roads & Infrastructure Department'},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
