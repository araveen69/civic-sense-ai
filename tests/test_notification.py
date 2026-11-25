import unittest
from contextlib import redirect_stdout
from io import StringIO

from utils.notification import notify_department


class DepartmentNotificationTests(unittest.TestCase):
    def test_notifies_assigned_department_with_report_details(self):
        output = StringIO()

        with redirect_stdout(output):
            sent = notify_department('Roads Department', 'CS-123', 'pothole', 'High')

        self.assertTrue(sent)
        self.assertIn('Roads Department', output.getvalue())
        self.assertIn('CS-123', output.getvalue())


if __name__ == '__main__':
    unittest.main()
