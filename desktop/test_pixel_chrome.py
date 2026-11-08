"""Native-independent checks; the separate Windows probe exercises real controls."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from desktop.pixel_chrome import (DEFAULT_CANVAS, SECTION_CANVASES, canvas_for_url,
                                  resize_hit, restore_drag_origin)


class ChromeBoundaryTests(unittest.TestCase):
    def test_module_compiles_without_native_imports(self):
        from desktop.pixel_chrome import install_pixel_chrome
        self.assertTrue(callable(install_pixel_chrome))

    def test_adapter_keeps_security_and_confirmation(self):
        source = Path(__file__).with_name('webview_window.py').read_text(encoding='utf-8')
        self.assertIn('js_api=None', source)
        self.assertIn('confirm_close=True', source)
        self.assertIn('window.events.before_show += guard.before_show', source)
        self.assertIn('min_size=(390, 600)', source)

    def test_close_uses_native_confirmation_path(self):
        source = Path(__file__).with_name('pixel_chrome.py').read_text(encoding='utf-8-sig')
        ast.parse(source)
        self.assertIn('form.Close()', source)
        self.assertNotIn('confirm_close = False', source)
        self.assertNotIn('evaluate_js', source)
        self.assertNotIn('ExecuteScript', source)
        self.assertIn('form.FormBorderStyle = original_border', source)
        self.assertIn('Screen.FromControl(form).WorkingArea', source)

    def test_titleless_controls_and_palette_are_native(self):
        source = Path(__file__).with_name('pixel_chrome.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('STUDY REVIEW', source)
        self.assertNotIn('Label()', source)
        self.assertIn("bind(form.webview, 'NavigationCompleted', sync_palette)", source)
        self.assertIn('button.TabStop = True', source)
        self.assertIn('button.Width = round(44 * scale)', source)
        self.assertIn('tooltip.SetToolTip', source)
        self.assertIn('edge.Visible = not maximized', source)

    def test_palettes_match_web_styles(self):
        root = Path(__file__).resolve().parents[1]
        scenery = (root / 'static/css/pixel-scenery.css').read_text(encoding='utf-8-sig').lower()
        valley = (root / 'static/css/pixel-valley.css').read_text(encoding='utf-8-sig').lower()
        def hex_rgb(rgb):
            return '#' + ''.join(f'{c:02x}' for c in rgb)
        self.assertIn('--scene-canvas:' + hex_rgb(DEFAULT_CANVAS), scenery)
        for section, rgb in SECTION_CANVASES.items():
            if section == 'focus':
                self.assertIn('--canvas:' + hex_rgb(rgb), valley)
            else:
                line = next(line for line in scenery.splitlines()
                            if line.startswith(f'body[data-section="{section}"]'))
                self.assertIn('--scene-canvas:' + hex_rgb(rgb), line)

    def test_palette_uses_only_loopback_path(self):
        for host in ('127.0.0.1:8090', 'localhost:8090', '[::1]:8090'):
            for section, color in SECTION_CANVASES.items():
                self.assertEqual(canvas_for_url(f'http://{host}/{section}/42/?next=/tasks/#section'), color)
        for url in ('about:blank', 'file:///courses/', 'https://example.com/courses/',
                    'http://127.0.0.1.evil.test/courses/', 'http://u@localhost/courses/',
                    'http://[broken', None, 'http://127.0.0.1/coursework/',
                    'http://127.0.0.1/accounts/login/?next=/courses/'):
            self.assertEqual(canvas_for_url(url), DEFAULT_CANVAS)

    def test_edges_and_corners_are_resize_targets(self):
        for code in (10, 11, 12, 15):
            self.assertEqual(resize_hit(code, 50, 50, 100, 100), code)
        for code, expected in ((12, (13, 14)), (15, (16, 17))):
            self.assertEqual(resize_hit(code, 0, 2, 100, 4), expected[0])
            self.assertEqual(resize_hit(code, 99, 2, 100, 4), expected[1])
        for code, expected in ((10, (13, 16)), (11, (14, 17))):
            self.assertEqual(resize_hit(code, 2, 0, 4, 100), expected[0])
            self.assertEqual(resize_hit(code, 2, 99, 4, 100), expected[1])

    def test_drag_restore_retains_grab_position(self):
        self.assertEqual(restore_drag_origin(1200, 50, .75, 800, 12), (600, 38))
        self.assertEqual(restore_drag_origin(-1500, 50, .5, 800, 12), (-1900, 38))
        self.assertEqual(restore_drag_origin(120, 50, -1, 800, 12), (120, 38))
        self.assertEqual(restore_drag_origin(120, 50, 2, 800, 12), (-680, 38))

    def run_move_handler(self, end, maximized=False):
        # Execute the real nested handler against inert native stand-ins. This
        # catches dropped first movement without a Windows message loop.
        source = Path(__file__).with_name('pixel_chrome.py').read_text(encoding='utf-8-sig')
        handler = next(node for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.FunctionDef) and node.name == 'move')
        form = SimpleNamespace(Left=51, Top=51, Width=800, Location=(51, 51),
                               WindowState='Maximized' if maximized else 'Normal')
        drag = {'start': SimpleNamespace(X=400, Y=12), 'fraction': .5, 'offset': 12}
        bar = SimpleNamespace(Capture=True)
        native_calls = []
        scope = {
            'form': form, 'drag': drag, 'bar': bar,
            'Cursor': SimpleNamespace(Position=SimpleNamespace(X=end[0], Y=end[1])),
            'SystemInformation': SimpleNamespace(DragSize=SimpleNamespace(Width=4, Height=4)),
            'MouseButtons': SimpleNamespace(Left='Left'),
            'FormWindowState': SimpleNamespace(Maximized='Maximized', Normal='Normal'),
            'Point': lambda x, y: (x, y), 'restore_drag_origin': restore_drag_origin,
            'native_drag': lambda hit: native_calls.append((hit, form.Location)),
        }
        exec(compile(ast.Module(body=[handler], type_ignores=[]), '<move-handler-test>', 'exec'), scope)
        scope['move'](bar, SimpleNamespace(Button='Left'))
        return form, drag, bar, native_calls

    def test_single_normal_move_applies_delta_before_native_loop(self):
        form, drag, bar, calls = self.run_move_handler((500, 82))
        self.assertEqual(form.Location, (151, 121))
        self.assertEqual(calls, [(2, (151, 121))])
        self.assertIsNone(drag['start'])
        self.assertFalse(bar.Capture)

    def test_below_threshold_click_does_not_move(self):
        form, drag, bar, calls = self.run_move_handler((401, 13))
        self.assertEqual(form.Location, (51, 51))
        self.assertEqual(calls, [])
        self.assertIsNotNone(drag['start'])
        self.assertTrue(bar.Capture)

    def test_maximized_move_still_restores_at_grab_position(self):
        form, drag, bar, calls = self.run_move_handler((500, 82), maximized=True)
        self.assertEqual(form.WindowState, 'Normal')
        self.assertEqual(form.Location, (100, 70))
        self.assertEqual(calls, [(2, (100, 70))])


if __name__ == '__main__':
    unittest.main()

