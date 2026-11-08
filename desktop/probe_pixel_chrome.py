"""Isolated loopback HTML native chrome diagnostics; no database or app profile."""
import ctypes
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview

from desktop.pixel_chrome import DEFAULT_CANVAS, SECTION_CANVASES, canvas_for_url, install_pixel_chrome

result = {'production_data_accessed': False, 'checks': {}}
output = Path(__file__).resolve().parents[2] / 'chrome-v5-validation' / 'native-chrome-results.json'


class SyntheticPage(BaseHTTPRequestHandler):
    def do_GET(self):
        rgb = canvas_for_url('http://127.0.0.1' + self.path)
        color = '#' + ''.join(f'{c:02x}' for c in rgb)
        page = ('<!doctype html><html><meta charset="utf-8">'
                '<body style="margin:0;background:' + color + ';font-family:sans-serif">'
                '<main style="margin:32px"><h1>拾习 / STUDY REVIEW</h1>'
                '<p>Isolated native chrome diagnostic</p>'
                '<button>Web content focus target</button></main></body></html>').encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticPage)
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{server.server_port}'
w = webview.create_window('StudyReview chrome diagnostic', url=origin + '/', width=800,
                          height=600, min_size=(390, 600), confirm_close=True, js_api=None)
w.events.before_show += lambda: result['checks'].update(installed=install_pixel_chrome(w))


def worker():
    from System import Action
    from System.Windows.Forms import FormWindowState, Screen

    f = w.native

    def ui(fn):
        state = {}
        def run():
            state['value'] = fn()
        f.Invoke(Action(run))
        return state.get('value')

    def wait_for(fn, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if ui(fn):
                return True
            time.sleep(.05)
        return False

    try:
        time.sleep(.5)
        bar = w._pixel_chrome[0][0]
        edges = w._pixel_chrome[0][1:]
        buttons = list(bar.Controls)
        minimize, maximize, close = buttons
        result['buttons'] = ui(lambda: [
            {'text': str(c.Text), 'accessible_name': str(c.AccessibleName),
             'tooltip': str(w._pixel_chrome[2][0].GetToolTip(c)),
             'x': int(c.Left), 'width': int(c.Width), 'tab_index': int(c.TabIndex),
             'tab_stop': bool(c.TabStop)} for c in buttons])
        result['bar_height'] = int(bar.Height)
        result['device_dpi'] = int(f.DeviceDpi)
        result['checks']['titleless'] = not str(bar.Text) and all(
            c.GetType().Name == 'Button' for c in buttons)
        result['checks']['button_order'] = minimize.Left < maximize.Left < close.Left
        result['checks']['accessible_controls'] = all(
            c['accessible_name'] and c['tooltip'] and c['tab_stop'] and c['width'] >= 44
            for c in result['buttons'])
        result['checks']['native_focus'] = ui(lambda: minimize.Focus() and minimize.Focused)
        result['checks']['native_tab_next'] = ui(
            lambda: bar.SelectNextControl(minimize, True, True, True, False) and maximize.Focused)

        palettes = {'overview': DEFAULT_CANVAS, **SECTION_CANVASES}
        result['palette_checks'] = {}
        for section, rgb in palettes.items():
            route = '/' if section == 'overview' else '/' + section + '/'
            ui(lambda path=route: f.webview.CoreWebView2.Navigate(origin + path))
            result['palette_checks'][section] = wait_for(
                lambda expected=rgb, path=route: str(f.webview.Source).rstrip('/') ==
                (origin + path).rstrip('/') and all(
                    (c.BackColor.R, c.BackColor.G, c.BackColor.B) == expected
                    for c in [f, bar, *edges, *buttons]))
        result['checks']['all_page_palettes_match'] = all(result['palette_checks'].values())
        result['checks']['no_painted_edge_border'] = all(int(e.BorderStyle) == 0 for e in edges)
        from ctypes import wintypes
        user32_geometry = ctypes.WinDLL('user32')
        user32_geometry.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32_geometry.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32_geometry.ShowWindow.restype = wintypes.BOOL
        user32_geometry.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        def native_rect(control):
            rect = wintypes.RECT()
            user32_geometry.GetWindowRect(int(control.Handle.ToInt64()), ctypes.byref(rect))
            return [rect.left, rect.top, rect.right, rect.bottom]

        def geometry():
            return {
                'state': str(f.WindowState), 'native_rect': native_rect(f),
                'managed_bounds': str(f.Bounds), 'client_size': str(f.ClientSize),
                'controls': [
                    {'name': str(c.Name or c.GetType().Name),
                     'managed_bounds': str(c.Bounds), 'native_rect': native_rect(c),
                     'visible': bool(c.Visible)}
                    for c in [f.webview, bar, *edges, *buttons]],
            }

        def children_within_form(snapshot):
            left, top, right, bottom = snapshot['native_rect']
            return all(
                left <= c['native_rect'][0] <= c['native_rect'][2] <= right
                and top <= c['native_rect'][1] <= c['native_rect'][3] <= bottom
                for c in snapshot['controls'] if c['visible'])

        result['restore_geometry'] = {'baseline': ui(geometry)}
        result['checks']['baseline_child_bounds'] = children_within_form(result['restore_geometry']['baseline'])
        restore_methods = (
            ('managed_normal', lambda: setattr(f, 'WindowState', FormWindowState.Normal)),
            ('show_restore', lambda: user32_geometry.ShowWindow(int(f.Handle.ToInt64()), 9)),
            ('show_normal', lambda: user32_geometry.ShowWindow(int(f.Handle.ToInt64()), 1)),
            ('system_restore', lambda: user32_geometry.PostMessageW(int(f.Handle.ToInt64()), 0x112, 0xF120, 0)),
        )
        for method, restore in restore_methods:
            ui(lambda: minimize.PerformClick())
            result['checks']['minimize_' + method] = ui(lambda: f.WindowState == FormWindowState.Minimized)
            result['restore_geometry'][method + '_minimized'] = ui(geometry)
            ui(restore)
            wait_for(lambda: f.WindowState != FormWindowState.Minimized)
            time.sleep(.2)
            snapshot = ui(geometry)
            result['restore_geometry'][method] = snapshot
            result['checks']['restore_child_bounds_' + method] = children_within_form(snapshot)
            result['checks']['restored_normal_' + method] = snapshot['state'] == 'Normal'
        ui(lambda: maximize.PerformClick())
        result['checks']['maximize'] = ui(lambda: f.WindowState == FormWindowState.Maximized)
        result['checks']['maximized_edges_hidden'] = ui(lambda: all(not e.Visible for e in edges))
        result['checks']['maximize_accessible_name_updates'] = ui(lambda: str(maximize.AccessibleName) == '还原')
        result['maximized_bounds'] = ui(lambda: str(f.Bounds))
        result['working_area'] = ui(lambda: str(Screen.FromControl(f).WorkingArea))
        result['checks']['respects_work_area'] = ui(lambda: f.Bounds == Screen.FromControl(f).WorkingArea)
        ui(lambda: maximize.PerformClick())
        result['checks']['restore'] = ui(lambda: f.WindowState == FormWindowState.Normal)
        result['checks']['restored_resize_targets'] = ui(lambda: all(e.Visible for e in edges))
        result['checks']['restore_accessible_name_updates'] = ui(lambda: str(maximize.AccessibleName) == '最大化')
        user32 = ctypes.WinDLL('user32')
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

        def dismiss(code):
            for _ in range(100):
                dialog = user32.FindWindowW('#32770', 'StudyReview chrome diagnostic')
                if dialog:
                    result['checks']['confirmation_dialog_' + str(code)] = True
                    user32.PostMessageW(dialog, 0x111, code, 0)
                    return
                time.sleep(.05)

        threading.Thread(target=dismiss, args=(2,), daemon=True).start()
        ui(lambda: close.PerformClick())
        result['checks']['close_cancel_preserves_window'] = ui(lambda: not f.IsDisposed and f.Visible)
        threading.Thread(target=dismiss, args=(1,), daemon=True).start()
        # This is Alt-F4's native command, not a physical keyboard test.
        result['checks']['alt_f4_command_sent'] = bool(
            user32.PostMessageW(int(f.Handle.ToInt64()), 0x112, 0xF060, 0))
    except Exception as exc:
        result['error'] = repr(exc)
        w.confirm_close = False
        w.destroy()


def timeout():
    result['error'] = 'Diagnostic exceeded 45 seconds'
    w.confirm_close = False
    w.destroy()


timer = threading.Timer(45, timeout)
timer.daemon = True
timer.start()
threading.Thread(target=lambda: (w.events.loaded.wait(), worker()), daemon=True).start()
webview.start(gui='edgechromium', private_mode=True, http_server=False)
timer.cancel()
server.shutdown()
result['checks']['confirmed_close_completed'] = 'error' not in result
result['unverified'] = [
    'Physical title dragging, including drag from maximized state and double-click',
    'Physical edge/corner resize and minimum-size enforcement',
    'Actual keyboard Alt-F4 and Tab gestures, browser-to-native focus transition',
    'Multiple monitors, high contrast and DPI changes',
]
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
raise SystemExit(0 if all(result['checks'].values()) and 'error' not in result else 1)

