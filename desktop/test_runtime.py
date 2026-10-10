"""Run with: python -m unittest desktop.test_runtime -v.

These tests never open a business database, install anything, or kill processes.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from desktop.runtime import (
    APP_ID, APP_VERSION, CONTROL_PATH, IDENTITY_PATH, AlreadyRunning,
    DesktopError, InstanceLock, NavigationPolicy, OwnedServer, RuntimePaths,
    child_path, get_local_json, local_opener, request_stop, wait_for_health,
    stop_state_path,
)
from desktop.webview_window import WebView2Guard


class Response(io.BytesIO):
    status = 200


class Dispatcher:
    def __init__(self):
        self.shutdown = Mock()


class FakeServer:
    def __init__(self, app, **options):
        self.options = options
        self.socket = options["sockets"][0]
        self.effective_host, self.effective_port = self.socket.getsockname()
        self.task_dispatcher = Dispatcher()
        self.end = threading.Event()
        self.close_count = 0

    def run(self):
        self.end.wait()

    def close(self):
        self.close_count += 1
        self.socket.close()
        self.end.set()


class PathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.resources = self.base / "program"
        (self.resources / "config").mkdir(parents=True)
        (self.resources / "config" / "settings.py").write_text("", encoding="utf-8")
        self.data = self.base / "data"
        self.credentials = self.base / "credential.json"
        self.credentials.write_text('{"password":"must-not-be-read"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_data_outside_program_credentials_never_read(self):
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), self.credentials.resolve())
            return original(path, *args, **kwargs)
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "read_text", guarded):
            paths = RuntimePaths.resolve(self.resources, self.data, self.credentials)
        self.assertEqual(paths.data, self.data.resolve())
        self.assertTrue(paths.browser_profile.is_dir())
        self.assertFalse(paths.state.exists())

    def test_data_in_program_is_rejected(self):
        with self.assertRaisesRegex(DesktopError, "程序资源目录之外"):
            RuntimePaths.resolve(self.resources, self.resources / "data", self.credentials)

    def test_resource_missing_is_readable_failure(self):
        with self.assertRaisesRegex(DesktopError, "资源不完整"):
            RuntimePaths.resolve(self.base / "missing", self.data, self.credentials)

    def test_no_runtime_no_credentials_fail_without_creating_data(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DesktopError, "尚未配置"):
            RuntimePaths.resolve(self.resources, self.data)
        self.assertFalse(self.data.exists())

    def test_missing_credentials_fail(self):
        with self.assertRaisesRegex(DesktopError, "配置文件不存在"):
            RuntimePaths.resolve(self.resources, self.data, self.base / "not-there")

    def test_runtime_relative_credentials_are_contained(self):
        private = self.data / "private"
        private.mkdir(parents=True)
        (private / "db.json").write_text("{}", encoding="utf-8")
        (private / "runtime.json").write_text('{"credentials_file":"db.json"}', encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            paths = RuntimePaths.resolve(self.resources, self.data)
        self.assertEqual(paths.credentials, (private / "db.json").resolve())

    def test_runtime_traversal_is_rejected(self):
        private = self.data / "private"
        private.mkdir(parents=True)
        (private / "runtime.json").write_text('{"credentials_file":"../../credential.json"}', encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DesktopError, "超出"):
            RuntimePaths.resolve(self.resources, self.data)

    def test_bad_runtime_json_is_safe(self):
        private = self.data / "private"
        private.mkdir(parents=True)
        (private / "runtime.json").write_text("{not-json", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(DesktopError, "格式不正确"):
            RuntimePaths.resolve(self.resources, self.data)

    def test_child_traversal_is_rejected(self):
        with self.assertRaises(DesktopError):
            child_path(self.data, "../other")

    def test_stop_state_does_not_require_credentials_or_create_directory(self):
        with patch.dict(os.environ, {}, clear=True):
            state = stop_state_path(self.data)
        self.assertEqual(state, self.data / "private" / "desktop-state.json")
        self.assertFalse(self.data.exists())


class LockTests(unittest.TestCase):
    def test_second_process_cannot_lock_and_release_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            lockfile = Path(directory) / "desktop.lock"
            lock = InstanceLock(lockfile).acquire()
            try:
                code = ("from pathlib import Path; from desktop.runtime import InstanceLock,AlreadyRunning; "
                        "import sys\ntry:\n InstanceLock(Path(sys.argv[1])).acquire()\nexcept AlreadyRunning:\n sys.exit(2)\n")
                result = subprocess.run([sys.executable, "-c", code, str(lockfile)],
                                        cwd=Path(__file__).resolve().parent.parent,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stderr)
            finally:
                lock.release()
            with InstanceLock(lockfile):
                self.assertTrue(lockfile.exists())
            self.assertTrue(lockfile.exists())


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.policy = NavigationPolicy("http://127.0.0.1:45678")

    def test_local_pages_queries_fragments_allowed(self):
        for url in ("http://127.0.0.1:45678/", "http://127.0.0.1:45678/questions/9/?next=%2F#answer"):
            self.assertTrue(self.policy.allows(url), url)

    def test_other_hosts_ports_protocols_and_userinfo_blocked(self):
        for url in ("https://127.0.0.1:45678/", "http://localhost:45678/", "http://127.0.0.1:45679/",
                    "http://127.0.0.1.evil.test:45678/", "http://127.0.0.1:45678@evil.test/",
                    "http://evil@127.0.0.1:45678/", "file:///C:/Windows/", "javascript:alert(1)",
                    "data:text/html,test", "https://api.deepseek.com", "//127.0.0.1:45678/",
                    "http://127.0.0.1:45678\\@evil.test", "http://127.0.0.1:45678/\n",
                    "http://127.0.0.1:bogus/", "http://[::1]:45678/", "about:blank"):
            self.assertFalse(self.policy.allows(url), url)

    def test_invalid_base_is_rejected(self):
        with self.assertRaises(DesktopError):
            NavigationPolicy("http://0.0.0.0:8000")

    def test_native_events_cancel_navigation_and_popup_without_js(self):
        guard = WebView2Guard(Mock(), self.policy.origin)
        guard.core = Mock()
        args = Mock(Uri="https://example.invalid/", Cancel=False, Handled=False)
        guard.navigation_starting(None, args)
        self.assertTrue(args.Cancel)
        guard.new_window_requested(None, args)
        self.assertTrue(args.Handled)
        guard.core.Navigate.assert_not_called()
        self.assertEqual(guard.blocked_navigations, 1)
        self.assertEqual(guard.blocked_popups, 1)
        args.Uri = self.policy.origin + "/tasks/"
        guard.new_window_requested(None, args)
        guard.core.Navigate.assert_called_once_with(args.Uri)

    def test_external_resource_is_blocked(self):
        guard = WebView2Guard(Mock(), self.policy.origin)
        guard.core = Mock()
        args = Mock()
        args.Request.Uri = "https://example.invalid/tracker.png"
        guard.web_resource_requested(None, args)
        guard.core.Environment.CreateWebResourceResponse.assert_called_once()
        self.assertEqual(args.Response, guard.core.Environment.CreateWebResourceResponse.return_value)

    def test_local_image_previews_allowed_without_relaxing_navigation(self):
        blob = "blob:" + self.policy.origin + "/2b1f5b19-d640-4ef1-945e-4543f1cd3e92"
        data = "data:image/png;base64,iVBORw0KGgo="
        for url in (blob, data):
            self.assertTrue(self.policy.allows_resource(url, "Image"))
            self.assertFalse(self.policy.allows(url))
            self.assertFalse(self.policy.allows_resource(url, "Document"))
            self.assertFalse(self.policy.allows_resource(url, "Script"))
        self.assertFalse(self.policy.allows_resource("blob:https://example.invalid/test", "Image"))
        self.assertFalse(self.policy.allows_resource("data:text/html,test", "Image"))
        self.assertFalse(self.policy.allows_resource("file:///C:/test.png", "Image"))

    def test_native_initialization_failure_closes_window(self):
        window = Mock()
        closed = threading.Event()
        window.destroy.side_effect = closed.set
        callback = Mock()
        guard = WebView2Guard(window, self.policy.origin, callback)
        guard.initialization_completed(None, Mock(IsSuccess=False))
        callback.assert_called_once()
        self.assertTrue(closed.wait(1))
        window.destroy.assert_called_once()
        self.assertFalse(guard.installed.is_set())


class HealthTests(unittest.TestCase):
    def test_health_requires_real_db_true_and_correct_app_version(self):
        opener = Mock()
        opener.open.side_effect = [Response(b'{"app":"studyreview","version":"2.0","db":false}'),
                                  Response(b'{"app":"another","version":"2.0","db":true}'),
                                  Response(b'{"app":"studyreview","version":"2.0","db":true}')]
        with patch("desktop.runtime.time.sleep"):
            result = wait_for_health("http://127.0.0.1:45678", opener=opener)
        self.assertIs(result["db"], True)
        self.assertEqual(opener.open.call_count, 3)

    def test_failed_thread_is_not_success(self):
        with self.assertRaisesRegex(DesktopError, "意外退出"):
            wait_for_health("http://127.0.0.1:45678", stopped=lambda: True)

    def test_timeout_is_explicit_not_blank_window(self):
        opener = Mock()
        opener.open.side_effect = URLError("connection refused")
        with patch("desktop.runtime.time.monotonic", side_effect=[0, 0, 2]), patch("desktop.runtime.time.sleep"):
            with self.assertRaisesRegex(DesktopError, "启动检查失败"):
                wait_for_health("http://127.0.0.1:45678", timeout=1, opener=opener)

    def test_no_proxy_and_no_redirect_are_configured(self):
        from desktop.runtime import NoRedirect
        opener = local_opener()
        self.assertTrue(any(isinstance(handler, NoRedirect) for handler in opener.handlers))
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid/"))

    def test_health_payload_limit(self):
        opener = Mock()
        opener.open.return_value = Response(b"x" * 9000)
        with self.assertRaises(DesktopError):
            get_local_json("http://127.0.0.1:45678/health/", opener=opener)


class LifecycleTests(unittest.TestCase):
    def test_bound_port_is_handed_to_waitress_without_releasing_socket(self):
        app = Mock()
        server = OwnedServer(app, create_server=FakeServer).start()
        try:
            self.assertEqual(server.server.socket.getsockname(), ("127.0.0.1", server.port))
            self.assertTrue(server.thread.is_alive())
            self.assertEqual(server.server.options["max_request_body_size"], 10 * 1024 * 1024)
            self.assertFalse(server.server.options["expose_tracebacks"])
        finally:
            server.close()
        self.assertFalse(server.thread.is_alive())
        self.assertEqual(server.server.close_count, 1)
        server.close()
        self.assertEqual(server.server.close_count, 1)

    def test_conflicting_port_is_not_stolen(self):
        with socket.socket() as unrelated:
            unrelated.bind(("127.0.0.1", 0))
            unrelated.listen()
            port = unrelated.getsockname()[1]
            with self.assertRaisesRegex(DesktopError, "端口绑定失败"):
                OwnedServer(Mock(), port=port, create_server=FakeServer)
            self.assertEqual(unrelated.getsockname()[1], port)

    def test_foreign_owner_refuses_close_no_process_kill(self):
        server = OwnedServer(Mock(), create_server=FakeServer)
        try:
            with patch("desktop.runtime.os.getpid", return_value=server.owner_pid + 1), patch("os.kill") as kill:
                with self.assertRaisesRegex(DesktopError, "其他进程"):
                    server.close()
                kill.assert_not_called()
                self.assertEqual(server.server.close_count, 0)
        finally:
            server.close()

    def test_state_cleanup_preserves_other_instance_state(self):
        server = OwnedServer(Mock(), create_server=FakeServer)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "desktop-state.json"
            try:
                server.write_state(state)
                value = json.loads(state.read_text())
                self.assertEqual(value["instance"], server.instance)
                server.remove_state(state)
                self.assertFalse(state.exists())
                value["instance"] = "different"
                state.write_text(json.dumps(value))
                server.remove_state(state)
                self.assertTrue(state.exists())
            finally:
                server.close()

    def test_stale_identity_cannot_trigger_stop(self):
        server = OwnedServer(Mock(), create_server=FakeServer)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "desktop-state.json"
            try:
                server.write_state(state)
                opener = Mock()
                opener.open.return_value = Response(json.dumps({
                    "app": APP_ID, "version": APP_VERSION,
                    "instance": "0" * 32, "pid": server.owner_pid,
                }).encode())
                with patch("os.kill") as kill, self.assertRaisesRegex(DesktopError, "身份"):
                    request_stop(state, opener=opener)
                self.assertEqual(opener.open.call_count, 1)
                kill.assert_not_called()
            finally:
                server.close()

    def test_bad_state_fails_without_network_or_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text('{"port":8000,"pid":1,"app":"other"}')
            opener = Mock()
            with patch("os.kill") as kill, self.assertRaisesRegex(DesktopError, "可验证"):
                request_stop(state, opener=opener)
            opener.open.assert_not_called()
            kill.assert_not_called()

    def test_control_requires_loopback_host_token_and_no_origin(self):
        app = Mock(return_value=[b"normal-app"])
        server = OwnedServer(app, create_server=FakeServer)
        try:
            base = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": f"127.0.0.1:{server.port}",
                    "PATH_INFO": CONTROL_PATH, "REQUEST_METHOD": "POST", "CONTENT_LENGTH": "0",
                    "HTTP_X_STUDY_DESKTOP_TOKEN": server.control_token,
                    "HTTP_X_STUDY_DESKTOP_INSTANCE": server.instance}
            for overrides in ({"REMOTE_ADDR":"192.168.1.2"}, {"HTTP_HOST":"example.invalid"},
                              {"HTTP_X_STUDY_DESKTOP_TOKEN":"bad"}, {"HTTP_X_STUDY_DESKTOP_INSTANCE":"old"},
                              {"HTTP_ORIGIN":"https://example.invalid"}, {"CONTENT_LENGTH":"1"},
                              {"REQUEST_METHOD":"GET"}):
                environ = {**base, **overrides}
                start = Mock()
                server._dispatch(environ, start)
                self.assertEqual(start.call_args.args[0], "403 Forbidden")
                self.assertFalse(server.stop_requested.is_set())
            app.assert_not_called()
            start = Mock()
            server._dispatch(base, start)
            self.assertEqual(start.call_args.args[0], "200 OK")
            self.assertTrue(server.stop_requested.is_set())
            start = Mock()
            server._dispatch({**base, "PATH_INFO":"/save/"}, start)
            self.assertEqual(start.call_args.args[0], "503 Service Unavailable")
            app.assert_not_called()
        finally:
            server.close()


class PackageAuditTests(unittest.TestCase):
    def build_minimal(self, directory):
        root = Path(directory)
        (root / "StudyReview.exe").write_bytes(b"synthetic executable placeholder; not runnable")
        (root / "_internal" / "templates").mkdir(parents=True)
        (root / "_internal" / "templates" / "base.html").write_text("synthetic")
        (root / "_internal" / "staticfiles").mkdir()
        (root / "_internal" / "staticfiles" / "app.css").write_text("body{}")
        (root / "LICENSES.txt").write_text("synthetic license test")
        return root

    def test_structure_audit_is_explicitly_not_cross_machine_proof(self):
        from desktop.package_audit import inspect_package
        with tempfile.TemporaryDirectory() as directory:
            report = inspect_package(self.build_minimal(directory))
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["clean_other_computer_verified"])
        self.assertEqual(report["audit_kind"], "structure_and_file_hashes_only")

    def test_private_folder_is_detected_without_reading_contents(self):
        from desktop.package_audit import inspect_package
        with tempfile.TemporaryDirectory() as directory:
            root = self.build_minimal(directory)
            private = root / "private"
            private.mkdir()
            (private / "database-credentials.json").write_text("must never read")
            original = Path.open
            def guarded(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(private))
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                report = inspect_package(root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("private", report["forbidden_paths"])
        self.assertFalse(report["credentials_contents_read"])

    def test_loose_runtime_config_is_detected_without_reading(self):
        from desktop.package_audit import inspect_package
        with tempfile.TemporaryDirectory() as directory:
            root = self.build_minimal(directory)
            (root / "runtime.json").write_text("sensitive")
            report = inspect_package(root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("runtime.json", report["forbidden_paths"])

    def test_missing_assets_fail(self):
        from desktop.package_audit import inspect_package
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "StudyReview.exe").write_bytes(b"test")
            report = inspect_package(root)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["required_resources"]["templates"])

    def test_ai_credentials_and_dpapi_are_not_read_or_hashed(self):
        from desktop.package_audit import inspect_package
        with tempfile.TemporaryDirectory() as directory:
            root = self.build_minimal(directory)
            private = root / "ai-credentials"
            private.mkdir()
            (private / "provider.bin").write_bytes(b"synthetic encrypted value")
            encrypted = root / "key.dpapi"
            encrypted.write_bytes(b"synthetic encrypted key")
            original = Path.open
            def guarded(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(private))
                self.assertNotEqual(path, encrypted)
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                report = inspect_package(root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("ai-credentials", report["forbidden_paths"])
        self.assertIn("key.dpapi", report["forbidden_paths"])
        self.assertFalse(any(item["path"].endswith(".dpapi") for item in report["files"]))


@unittest.skipUnless(importlib.util.find_spec("waitress"), "Waitress 未安装，真实 HTTP 待集成者安装后验证")
class ActualWaitressTests(unittest.TestCase):
    def test_real_http_health_stop_and_unrelated_listener_survives(self):
        def app(environ, start_response):
            body = b'{"app":"studyreview","version":"2.0","db":true}'
            start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
            return [body]
        with tempfile.TemporaryDirectory() as directory, socket.socket() as unrelated:
            unrelated.bind(("127.0.0.1", 0))
            unrelated.listen()
            untouched_port = unrelated.getsockname()[1]
            server = OwnedServer(app).start()
            client = local_opener()
            state = Path(directory) / "desktop-state.json"
            try:
                wait_for_health(server.base_url, timeout=3, stopped=server.failed)
                identity = get_local_json(server.base_url + IDENTITY_PATH)
                self.assertEqual(identity["pid"], os.getpid())
                self.assertEqual(identity["instance"], server.instance)
                with socket.socket() as conflicting:
                    with self.assertRaises(OSError):
                        conflicting.bind(("127.0.0.1", server.port))
                with self.assertRaises(HTTPError) as denied:
                    client.open(Request(server.base_url + CONTROL_PATH, data=b"", method="POST"), timeout=2)
                self.assertEqual(denied.exception.code, 403)
                self.assertFalse(server.stop_requested.is_set())
                server.write_state(state)
                self.assertTrue(request_stop(state))
                self.assertTrue(server.stop_requested.wait(1))
            finally:
                server.close()
                server.remove_state(state)
            self.assertFalse(server.thread.is_alive())
            self.assertEqual(unrelated.getsockname()[1], untouched_port)
            with socket.socket() as reconnect:
                reconnect.settimeout(1)
                self.assertNotEqual(reconnect.connect_ex(("127.0.0.1", server.port)), 0)


if __name__ == "__main__":
    unittest.main()
