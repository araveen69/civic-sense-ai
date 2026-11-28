import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import app, geocoder


class ReportLocationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_coordinates_are_hidden_optional_form_fields(self):
        response = self.client.get('/report')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<input type="hidden" name="latitude" id="lat">', response.data)
        self.assertIn(b'<input type="hidden" name="longitude" id="lon">', response.data)
        self.assertIn(b'id="getLocationButton"', response.data)
        self.assertIn(b'Location is optional.', response.data)
        self.assertIn(b'data-reverse-geocode-url="/api/location/reverse"', response.data)

    def test_reverse_geocodes_coordinates_into_a_full_address(self):
        address = '1 Example Street, Bengaluru, Karnataka, India'
        with patch.object(
            geocoder,
            'reverse',
            return_value=SimpleNamespace(address=address)
        ) as reverse:
            response = self.client.post(
                '/api/location/reverse',
                json={'latitude': 12.9716, 'longitude': 77.5946}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'address': address})
        reverse.assert_called_once_with(
            (12.9716, 77.5946),
            exactly_one=True,
            language='en'
        )

    def test_rejects_out_of_range_coordinates(self):
        with patch.object(geocoder, 'reverse') as reverse:
            response = self.client.post(
                '/api/location/reverse',
                json={'latitude': 91, 'longitude': 77.5946}
            )

        self.assertEqual(response.status_code, 400)
        reverse.assert_not_called()


if __name__ == '__main__':
    unittest.main()
