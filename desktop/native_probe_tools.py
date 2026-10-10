"""Bounded host-only diagnostics for explicit desktop integration probes.

Nothing in this module is exposed through js_api or window.expose.
"""
import json
from pathlib import Path
import threading
import time

from .runtime import DesktopError


def wait_until(condition, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(.1)
    return False


class NativeProbeTools:
    def __init__(self, window):
        self.window = window

    def invoke(self, function, seconds=3):
        from System import Action
        event = threading.Event()
        state = {}
        def begin():
            try:
                state["value"] = function()
            except Exception:
                state["error"] = True
            finally:
                event.set()
        self.window.native.BeginInvoke(Action(begin))
        if not event.wait(seconds) or state.get("error"):
            raise DesktopError("原生诊断操作未启动。")
        return state.get("value")

    def await_task(self, task, seconds=5):
        if not wait_until(lambda: task.IsCompleted, seconds=seconds):
            raise DesktopError("原生诊断操作超时。")
        if task.IsFaulted or task.IsCanceled:
            raise DesktopError("原生诊断操作失败。")

    def execute(self, script, seconds=3):
        task = self.invoke(lambda: self.window.native.webview.CoreWebView2.ExecuteScriptAsync(script))
        self.await_task(task, seconds=seconds)
        return json.loads(str(task.Result))

    def current_url(self):
        return self.execute("document.URL")

    def capture_png(self, output):
        from System.IO import FileStream, FileMode
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        stream = FileStream(str(output), FileMode.Create)
        try:
            task = self.invoke(lambda: self.window.native.webview.CoreWebView2.CapturePreviewAsync(
                CoreWebView2CapturePreviewImageFormat.Png, stream))
            self.await_task(task)
        finally:
            stream.Dispose()
        return {"screenshot":str(output), "native_title":self.invoke(lambda: str(self.window.native.Text)),
                "bytes":output.stat().st_size}
