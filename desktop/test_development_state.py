import json
import os
from pathlib import Path
import socket
import tempfile
import unittest

from desktop.development_state import recover, pid_is_alive, port_is_busy
from desktop.runtime import DesktopError, InstanceLock


class DevelopmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.private = self.data / 'private'
        self.private.mkdir()
        (self.private/'development-environment.json').write_text(json.dumps({
            'database':'study_review_v2_dev_synthetic',
            'test_database':'test_study_review_v2_synthetic'}))
        self.state = self.private/'desktop-state.json'
        self.raw = json.dumps({'app':'studyreview','version':'2.0','pid':12345,'port':8001}).encode()
        self.state.write_bytes(self.raw)
        self.other = self.private/'keep.dat'
        self.other.write_bytes(b'unchanged')

    def test_abandoned_state_is_backed_up_exactly_and_second_start_is_noop(self):
        self.assertTrue(recover(self.data,8001,alive=lambda _:False,busy=lambda _:False))
        self.assertFalse(self.state.exists())
        backup=list(self.private.glob('desktop-state.stale-*.json'))
        self.assertEqual(len(backup),1)
        self.assertEqual(backup[0].read_bytes(),self.raw)
        self.assertEqual(self.other.read_bytes(),b'unchanged')
        self.assertFalse(recover(self.data,8001))

    def test_live_pid_or_busy_port_preserves_state(self):
        for alive,busy in [(True,False),(False,True)]:
            with self.subTest(alive=alive,busy=busy),self.assertRaises(DesktopError):
                recover(self.data,8001,alive=lambda _:alive,busy=lambda _:busy)
            self.assertEqual(self.state.read_bytes(),self.raw)

    def test_held_lock_preserves_state(self):
        with InstanceLock(self.private/'desktop.lock'):
            with self.assertRaises(DesktopError):
                recover(self.data,8001,alive=lambda _:False,busy=lambda _:False)
        self.assertEqual(self.state.read_bytes(),self.raw)

    def test_invalid_and_foreign_states_are_never_moved(self):
        for raw in (b'not json',b'[]',self.raw.replace(b'studyreview',b'other-app'),self.raw.replace(b'8001',b'9001')):
            self.state.write_bytes(raw)
            with self.assertRaises(DesktopError):
                recover(self.data,8001,alive=lambda _:False,busy=lambda _:False)
            self.assertEqual(self.state.read_bytes(),raw)

    def test_original_runtime_profile_is_refused(self):
        (self.private/'development-environment.json').write_text('{"database":"production"}')
        with self.assertRaises(DesktopError):recover(self.data,8001)
        self.assertEqual(self.state.read_bytes(),self.raw)

    def test_actual_current_process_and_listening_socket_are_detected(self):
        self.assertTrue(pid_is_alive(os.getpid()))
        self.assertFalse(pid_is_alive(2147483647))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            port=listener.getsockname()[1]
            self.assertTrue(port_is_busy(port))
        self.assertFalse(port_is_busy(port))
