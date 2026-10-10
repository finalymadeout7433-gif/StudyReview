"""Consent, no secret reading, no silent overwrite and remembered path tests."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from desktop.runtime import DesktopError
from desktop.setup_wizard import persist_reference,remembered_data_dir,configuration_reference
class SetupReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.resources=self.root/'程序';self.resources.mkdir();self.data=self.root/'私人学习数据'
        self.credentials=self.root/'已有本机配置.json';self.credentials.write_text('{"application_password":"synthetic-private-sentinel"}')
        self.preferences=self.root/'本人偏好'/'launcher.json';self.secure=patch('desktop.setup_wizard._secure_new_directory');self.secure.start()
    def tearDown(self):self.secure.stop();self.temp.cleanup()
    def save(self,**kwargs):return persist_reference(self.resources,self.data,self.credentials,preferences=self.preferences,**kwargs)
    def test_no_consent_creates_nothing(self):
        with self.assertRaises(DesktopError):self.save()
        self.assertFalse(self.data.exists());self.assertFalse(self.preferences.exists())
    def test_save_never_reads_credential_contents(self):
        with patch.object(Path,'read_text',side_effect=AssertionError('credential values must not be read')):self.save(confirmed=True)
        runtime=self.data/'private'/'runtime.json';value=json.loads(runtime.read_text(encoding="utf-8"))
        self.assertEqual(value,{'credentials_file':str(self.credentials.resolve())})
        self.assertNotIn('synthetic-private-sentinel',runtime.read_text(encoding="utf-8")+self.preferences.read_text(encoding="utf-8"))
    def test_remembers_data_directory_only_after_consent(self):
        self.save(confirmed=True);self.assertEqual(remembered_data_dir(self.preferences),str(self.data.resolve()))
    def test_program_data_refused(self):
        self.data=self.resources/'data'
        with self.assertRaises(DesktopError):self.save(confirmed=True)
        self.assertFalse(self.data.exists())
    def test_credentials_in_program_refused(self):
        self.credentials=self.resources/'private-config.json';self.credentials.write_text('{}')
        with self.assertRaises(DesktopError):self.save(confirmed=True)
        self.assertFalse(self.data.exists())
    def test_missing_file_refused_without_data_creation(self):
        self.credentials=self.root/'missing.json'
        with self.assertRaises(DesktopError):self.save(confirmed=True)
        self.assertFalse(self.data.exists())
    def test_other_reference_needs_separate_confirmation(self):
        self.save(confirmed=True);runtime=self.data/'private'/'runtime.json';old=runtime.read_bytes()
        self.credentials=self.root/'其他已有配置.json';self.credentials.write_text('{}')
        with self.assertRaises(DesktopError):self.save(confirmed=True)
        self.assertEqual(runtime.read_bytes(),old)
    def test_explicit_replace_keeps_old_reference_bytes(self):
        self.save(confirmed=True);runtime=self.data/'private'/'runtime.json';old=runtime.read_bytes()
        self.credentials=self.root/'其他已有配置.json';self.credentials.write_text('{}')
        self.save(confirmed=True,replace_confirmed=True)
        backups=list(runtime.parent.glob('runtime-reference-before-*.json'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)
    def test_same_existing_reference_can_remember_selected_data(self):
        self.save(confirmed=True);self.preferences.unlink();self.assertTrue(self.save(confirmed=True)['preferences_saved'])
    def test_malformed_runtime_preserved(self):
        private=self.data/'private';private.mkdir(parents=True);runtime=private/'runtime.json';runtime.write_bytes(b'not json')
        with self.assertRaises(DesktopError):self.save(confirmed=True,replace_confirmed=True)
        self.assertEqual(runtime.read_bytes(),b'not json')
    def test_unknown_fields_preserved(self):
        private=self.data/'private';private.mkdir(parents=True);runtime=private/'runtime.json'
        value={'credentials_file':str(self.credentials),'unexpected':'must retain'};runtime.write_text(json.dumps(value))
        with self.assertRaises(DesktopError):self.save(confirmed=True,replace_confirmed=True)
        self.assertEqual(json.loads(runtime.read_text(encoding="utf-8")),value)
    def test_malformed_or_relative_preference_not_used(self):
        self.preferences.parent.mkdir();self.preferences.write_text('{"data_dir":"../outside"}')
        self.assertIsNone(remembered_data_dir(self.preferences))
        self.preferences.write_text('not json');self.assertIsNone(remembered_data_dir(self.preferences))
    def test_reference_reader_only_returns_path(self):
        self.save(confirmed=True);self.assertEqual(configuration_reference(self.data),str(self.credentials.resolve()))
    def test_read_only_configuration_reference_does_not_create_directory(self):
        self.assertEqual(configuration_reference(self.data),'');self.assertFalse(self.data.exists())
