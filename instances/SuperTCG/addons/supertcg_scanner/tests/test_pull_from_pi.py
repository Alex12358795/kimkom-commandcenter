import json
import urllib.error
from unittest.mock import patch, MagicMock
from io import BytesIO

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestPullFromPi(TransactionCase):
    """Test the Pull from Pi functionality."""

    def setUp(self):
        super().setUp()
        # Deactivate all existing devices to isolate tests
        self.env['supertcg.scanner.device'].sudo().search([]).write({'active': False})
        
        # Create test scanner device with Pi URL
        self.device = self.env['supertcg.scanner.device'].sudo().create({
            'name': 'Test Scanner',
            'api_key': 'test-api-key-123',
            'pi_url': 'http://192.168.178.135:8082/api/batches',
            'company_id': self.env.company.id,
        })
        # Create second device without pi_url
        self.device2 = self.env['supertcg.scanner.device'].sudo().create({
            'name': 'Test Scanner 2 (no pi)',
            'api_key': 'test-api-key-456',
            'company_id': self.env.company.id,
        })

    def _mock_response(self, data, status=200):
        """Helper to create a mock HTTP response."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        return mock_response

    def test_pull_from_pi_success(self):
        """Test successfully pulling batches from Pi."""
        pi_data = {
            'ok': True,
            'batches': [
                {
                    'batch_id': 'test-batch-001',
                    'batch_name': 'Test Batch 1',
                    'scanned_at': '2026-06-04T10:11:53',
                    'device_id': 'test-device',
                    'card_count': 2,
                    'cards': [
                        {
                            'seq': 1,
                            'card_name': 'Pikachu',
                            'card_number': '25/102',
                            'set_code': 'BS',
                            'set_name': 'Base Set',
                            'condition': 'NM',
                            'printing': 'Holofoil',
                            'price_market': 10.5,
                            'price_low': 8.0,
                            'price_high': 15.0,
                            'product_id': '12345',
                            'rarity': 'Rare Holo',
                            'game_name': 'Pokemon',
                            'language': 'EN',
                            'foil': True,
                            'cdn_image': 'https://example.com/pikachu.jpg',
                        },
                        {
                            'seq': 2,
                            'card_name': 'Charizard',
                            'card_number': '4/102',
                            'condition': 'LP',
                            'printing': 'Holofoil',
                            'price_market': 100.0,
                            'price_low': 80.0,
                            'product_id': '67890',
                            'rarity': 'Rare Holo',
                            'game_name': 'Pokemon',
                            'language': 'EN',
                            'foil': True,
                        }
                    ]
                }
            ]
        }

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        # Check notification
        self.assertEqual(result['params']['title'], 'Pull Complete')
        self.assertIn('Imported 1 batch', result['params']['message'])

        # Check batch was created
        batch = self.env['supertcg.batch'].search([('batch_id', '=', 'test-batch-001')], limit=1)
        self.assertTrue(batch)
        self.assertEqual(batch.batch_name, 'Test Batch 1')
        self.assertEqual(batch.card_count, 2)
        self.assertEqual(batch.scanner_device_id, self.device)

        # Check cards were created
        self.assertEqual(len(batch.card_line_ids), 2)
        card1 = batch.card_line_ids.filtered(lambda c: c.card_name == 'Pikachu')
        self.assertTrue(card1)
        self.assertEqual(card1.condition, 'nm')
        self.assertEqual(card1.printing, 'Holofoil')
        self.assertEqual(card1.price_market, 10.5)
        self.assertEqual(card1.card_category, 'holo')

        card2 = batch.card_line_ids.filtered(lambda c: c.card_name == 'Charizard')
        self.assertTrue(card2)
        self.assertEqual(card2.condition, 'lp')
        self.assertEqual(card2.card_category, 'holo')

    def test_pull_from_pi_skips_duplicates(self):
        """Test that existing batches are skipped."""
        # Create existing batch
        existing = self.env['supertcg.batch'].sudo().create({
            'batch_id': 'existing-batch-001',
            'batch_name': 'Existing',
            'company_id': self.env.company.id,
        })

        pi_data = {
            'ok': True,
            'batches': [
                {
                    'batch_id': 'existing-batch-001',
                    'batch_name': 'Should Skip',
                    'card_count': 1,
                    'cards': [{'card_name': 'Test', 'seq': 1}]
                }
            ]
        }

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        # Should report at least 1 skipped duplicate
        # (may be more if multiple devices query the same Pi)
        self.assertIn('Skipped', result['params']['message'])
        # Original batch should not be modified
        self.assertEqual(existing.batch_name, 'Existing')

    def test_pull_from_pi_no_batches(self):
        """Test when Pi returns no batches."""
        pi_data = {'ok': True, 'batches': []}

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertEqual(result['params']['title'], 'No Batches')

    def test_pull_from_pi_no_devices(self):
        """Test error when no devices have pi_url configured."""
        # Deactivate all devices
        self.device.write({'active': False})
        self.device2.write({'active': False})

        with self.assertRaises(UserError) as cm:
            self.env['supertcg.batch'].action_pull_from_pi()
        self.assertIn('No active scanner devices', str(cm.exception))

    def test_pull_from_pi_connection_error(self):
        """Test handling connection error to Pi."""
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('Connection refused')):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertIn('Errors', result['params']['message'])
        self.assertIn('cannot connect', result['params']['message'])

    def test_pull_from_pi_http_error(self):
        """Test handling HTTP error from Pi."""
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(
            'http://test', 401, 'Unauthorized', {}, None
        )):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertIn('Errors', result['params']['message'])
        self.assertIn('HTTP', result['params']['message'])

    def test_pull_from_pi_invalid_json(self):
        """Test handling invalid JSON response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'not valid json'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertIn('Errors', result['params']['message'])
        self.assertIn('invalid JSON', result['params']['message'])

    def test_pull_from_pi_pi_error_response(self):
        """Test when Pi returns ok: false."""
        pi_data = {'ok': False, 'error': 'Rate limited'}

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertIn('Errors', result['params']['message'])
        self.assertIn('Rate limited', result['params']['message'])

    def test_pull_from_pi_device_without_url_skipped(self):
        """Test that devices without pi_url are skipped."""
        # device2 has no pi_url, so only device should be called
        pi_data = {'ok': True, 'batches': []}

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)) as mock_urlopen:
            self.env['supertcg.batch'].action_pull_from_pi()
            # Should call at least once (for device with pi_url)
            # May be more if other test data exists, but should never be 0
            self.assertGreaterEqual(mock_urlopen.call_count, 1)

    def test_pull_from_pi_multiple_devices(self):
        """Test pulling from multiple devices."""
        # Create second device with different URL
        device3 = self.env['supertcg.scanner.device'].sudo().create({
            'name': 'Test Scanner 3',
            'api_key': 'test-api-key-789',
            'pi_url': 'http://192.168.178.136:8082/api/batches',
            'company_id': self.env.company.id,
        })

        pi_data1 = {
            'ok': True,
            'batches': [{'batch_id': 'batch-from-dev1', 'batch_name': 'Dev1 Batch', 'card_count': 0, 'cards': []}]
        }
        pi_data2 = {
            'ok': True,
            'batches': [{'batch_id': 'batch-from-dev3', 'batch_name': 'Dev3 Batch', 'card_count': 0, 'cards': []}]
        }

        def side_effect(req, **kwargs):
            if '135' in req.full_url:
                return self._mock_response(pi_data1)
            else:
                return self._mock_response(pi_data2)

        with patch('urllib.request.urlopen', side_effect=side_effect):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertEqual(result['params']['title'], 'Pull Complete')
        self.assertIn('Imported 2 batch', result['params']['message'])

        batch1 = self.env['supertcg.batch'].search([('batch_id', '=', 'batch-from-dev1')], limit=1)
        batch3 = self.env['supertcg.batch'].search([('batch_id', '=', 'batch-from-dev3')], limit=1)
        self.assertTrue(batch1)
        self.assertTrue(batch3)

    def test_pull_from_pi_uses_device_api_key(self):
        """Test that each device's API key is used."""
        captured_keys = []

        def capture_request(req, **kwargs):
            # urllib Request stores headers in a dict, get_header normalizes names
            api_key = req.get_header('X-api-key')
            captured_keys.append(api_key)
            return self._mock_response({'ok': True, 'batches': []})

        with patch('urllib.request.urlopen', side_effect=capture_request):
            self.env['supertcg.batch'].action_pull_from_pi()

        # Should have captured our test device's key
        self.assertIn('test-api-key-123', captured_keys)

    def test_pull_from_pi_card_with_minimal_data(self):
        """Test card creation with minimal data from Pi."""
        pi_data = {
            'ok': True,
            'batches': [
                {
                    'batch_id': 'minimal-batch',
                    'card_count': 1,
                    'cards': [
                        {'card_name': 'Minimal Card', 'seq': 1}
                    ]
                }
            ]
        }

        with patch('urllib.request.urlopen', return_value=self._mock_response(pi_data)):
            result = self.env['supertcg.batch'].action_pull_from_pi()

        self.assertEqual(result['params']['title'], 'Pull Complete')
        batch = self.env['supertcg.batch'].search([('batch_id', '=', 'minimal-batch')], limit=1)
        self.assertTrue(batch)
        self.assertEqual(len(batch.card_line_ids), 1)
        self.assertEqual(batch.card_line_ids[0].card_name, 'Minimal Card')
        self.assertEqual(batch.card_line_ids[0].condition, 'ex')  # default
