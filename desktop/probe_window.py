"""Synthetic real-WebView2 integration probe. No business DB or model provider.

Run explicitly with `python -m desktop.probe_window` after dependencies are
installed. It opens a short-lived test window and records actual native events.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import threading
import time

from desktop.runtime import DesktopError, OwnedServer, wait_for_health
from desktop.webview_window import open_window


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>拾习 · 独立窗口合成验证</title><style>
body{margin:10vh 8vw;background:#f7f2ed;color:#171717;font:18px/1.8 'Microsoft YaHei',sans-serif}
h1{font-size:56px;font-weight:400;border-top:3px solid #da291c;padding-top:20px}
small{font-size:14px}a{color:#171717}</style><small>仅合成窗口 · 没有学习数据库</small>
<h1>拾习</h1><p>独立窗口生命周期与本机导航验证。</p><a href="/internal/">本机页面</a>
</html>"""


def app(environ, start_response):
    if environ.get("PATH_INFO") == "/health/":
        body = b'{"app":"studyreview","version":"2.0","db":true}'
        mime = "application/json"
    else:
        body = PAGE.encode("utf-8")
        mime = "text/html; charset=utf-8"
    start_response("200 OK", [("Content-Type", mime), ("Content-Length", str(len(body)))])
    return [body]


def main(argv=None):
    parser = argparse.ArgumentParser(description="合成 WSGI + 实际 WebView2，不打开真实数据库")
    parser.add_argument("--output", default=str(Path(__file__).parent / "evidence" / "window-probe.json"))
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    report = {"synthetic": True, "business_database_opened": False,
              "real_ai_called": False, "started_utc": datetime.now(timezone.utc).isoformat(),
              "checks": [], "status": "running"}
    server = None
    secondary = None
    observed_secondary_requests = []
    profile = Path(__file__).parent / "evidence" / "private" / (
        "webview-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    profile.mkdir(parents=True, exist_ok=False)
    # Preserve the synthetic profile for diagnosis. Never recursively delete a
    # cache that WebView2 may still have open, and keep all writes in our scope.
    report["synthetic_profile_retained"] = True

    def check(name, passed, detail=None):
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            raise DesktopError("实际窗口检查失败：" + name)

    def wait_until(condition, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(.1)
        return False

    def native_eval(window, script, seconds=3):
        """Bounded host-side JS without eval/pywebview bridge dependency."""
        from System import Action
        started = threading.Event()
        state = {}
        def begin():
            try:
                state["task"] = window.native.webview.CoreWebView2.ExecuteScriptAsync(script)
            except Exception:
                state["error"] = True
            finally:
                started.set()
        window.native.BeginInvoke(Action(begin))
        if not started.wait(seconds) or "error" in state:
            raise DesktopError("原生诊断脚本未启动。")
        task = state["task"]
        if not wait_until(lambda: task.IsCompleted, seconds=seconds):
            raise DesktopError("原生诊断脚本超时。")
        if task.IsFaulted or task.IsCanceled:
            raise DesktopError("原生诊断脚本失败。")
        return json.loads(str(task.Result))

    def current_url(window):
        return native_eval(window, "document.URL")

    def capture_page(window, guard):
        from System import Action
        from System.IO import FileStream, FileMode
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        screenshot = output.with_suffix(".png")
        stream = FileStream(str(screenshot), FileMode.Create)
        started = threading.Event()
        state = {}
        def begin():
            try:
                state["task"] = guard.core.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream)
                state["native_title"] = str(window.native.Text)
            except Exception:
                state["error"] = True
            finally:
                started.set()
        try:
            window.native.BeginInvoke(Action(begin))
            if not started.wait(3) or "error" in state:
                raise DesktopError("原生页面截图未启动。")
            task = state["task"]
            if not wait_until(lambda: task.IsCompleted, seconds=5) or task.IsFaulted or task.IsCanceled:
                raise DesktopError("原生页面截图未完成。")
            report["screenshot"] = str(screenshot)
            report["native_window_title"] = state["native_title"]
        finally:
            stream.Dispose()

    def probe(window, guard):
        try:
            check("native_guard_installed", guard.installed.is_set())
            check("own_resource_filter_registered", guard.resource_filter_registered)
            check("actual_local_page_loaded", wait_until(
                lambda: current_url(window) == server.base_url + "/"
                and native_eval(window, "document.readyState === 'complete' && document.title === '拾习 · 独立窗口合成验证'")))
            check("no_python_functions_exposed", native_eval(window,
                "Object.keys(window.pywebview?.api || {}).length") == 0)
            check("synthetic_page_title", native_eval(window, "document.title") == "拾习 · 独立窗口合成验证")
            capture_page(window, guard)
            check("native_render_capture_created", output.with_suffix(".png").stat().st_size > 1000)
            native_eval(window, """window.__previewLoaded=false;
const pixel=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jL1cAAAAASUVORK5CYII='),c=>c.charCodeAt(0));
const preview=document.createElement('img');preview.onload=()=>window.__previewLoaded=preview.naturalWidth===1;
preview.src=URL.createObjectURL(new Blob([pixel],{type:'image/png'}));document.body.append(preview);""")
            check("local_blob_image_preview", wait_until(lambda: native_eval(window, "window.__previewLoaded === true")))
            native_eval(window, "location.href='/internal/'")
            check("allowed_internal_navigation", wait_until(
                lambda: current_url(window) == server.base_url + "/internal/"
                and native_eval(window, "document.readyState === 'complete'")))
            native_eval(window, "window.open('/internal-popup/','_blank')")
            check("internal_popup_reuses_window", wait_until(
                lambda: current_url(window) == server.base_url + "/internal-popup/"
                and native_eval(window, "document.readyState === 'complete'")))
            previous = current_url(window)
            before = guard.blocked_navigations
            native_eval(window, "location.href='https://example.invalid/blocked-navigation'")
            check("external_navigation_native_cancel", wait_until(
                lambda: guard.blocked_navigations > before))
            check("external_navigation_keeps_local_page", current_url(window) == previous)
            before = guard.blocked_popups
            native_eval(window, "window.open('https://example.invalid/blocked-popup','_blank')")
            check("external_popup_native_handled", wait_until(lambda: guard.blocked_popups > before))
            check("external_popup_keeps_local_page", current_url(window) == previous)
            before = guard.blocked_resources
            image_target = secondary.base_url + "/blocked-image.png"
            native_eval(window, "(()=>{const image=document.createElement('img'); image.src=" + json.dumps(image_target) + ";document.body.append(image)})()")
            check("external_subresource_native_blocked", wait_until(
                lambda: guard.blocked_resources > before))
            check("cross_origin_observer_received_zero_requests", not observed_secondary_requests)
            before = guard.blocked_navigations + guard.blocked_resources
            native_eval(window, "(()=>{const iframe=document.createElement('iframe');iframe.src='https://example.invalid/blocked-frame';document.body.append(iframe)})()")
            check("external_frame_native_blocked", wait_until(
                lambda: guard.blocked_navigations + guard.blocked_resources > before))
            # A file URL must never be navigated even by a direct native Navigate.
            before = guard.blocked_navigations
            from System import Action
            window.native.Invoke(Action(lambda: guard.core.Navigate("file:///C:/Windows/win.ini")))
            check("file_navigation_native_cancel", wait_until(lambda: guard.blocked_navigations > before))
            check("file_navigation_keeps_local_page", current_url(window) == previous)
            from webview import windows
            check("exactly_one_window", len(windows) == 1)
            report["counters"] = {"navigations": guard.blocked_navigations,
                                   "popups": guard.blocked_popups,
                                   "resources": guard.blocked_resources,
                                   "cross_origin_observer_requests":len(observed_secondary_requests)}
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["error_type"] = type(error).__name__
            report["error"] = str(error) if isinstance(error, DesktopError) else "原生窗口验证异常"
            try:
                report["synthetic_failure_diagnostic"] = {
                    "current_url": current_url(window),
                    "page": native_eval(window, "({url:document.URL,title:document.title,state:document.readyState,text:document.body?.innerText?.slice(0,300)})"),
                    "guard": {"installed":guard.installed.is_set(), "error":guard.error,
                              "navigations":guard.blocked_navigations,
                              "popups":guard.blocked_popups,"resources":guard.blocked_resources},
                }
            except Exception:
                report["synthetic_failure_diagnostic"] = "unavailable"
        finally:
            window.destroy()

    try:
        for package in ("pywebview", "waitress", "pythonnet", "clr_loader"):
            try:
                report.setdefault("versions", {})[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                report.setdefault("versions", {})[package] = "not installed"
        server = OwnedServer(app).start()
        def observer(environ, start_response):
            observed_secondary_requests.append(environ.get("PATH_INFO"))
            start_response("200 OK", [("Content-Type","image/png"),("Content-Length","0")])
            return [b""]
        secondary = OwnedServer(observer).start()
        wait_for_health(server.base_url, timeout=3, stopped=server.failed)
        check("actual_loopback_wsgi_health", True)
        open_window(server, profile, smoke_seconds=45, on_ready=probe)
        if report["status"] == "running":
            report["status"] = "failed"
            report["error"] = "诊断未完成，窗口已按时关闭。"
    except DesktopError as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        if server:
            try:
                server.close()
                check("owned_server_thread_exited", not server.thread.is_alive())
            except DesktopError as error:
                report["status"] = "failed"
                report["stop_error"] = str(error)
        if secondary:
            secondary.close()
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]),
                      "output": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
