"""Fake cursor only; no credentials/MySQL import or real privilege changes."""
import unittest
from unittest.mock import MagicMock,patch
from scripts.initialize_v2_mysql import create_new_database,main
class InitializationTests(unittest.TestCase):
    def connection(self,counts):
        connection=MagicMock();cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[(count,)for count in counts]
        return connection,cursor
    def test_default_does_not_connect(self):
        with patch('builtins.print'):self.assertEqual(main([]),2)
    def test_existing_even_empty_schema_stops_before_any_write(self):
        connection,cursor=self.connection([1])
        with self.assertRaises(RuntimeError):create_new_database(connection,'synthetic-app')
        self.assertEqual(cursor.execute.call_count,1)
        self.assertTrue(cursor.execute.call_args.args[0].startswith('SELECT '))
    def test_missing_identity_stops_before_create(self):
        connection,cursor=self.connection([0,0])
        with self.assertRaises(RuntimeError):create_new_database(connection,'synthetic-app')
        self.assertTrue(all(call.args[0].startswith('SELECT ')for call in cursor.execute.call_args_list))
    def test_new_schema_grants_only_dml(self):
        connection,cursor=self.connection([0,1]);create_new_database(connection,'synthetic-app')
        statements=[call.args[0]for call in cursor.execute.call_args_list]
        self.assertEqual(len(statements),4)
        self.assertNotIn('IF NOT EXISTS',statements[2]);self.assertNotIn('ALL',statements[3])
        self.assertTrue(statements[3].startswith('GRANT SELECT, INSERT, UPDATE, DELETE '))
        self.assertFalse(any('CREATE USER'in statement or 'IDENTIFIED'in statement for statement in statements))
    def test_create_race_failure_never_grants(self):
        connection,cursor=self.connection([0,1]);cursor.execute.side_effect=[None,None,RuntimeError('synthetic race')]
        with self.assertRaises(RuntimeError):create_new_database(connection,'synthetic-app')
        self.assertEqual(cursor.execute.call_count,3)
