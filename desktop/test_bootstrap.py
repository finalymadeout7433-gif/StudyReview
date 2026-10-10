"""Safety decisions tested without any credential or database access."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from desktop.bootstrap import validate_request
from desktop.main import main
from desktop.runtime import DesktopError

class BootstrapTests(unittest.TestCase):
    def test_missing_confirmation_is_rejected_before_paths(self):
        for create, grant in ((False, False), (True, False), (False, True)):
            with self.subTest(create=create, grant=grant), self.assertRaises(DesktopError):
                validate_request('/outside/data', '/outside/config.json', create, grant)

    def test_missing_explicit_paths_is_rejected(self):
        for data, config in ((None, '/outside/config.json'), ('/outside/data', None)):
            with self.subTest(data=data), self.assertRaises(DesktopError):
                validate_request(data, config, True, True)

    def test_relative_paths_are_rejected(self):
        with self.assertRaises(DesktopError):
            validate_request('data', 'config.json', True, True)

    def test_standalone_seed_cannot_reach_database(self):
        with patch('desktop.main.RuntimePaths.resolve') as resolve:
            self.assertEqual(main(['--seed-synthetic-demo', '--quiet']), 1)
            resolve.assert_not_called()

    def test_mixed_start_and_initialization_rejected(self):
        with patch('desktop.bootstrap.initialize_new_installation') as initialize:
            self.assertEqual(main(['--initialize-new-empty-database', '--start-or-setup', '--quiet']), 1)
            initialize.assert_not_called()

    def test_development_settings_cannot_initialize_production_schema(self):
        with patch('desktop.bootstrap.initialize_new_installation') as initialize:
            self.assertEqual(main(['--initialize-new-empty-database', '--settings',
                                  'config.v2_development_settings', '--quiet']), 1)
            initialize.assert_not_called()

    def test_existing_report_is_rejected_before_database(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'existing.json'
            report.write_text('preserve')
            with patch('desktop.bootstrap.initialize_new_installation') as initialize:
                self.assertEqual(main(['--initialize-new-empty-database', '--initialization-output',
                                      str(report), '--quiet']), 1)
                initialize.assert_not_called()
            self.assertEqual(report.read_text(), 'preserve')
