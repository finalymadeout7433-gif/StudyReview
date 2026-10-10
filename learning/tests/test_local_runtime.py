import contextlib
import io
import json
import os
import runpy
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from django.conf import settings
from django.test import SimpleTestCase
from config.local_runtime import resolve_credentials_file


class RuntimeConfigurationTests(SimpleTestCase):
    def test_resolver_precedence_and_runtime_only_configuration(self):
        with tempfile.TemporaryDirectory(prefix='study-runtime-') as temporary:
            root = Path(temporary)
            (root / 'private').mkdir()
            external = root / 'existing-safe-config.json'
            (root / 'private' / 'runtime.json').write_text(json.dumps({'credentials_file': str(external)}), encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(resolve_credentials_file(root), external)
                with patch.dict(os.environ, {'STUDY_CREDENTIALS_FILE': str(root / 'override.json')}):
                    self.assertEqual(resolve_credentials_file(root), root / 'override.json')

    def test_explicit_v2_initializer_uses_shared_runtime_resolver_and_refuses_existing_schema(self):
        # Mock only the connection so the initializer cannot modify any live schema.
        with tempfile.TemporaryDirectory(prefix='study-runtime-init-') as temporary:
            root = Path(temporary)
            private = root / 'private'
            private.mkdir()
            external = root / 'existing-safe-config.json'
            external.write_text(json.dumps({'host': '127.0.0.1', 'port': 3306, 'database': 'study_review',
                'administrator_user': 'synthetic_admin', 'administrator_password': 'synthetic_admin_password',
                'application_user': 'synthetic_app', 'application_password': 'synthetic_app_password'}), encoding='utf-8')
            (private / 'runtime.json').write_text(json.dumps({'credentials_file': str(external)}), encoding='utf-8')
            def resolver(project_root):
                return resolve_credentials_file(root)
            fake_connection = MagicMock()
            fake_connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            with patch.dict(os.environ, {}, clear=True), patch('config.local_runtime.resolve_credentials_file', side_effect=resolver), \
                patch('MySQLdb.connect', return_value=fake_connection) as connect, contextlib.redirect_stdout(io.StringIO()):
                from scripts.initialize_v2_mysql import main
                with self.assertRaises(RuntimeError):
                    main(['--create-new-empty-database','--confirm-existing-account-dml-grant'])
            self.assertEqual(connect.call_args.kwargs['user'], 'synthetic_admin')
            self.assertEqual(connect.call_args.kwargs['passwd'], 'synthetic_admin_password')
            self.assertTrue(fake_connection.close.called)
            self.assertEqual(fake_connection.cursor.return_value.__enter__.return_value.execute.call_count,1)

    def test_retired_initializer_never_reads_configuration_or_connects(self):
        with patch('config.local_runtime.resolve_credentials_file',side_effect=AssertionError('retired entry must not read')),patch('MySQLdb.connect')as connect,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit)as error:
                runpy.run_path(str(Path(settings.BASE_DIR)/'scripts'/'prepare_mysql.py'),run_name='__main__')
        self.assertEqual(error.exception.code,2);connect.assert_not_called()
