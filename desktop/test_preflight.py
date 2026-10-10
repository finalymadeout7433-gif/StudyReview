"""First-start privacy and failure boundaries; no actual database connection."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from desktop.preflight import diagnose,TABLES,TRIGGERS
from desktop.main import main

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.program=self.root/'中文程序';self.data=self.root/'私有学习数据'
        for name in ('templates/base.html','staticfiles/css/app.css','staticfiles/css/v2.css','staticfiles/js/assistant.js','staticfiles/img/mi-avatar.png'):
            file=self.program/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'public asset')
        self.config=self.root/'chosen-existing-config.json'
        self.config.write_text(json.dumps({'host':'127.0.0.1','port':3306,'application_user':'synthetic-app','application_password':'synthetic-sensitive-sentinel'}),encoding='utf-8')
        self.environment=patch.dict(os.environ,{},clear=True);self.environment.start()
        self.runtime=patch('desktop.webview_window.webview2_installed',return_value=True);self.runtime.start()
    def tearDown(self):self.runtime.stop();self.environment.stop();self.temp.cleanup()
    def run_check(self,**options):return diagnose(self.program,self.data,**options)
    def test_unconfigured_can_check_dependencies_without_creating_data(self):
        result=self.run_check()
        self.assertFalse(result['configured']);self.assertFalse(result['ready_to_launch']);self.assertFalse(self.data.exists())
        self.assertTrue(next(row['passed']for row in result['checks']if row['code']=='dependency_MySQLdb'))
    def test_config_pointer_alone_never_reads_secret_contents(self):
        with patch.object(Path,'read_text',side_effect=AssertionError('credential contents not authorized in path-only check')):
            result=self.run_check(credentials_file=self.config)
        self.assertTrue(result['configured']);self.assertFalse(result['database_checked'])
    def test_database_configuration_rejects_remote_host_before_connection(self):
        self.config.write_text(json.dumps({'host':'remote.invalid','port':3306,'application_user':'user','application_password':'synthetic-sensitive-sentinel'}),encoding='utf-8')
        with patch('MySQLdb.connect')as connect:result=self.run_check(credentials_file=self.config,database=True);connect.assert_not_called()
        self.assertFalse(result['ready_to_launch']);self.assertNotIn('synthetic-sensitive-sentinel',json.dumps(result))
    def test_no_password_database_is_not_accepted(self):
        value=json.loads(self.config.read_text());value['application_password']='';self.config.write_text(json.dumps(value))
        with patch('MySQLdb.connect')as connect:result=self.run_check(credentials_file=self.config,database=True);connect.assert_not_called()
        self.assertFalse(result['ready_to_launch'])
    def test_bool_port_is_rejected(self):
        value=json.loads(self.config.read_text());value['port']=True;self.config.write_text(json.dumps(value))
        with patch('MySQLdb.connect')as connect:result=self.run_check(credentials_file=self.config,database=True);connect.assert_not_called()
        self.assertFalse(result['database_checked'])
    def test_database_error_is_redacted(self):
        with patch('MySQLdb.connect',side_effect=RuntimeError('synthetic-sensitive-sentinel: user and password must never appear')):
            result=self.run_check(credentials_file=self.config,database=True)
        self.assertFalse(result['ready_to_launch']);self.assertNotIn('synthetic-sensitive-sentinel',json.dumps(result))
        self.assertFalse(self.data.exists())
    def test_relative_config_cannot_escape_private_directory(self):
        private=self.data/'private';private.mkdir(parents=True)
        (private/'runtime.json').write_text(json.dumps({'credentials_file':'../../chosen-existing-config.json'}))
        result=self.run_check();self.assertFalse(result['configured'])
    def test_malformed_runtime_does_not_get_overwritten(self):
        private=self.data/'private';private.mkdir(parents=True);file=private/'runtime.json';file.write_bytes(b'not json')
        result=self.run_check();self.assertFalse(result['configured']);self.assertEqual(file.read_bytes(),b'not json')
    def test_data_in_program_refused(self):
        result=diagnose(self.program,self.program/'data')
        self.assertFalse(result['ready_to_launch']);self.assertFalse((self.program/'data').exists())
    def test_missing_webview_reports_failure_without_installing(self):
        with patch('desktop.webview_window.webview2_installed',return_value=False):result=self.run_check(credentials_file=self.config)
        self.assertFalse(result['ready_to_launch']);self.assertFalse(self.data.exists())
    def test_complete_database_check_runs_selects_only(self):
        connection=Mock();cursor=Mock();connection.cursor.return_value.__enter__=Mock(return_value=cursor);connection.cursor.return_value.__exit__=Mock(return_value=False)
        cursor.fetchone.side_effect=[('study_review_dev','8.4.11'),(1,)]
        cursor.fetchall.side_effect=[[(table,)for table in TABLES],[(trigger,)for trigger in TRIGGERS]]
        with patch('MySQLdb.connect',return_value=connection):result=self.run_check(credentials_file=self.config,database=True)
        self.assertTrue(result['ready_to_launch']);self.assertFalse(self.data.exists());connection.close.assert_called_once()
        self.assertTrue(all(call.args[0].startswith('SELECT ')for call in cursor.execute.call_args_list))
        self.assertNotIn('synthetic-sensitive-sentinel',json.dumps(result))
    def test_existing_report_file_not_truncated(self):
        output=self.root/'report.json';output.write_bytes(b'preserved')
        code=main(['--diagnose','--resource-dir',str(self.program),'--data-dir',str(self.data),'--diagnose-output',str(output),'--quiet'])
        self.assertEqual(code,1);self.assertEqual(output.read_bytes(),b'preserved')

    def assert_redirected_private_path_refused(self,parts,*,database=True,settings_module='config.settings'):
        """Simulate resolution only; never create a junction or private secret."""
        blocked=self.data.joinpath(*parts)
        outside=self.root/'outside-synthetic-boundary'/parts[-1]
        original_resolve=Path.resolve
        def redirected(path,*args,**kwargs):
            if path==blocked:return original_resolve(outside)
            return original_resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',autospec=True,side_effect=redirected), \
             patch.object(Path,'read_text',side_effect=AssertionError('No reference or credential reads permitted'))as reads, \
             patch('MySQLdb.connect')as connect:
            result=self.run_check(credentials_file=self.config,database=database,settings_module=settings_module)
        reads.assert_not_called();connect.assert_not_called()
        self.assertFalse(result['configured']);self.assertFalse(result['database_checked'])
        self.assertFalse(result['ready_to_launch']);self.assertFalse(self.data.exists())
        self.assertFalse(next(row['passed']for row in result['checks']if row['code']=='private_path_boundary'))

    def test_private_junction_refused_before_any_config_read_or_connection(self):
        self.assert_redirected_private_path_refused(('private',))

    def test_private_junction_refused_also_in_path_only_diagnose(self):
        self.assert_redirected_private_path_refused(('private',),database=False)

    def test_runtime_json_redirect_refused_even_with_explicit_credentials(self):
        self.assert_redirected_private_path_refused(('private','runtime.json'))

    def test_development_json_redirect_refused_before_credential_reads(self):
        self.assert_redirected_private_path_refused(('private','development-environment.json'),settings_module='config.v2_development_settings')

    def test_private_path_resolution_error_redacted_without_reads_or_connection(self):
        with patch('desktop.preflight.child_path',side_effect=OSError('synthetic-sensitive-sentinel')),\
             patch.object(Path,'read_text')as reads,patch('MySQLdb.connect')as connect:
            result=self.run_check(credentials_file=self.config,database=True)
        reads.assert_not_called();connect.assert_not_called()
        self.assertFalse(result['ready_to_launch']);self.assertFalse(result['database_checked'])
        self.assertNotIn('synthetic-sensitive-sentinel',json.dumps(result))
