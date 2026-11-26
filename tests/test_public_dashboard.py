import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import Report, app


class PublicDashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_dashboard_filters_sorts_and_paginates_reports(self):
        pagination = SimpleNamespace(
            items=[],
            total=20,
            page=2,
            pages=3,
            has_prev=True,
            has_next=True,
            prev_num=1,
            next_num=3,
        )
        query = MagicMock()
        query.filter.return_value = query
        query.filter_by.return_value = query
        query.order_by.return_value = query
        query.paginate.return_value = pagination

        with app.app_context(), patch.object(Report, 'query', query):
            response = self.client.get(
                '/dashboard?search=Main+Street&sort=recent&page=2'
                '&start_date=2026-01-01&end_date=2026-01-31'
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="Main Street"', response.data)
        self.assertIn(b'value="2026-01-01"', response.data)
        self.assertIn(b'value="2026-01-31"', response.data)
        self.assertIn(b'Page 2 of 3', response.data)
        self.assertIn(b'search=Main+Street', response.data)
        query.paginate.assert_called_once_with(page=2, per_page=9, error_out=False)
        self.assertEqual(query.filter.call_count, 3)

    def test_dashboard_rejects_invalid_date_range(self):
        response = self.client.get(
            '/dashboard?start_date=2026-02-01&end_date=2026-01-01'
        )

        self.assertEqual(response.status_code, 400)

    def test_stats_api_returns_trend_for_filtered_reports(self):
        query = MagicMock()
        query.filter.return_value = query
        query.filter_by.return_value = query
        query.count.return_value = 0
        query.with_entities.return_value.group_by.return_value.order_by.return_value.all.return_value = [
            ('2026-01-01', 2),
            ('2026-01-02', 1),
        ]

        with app.app_context(), patch.object(Report, 'query', query):
            response = self.client.get(
                '/api/stats?search=Main+Street&start_date=2026-01-01'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['trend'], {
            'dates': ['2026-01-01', '2026-01-02'],
            'counts': [2, 1],
        })
        self.assertEqual(query.filter.call_count, 2)


if __name__ == '__main__':
    unittest.main()
