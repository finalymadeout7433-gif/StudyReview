"""Small, independently testable lifecycle primitives for the local desktop app.

No credentials are logged, no processes are killed, and no database is created here.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


APP_ID = "studyreview"
APP_VERSION = "2.0"
CONTROL_PATH = "/__desktop/control/stop"
IDENTITY_PATH = "/__desktop/identity"


class DesktopError(RuntimeError):
    """A safe, user-readable error without credential contents."""


class AlreadyRunning(DesktopError):
    pass


def inside(path: Path, directory: Path) -> bool:
    """Resolve symlinks/junctions before checking containment."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def child_path(directory: Path, *parts: str) -> Path:
    result = directory.joinpath(*parts).resolve()
    if not inside(result, directory):
        raise DesktopError("数据路径超出指定目录，已停止启动。")
    return result


@dataclass(frozen=True)
class RuntimePaths:
    resources: Path
    data: Path
    private: Path
    credentials: Path
    state: Path
    lock: Path
    browser_profile: Path

    @classmethod
    def resolve(cls, resource_dir=None, data_dir=None, credentials_file=None):
        if resource_dir is None:
            resource_dir = os.environ.get("STUDY_RESOURCE_DIR")
        if resource_dir is None:
            resource_dir = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        resources = Path(resource_dir).expanduser().resolve()
        if getattr(sys, "frozen", False):
            # PyInstaller imports Python modules from PYZ; source .py files
            # need not exist next to the collected templates/static assets.
            valid_resources = ((resources / "templates" / "base.html").is_file()
                               and (resources / "staticfiles").is_dir())
        else:
            valid_resources = (resources / "config" / "settings.py").is_file()
        if not valid_resources:
            raise DesktopError("程序资源不完整，请重新解压完整程序目录。")
        if data_dir is None:
            data_dir = os.environ.get("STUDY_DATA_DIR")
        if data_dir is None:
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise DesktopError("请明确设置 STUDY_DATA_DIR，指定程序目录之外的学习数据目录。")
            data_dir = Path(local) / "StudyReview" / "data"
        data = Path(data_dir).expanduser().resolve()
        if inside(data, resources):
            raise DesktopError("学习数据目录必须在程序资源目录之外，避免升级或解压时覆盖记录。")
        if getattr(sys, "frozen", False):
            bundle = Path(sys.executable).resolve().parent
            if inside(data, bundle):
                raise DesktopError("学习数据目录必须在可执行程序目录之外。")
        private = child_path(data, "private")
        runtime_file = child_path(private, "runtime.json")
        credentials_file = credentials_file or os.environ.get("STUDY_CREDENTIALS_FILE")
        if not credentials_file and runtime_file.is_file():
            try:
                config = json.loads(runtime_file.read_text(encoding="utf-8-sig"))
                credentials_file = config.get("credentials_file")
            except (OSError, ValueError, AttributeError):
                raise DesktopError("private/runtime.json 格式不正确；请按说明填写本机配置。") from None
            if credentials_file:
                if not isinstance(credentials_file, str):
                    raise DesktopError("private/runtime.json 的 credentials_file 必须是文件路径文本。")
                credential_candidate = Path(credentials_file).expanduser()
                if not credential_candidate.is_absolute():
                    credentials_file = child_path(private, str(credential_candidate))
        if not credentials_file:
            raise DesktopError("尚未配置本机数据库。请在数据目录 private/runtime.json 填写 credentials_file，或设置 STUDY_CREDENTIALS_FILE。")
        credentials = Path(credentials_file).expanduser().resolve()
        if not credentials.is_file():
            raise DesktopError("指定的本机数据库配置文件不存在；请检查路径。")
        # Credential contents belong to Django configuration, not the desktop shell.
        try:
            private.mkdir(parents=True, exist_ok=True)
            browser_profile = child_path(private, "webview-profile")
            browser_profile.mkdir(exist_ok=True)
        except OSError:
            raise DesktopError("学习数据目录不可写；请换用当前账户可写的目录。") from None
        return cls(resources, data, private, credentials,
                   child_path(private, "desktop-state.json"),
                   child_path(private, "desktop.lock"), browser_profile)

    def apply_environment(self, settings_module: str) -> None:
        if settings_module not in {"config.settings", "config.v2_development_settings"}:
            raise DesktopError("不允许使用未知 Django 配置模块。")
        os.environ["STUDY_RESOURCE_DIR"] = str(self.resources)
        os.environ["STUDY_DATA_DIR"] = str(self.data)
        os.environ["STUDY_CREDENTIALS_FILE"] = str(self.credentials)
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
        os.environ["STUDY_DEBUG"] = "0"
        os.environ["STUDY_DATABASE"] = "study_review_dev"
        os.environ.pop("STUDY_DB_ENGINE",None)
        os.environ.pop("STUDY_ALLOW_SCHEMA_ADMIN",None)
        if str(self.resources) not in sys.path:
            sys.path.insert(0, str(self.resources))


class InstanceLock:
    """An OS-held file lock, released even when a process crashes.

    The file is intentionally kept after release: deleting a live lock filename
    could allow another process to lock a different inode on Unix.
    """
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise AlreadyRunning("拾习独立窗口已在运行。请切换到已有窗口；需要退出时使用停止入口。") from None
        return self

    def release(self):
        if self.file is None:
            return
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


class NavigationPolicy:
    def __init__(self, base_url: str):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise DesktopError("窗口服务地址必须是明确端口的 127.0.0.1。")
        self.origin = f"http://127.0.0.1:{parsed.port}"
        self.port = parsed.port

    def allows(self, url: str) -> bool:
        try:
            if not isinstance(url, str) or "\\" in url or any(ord(c) < 32 for c in url):
                return False
            parsed = urlsplit(url)
            return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                    and parsed.port == self.port and parsed.username is None
                    and parsed.password is None)
        except (ValueError, TypeError):
            return False

    def allows_resource(self, url: str, context: str) -> bool:
        if self.allows(url):
            return True
        # Upload previews can use browser-created image blobs without network
        # access. They remain forbidden as top-level/frame navigation.
        if context != "Image" or not isinstance(url, str):
            return False
        if any(ord(char) < 32 for char in url) or "\\" in url:
            return False
        if url.startswith("blob:" + self.origin + "/"):
            return True
        return url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,",
                               "data:image/webp;base64,"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_opener():
    # Ignore ambient proxy settings so local tokens cannot be sent to a proxy.
    return build_opener(ProxyHandler({}), NoRedirect())


def stop_state_path(data_dir=None):
    """Stopping requires the live instance record, not database credentials."""
    data_dir = data_dir or os.environ.get("STUDY_DATA_DIR")
    if data_dir is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise DesktopError("请设置 STUDY_DATA_DIR，以找到要停止的独立窗口。")
        data_dir = Path(local) / "StudyReview" / "data"
    return child_path(Path(data_dir).expanduser().resolve(), "private", "desktop-state.json")


def get_local_json(url: str, timeout: float = 1.0, opener=None):
    with (opener or local_opener()).open(url, timeout=timeout) as response:
        if response.status != 200:
            raise DesktopError("本机服务未通过启动检查。")
        raw = response.read(8193)
        if len(raw) > 8192:
            raise DesktopError("本机服务启动检查返回异常。")
        return json.loads(raw.decode("utf-8"))


def wait_for_health(base_url: str, timeout: float = 20.0, stopped=None, opener=None):
    NavigationPolicy(base_url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stopped and stopped():
            raise DesktopError("本机服务启动后意外退出，请查看本地运行日志。")
        try:
            value = get_local_json(base_url + "/health/", timeout=.8, opener=opener)
            if (value.get("app") == APP_ID and str(value.get("version")) == APP_VERSION
                    and value.get("db") is True):
                return value
        except (URLError, OSError, ValueError, AttributeError, DesktopError):
            pass
        time.sleep(.1)
    raise DesktopError("启动检查失败：Django 或本机 MySQL 尚未就绪。没有打开空白窗口，也没有创建或覆盖学习数据。")


def atomic_json(path: Path, value: dict):
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


class OwnedServer:
    """Owns exactly one in-process Waitress server and a private socket map."""
    def __init__(self, app, port=0, create_server=None):
        self.owner_pid = os.getpid()
        self.instance = secrets.token_hex(16)
        self.control_token = secrets.token_urlsafe(32)
        self.stop_requested = threading.Event()
        self.error = None
        self.exit_callback: Callable[[], None] | None = None
        self.socket_map = {}
        self._closed = False
        self._mutex = threading.Lock()
        if not (isinstance(port, int) and 0 <= port <= 65535):
            raise DesktopError("端口范围不正确。")
        if create_server is None:
            try:
                from waitress import create_server
            except ImportError:
                raise DesktopError("缺少 Waitress 依赖。请使用完整程序包或按依赖说明安装。") from None
        self.app = app
        # Bind once and hand the still-bound socket to Waitress. Windows
        # SO_EXCLUSIVEADDRUSE prevents a second listener from sharing it.
        self.bound_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.bound_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.bound_socket.bind(("127.0.0.1", port))
            self.server = create_server(
                self._dispatch, sockets=[self.bound_socket], ipv6=False,
                map=self.socket_map, threads=4, expose_tracebacks=False,
                max_request_body_size=10 * 1024 * 1024,
                asyncore_loop_timeout=.1,
            )
        except OSError:
            for channel in list(self.socket_map.values()):
                channel.close()
            self.bound_socket.close()
            raise DesktopError("本机端口绑定失败，可能端口已被占用；请使用自动端口。") from None
        except Exception:
            for channel in list(self.socket_map.values()):
                channel.close()
            self.bound_socket.close()
            raise DesktopError("本机服务创建失败，请检查完整依赖。") from None
        self.port = int(self.server.effective_port)
        if self.server.effective_host != "127.0.0.1" or not 1 <= self.port <= 65535:
            self.server.close()
            raise DesktopError("服务没有绑定到指定本机地址，已停止。")
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self._run, name="StudyReview-WSGI", daemon=True)

    def _json(self, start_response, status, value):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                                ("Content-Length", str(len(body))),
                                ("Cache-Control", "no-store"),
                                ("X-Content-Type-Options", "nosniff")])
        return [body]

    def _dispatch(self, environ, start_response):
        if (environ.get("REMOTE_ADDR") != "127.0.0.1"
                or environ.get("HTTP_HOST") != f"127.0.0.1:{self.port}"):
            return self._json(start_response, "403 Forbidden", {"error": "local_only"})
        path = environ.get("PATH_INFO")
        if path == IDENTITY_PATH:
            if environ.get("REQUEST_METHOD") != "GET":
                return self._json(start_response, "405 Method Not Allowed", {"error": "method"})
            return self._json(start_response, "200 OK", {
                "app": APP_ID, "version": APP_VERSION,
                "instance": self.instance, "pid": self.owner_pid,
            })
        if path == CONTROL_PATH:
            supplied = environ.get("HTTP_X_STUDY_DESKTOP_TOKEN", "")
            valid = (environ.get("REQUEST_METHOD") == "POST"
                     and not environ.get("HTTP_ORIGIN")
                     and environ.get("CONTENT_LENGTH", "0") in {"", "0"}
                     and isinstance(supplied, str)
                     and hmac.compare_digest(supplied, self.control_token)
                     and environ.get("HTTP_X_STUDY_DESKTOP_INSTANCE") == self.instance)
            if not valid:
                return self._json(start_response, "403 Forbidden", {"error": "denied"})
            self.stop_requested.set()
            if self.exit_callback:
                # Never wait on the current Waitress worker from a request.
                threading.Thread(target=self.exit_callback, name="StudyReview-close", daemon=True).start()
            return self._json(start_response, "200 OK", {"stopping": True, "instance": self.instance})
        if self.stop_requested.is_set():
            return self._json(start_response, "503 Service Unavailable", {"error": "stopping"})
        return self.app(environ, start_response)

    def _run(self):
        try:
            self.server.run()
        except BaseException as error:
            self.error = type(error).__name__  # no business text or secrets in state

    def start(self):
        self.thread.start()
        return self

    def failed(self):
        return self.error is not None or not self.thread.is_alive()

    def write_state(self, path: Path):
        atomic_json(path, {"app": APP_ID, "version": APP_VERSION,
                           "pid": self.owner_pid, "instance": self.instance,
                           "port": self.port, "control_token": self.control_token})

    def remove_state(self, path: Path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("instance") == self.instance and value.get("pid") == self.owner_pid:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass

    def close(self):
        if os.getpid() != self.owner_pid:
            raise DesktopError("不能停止其他进程拥有的本机服务。")
        with self._mutex:
            if self._closed:
                return
            self._closed = True
        self.stop_requested.set()
        # A single-socket Waitress server.close() does not shut down its workers.
        # Shut down the dispatcher and all sockets in this server's private map.
        self.server.task_dispatcher.shutdown(timeout=5)
        remaining_workers = getattr(self.server.task_dispatcher, "threads", ())
        self.server.close()
        for channel in list(self.socket_map.values()):
            channel.close()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise DesktopError("本机服务仍在退出；没有强制结束其他进程，请稍后再启动。")
        if isinstance(remaining_workers, (set, list, tuple)) and remaining_workers:
            raise DesktopError("仍有本次窗口请求正在结束，不能确认干净退出；没有强制结束其他进程。")


def request_stop(state_path: Path, opener=None):
    """Cooperative stop, authenticated to the exact live desktop instance.

    Stale or malicious PID files never result in os.kill/taskkill calls.
    """
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if (value.get("app") != APP_ID or str(value.get("version")) != APP_VERSION
                or type(value.get("port")) is not int or not 1 <= value["port"] <= 65535
                or type(value.get("pid")) is not int or value["pid"] <= 0
                or not isinstance(value.get("instance"), str) or len(value["instance"]) != 32
                or not isinstance(value.get("control_token"), str) or len(value["control_token"]) < 32):
            raise ValueError
    except (OSError, ValueError, KeyError, AttributeError):
        raise DesktopError("未找到可验证的独立窗口实例；没有结束任何进程。") from None
    base_url = f"http://127.0.0.1:{value['port']}"
    client = opener or local_opener()
    try:
        identity = get_local_json(base_url + IDENTITY_PATH, opener=client)
        if (identity.get("app") != APP_ID or identity.get("version") != APP_VERSION
                or identity.get("instance") != value["instance"]
                or identity.get("pid") != value["pid"]):
            raise DesktopError("实例身份与本地记录不符，已拒绝停止。")
        request = Request(base_url + CONTROL_PATH, data=b"", method="POST", headers={
            "X-Study-Desktop-Token": value["control_token"],
            "X-Study-Desktop-Instance": value["instance"],
        })
        with client.open(request, timeout=3) as response:
            result = json.loads(response.read(8192).decode("utf-8"))
        if result.get("stopping") is not True or result.get("instance") != value["instance"]:
            raise DesktopError("实例没有确认退出请求；没有结束任何进程。")
    except (URLError, OSError, ValueError, AttributeError):
        raise DesktopError("独立窗口未响应有效的停止请求；没有强制结束任何进程。") from None
    return True
