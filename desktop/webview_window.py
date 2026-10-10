"""Windows WebView2 adapter. Native events, not page JavaScript, enforce origin."""
from __future__ import annotations

import os
import threading

from .runtime import DesktopError, NavigationPolicy


STARTING_HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>拾习</title><style>body{margin:8vh 8vw;background:#f7f2ed;color:#171717;
font:18px/1.8 'Microsoft YaHei',sans-serif}h1{font-weight:400}p{max-width:34em}</style>
<h1>拾习</h1><p>本机服务已就绪，正在打开学习空间……</p></html>"""


def webview2_installed():
    """Read-only Evergreen runtime check. Never installs a runtime."""
    if os.name != "nt":
        return False
    import winreg
    runtime_id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for prefix in ("SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\",
                       "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\"):
            try:
                with winreg.OpenKey(hive, prefix + runtime_id) as key:
                    value, _ = winreg.QueryValueEx(key, "pv")
                if str(value) not in {"", "0", "0.0.0.0"}:
                    return True
            except OSError:
                continue
    return False


class WebView2Guard:
    """Retain handlers for pythonnet and install before loading app content.

    pywebview's default popup handler can open an external system browser. It is
    removed and replaced, and global OPEN_EXTERNAL_LINKS_IN_BROWSER is disabled
    as a second guard. Unknown versions fail closed instead of dropping controls.
    """
    def __init__(self, window, base_url, on_failure=None):
        self.window = window
        self.policy = NavigationPolicy(base_url)
        self.on_failure = on_failure
        self.installed = threading.Event()
        self.error = None
        self.control = None
        self.core = None
        self.blocked_navigations = 0
        self.blocked_popups = 0
        self.blocked_resources = 0
        self.resource_filter_registered = False

    def navigation_starting(self, _sender, args):
        if not self.policy.allows(str(args.Uri)):
            args.Cancel = True
            self.blocked_navigations += 1

    def frame_navigation_starting(self, sender, args):
        self.navigation_starting(sender, args)

    def new_window_requested(self, _sender, args):
        # Keep one window. An allowed internal target opens in this window.
        args.Handled = True
        target = str(args.Uri)
        if self.policy.allows(target):
            self.core.Navigate(target)
        else:
            self.blocked_popups += 1

    def download_starting(self, _sender, args):
        # Learning files are selected/uploaded by the website, not downloaded
        # through arbitrary browser destinations or external content.
        args.Cancel = True

    def web_resource_requested(self, _sender, args):
        if self.policy.allows_resource(str(args.Request.Uri), str(args.ResourceContext)):
            return
        # Reject external subresources as well as top-level navigation. The
        # initialization document has inline CSS and no network dependencies.
        args.Response = self.core.Environment.CreateWebResourceResponse(
            None, 403, "Blocked", "Content-Type: text/plain\r\nCache-Control: no-store")
        self.blocked_resources += 1

    def _fail(self):
        self.error = "窗口安全初始化失败，已关闭；请检查完整程序包与 WebView2 运行库。"
        if self.on_failure:
            self.on_failure()
        # before_show is synchronous. pywebview.destroy() waits for "shown",
        # so do not call it on that same UI thread and deadlock initialization.
        threading.Thread(target=self.window.destroy, name="StudyReview-guard-failure", daemon=True).start()

    def _attach_core(self):
        if self.installed.is_set():
            return
        self.core = self.control.CoreWebView2
        if self.core is None:
            raise DesktopError("WebView2 没有完成初始化。")
        browser = self.window.native.browser
        if not hasattr(browser, "on_new_window_request"):
            raise DesktopError("当前窗口引擎没有可验证的弹窗拦截接口。")
        self.core.NewWindowRequested -= browser.on_new_window_request
        self.core.NewWindowRequested += self.new_window_requested
        self.core.NavigationStarting += self.navigation_starting
        self.core.FrameNavigationStarting += self.frame_navigation_starting
        self.core.DownloadStarting += self.download_starting
        from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
        # Register our own filter explicitly; pywebview's present implementation
        # also registers one, but security must not depend on that side effect.
        self.core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
        self.resource_filter_registered = True
        self.core.WebResourceRequested += self.web_resource_requested
        config = self.core.Settings
        config.AreDevToolsEnabled = False
        config.AreDefaultContextMenusEnabled = False
        config.AreHostObjectsAllowed = False
        if hasattr(config, "IsGeneralAutofillEnabled"):
            config.IsGeneralAutofillEnabled = False
        if hasattr(config, "IsPasswordAutosaveEnabled"):
            config.IsPasswordAutosaveEnabled = False
        self.installed.set()
        # This method runs on the native UI thread; no user code is exposed.
        self.core.Navigate(self.policy.origin + "/")

    def initialization_completed(self, _sender, args):
        if not args.IsSuccess:
            self._fail()
            return
        try:
            self._attach_core()
        except Exception:
            self._fail()

    def before_show(self):
        try:
            self.control = self.window.native.webview
            if self.control.CoreWebView2 is not None:
                self._attach_core()
            else:
                self.control.CoreWebView2InitializationCompleted += self.initialization_completed
        except Exception:
            self._fail()


def open_window(server, profile, smoke_seconds=0, on_ready=None):
    if os.name != "nt":
        raise DesktopError("此独立窗口版本目前只验证 Windows + WebView2。")
    if not webview2_installed():
        raise DesktopError("未检测到 Microsoft Edge WebView2 Runtime。请按文档由用户安装官方运行库；程序不会自动安装。")
    try:
        import webview
    except ImportError:
        raise DesktopError("缺少 pywebview 依赖。请使用完整程序包或按依赖说明安装。") from None
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["IGNORE_SSL_ERRORS"] = False
    webview.settings["REMOTE_DEBUGGING_PORT"] = None
    window = webview.create_window(
        "拾习 · 学习与复习", html=STARTING_HTML, js_api=None,
        width=1280, height=880, min_size=(390, 600),
        background_color="#F7F2ED", text_select=True,
    )
    guard = WebView2Guard(window, server.base_url, on_failure=server.stop_requested.set)
    window.events.before_show += guard.before_show
    window.events.closed += server.stop_requested.set
    server.exit_callback = window.destroy

    def verify_renderer(renderer):
        if renderer != "edgechromium":
            guard.error = "实际窗口引擎不是 WebView2，已拒绝启动。"
            return False

    window.events.initialized += verify_renderer

    def supervise():
        if not guard.installed.wait(timeout=20):
            guard.error = "WebView2 窗口初始化超时，请检查运行库。"
            window.destroy()
            return
        if on_ready:
            on_ready(window, guard)
        deadline = None if not smoke_seconds else __import__("time").monotonic() + smoke_seconds
        while not server.stop_requested.wait(.25):
            if server.failed() or (deadline and __import__("time").monotonic() >= deadline):
                window.destroy()
                return

    supervisor = threading.Thread(target=supervise, name="StudyReview-supervisor", daemon=True)
    supervisor.start()
    smoke_timer = None
    if smoke_seconds:
        smoke_timer = threading.Timer(smoke_seconds, window.destroy)
        smoke_timer.daemon = True
        smoke_timer.start()
    try:
        # Own our daemon supervisor instead of pywebview's unbounded,
        # non-daemon func thread. Diagnostic callbacks cannot keep the
        # whole application alive after its window has been closed.
        webview.start(gui="edgechromium", debug=False,
                      private_mode=False, storage_path=str(profile), http_server=False)
    except Exception:
        raise DesktopError("独立窗口启动失败；请检查 WebView2、.NET 和完整依赖，程序未降级到旧浏览器引擎。") from None
    finally:
        server.exit_callback = None
        if smoke_timer:
            smoke_timer.cancel()
        server.stop_requested.set()
    if guard.error:
        raise DesktopError(guard.error)
    if not guard.installed.is_set():
        raise DesktopError("窗口没有完成安全初始化，未报告启动成功。")
    return guard
