"""Quiet native window controls, without a page bridge or security changes."""
from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_CANVAS = (233, 234, 213)
# Keep in sync with pixel-scenery.css; focus uses pixel-valley.css's canvas.
SECTION_CANVASES = {
    'courses': (226, 233, 219), 'tasks': (238, 230, 206),
    'questions': (234, 224, 220), 'reviews': (221, 232, 227),
    'statistics': (224, 228, 231), 'backup': (233, 226, 206),
    'focus': (246, 242, 233),
}


def canvas_for_url(url):
    """Choose a static palette from a native loopback URL, never page content."""
    try:
        parsed = urlsplit(str(url))
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username is not None or parsed.password is not None):
            return DEFAULT_CANVAS
        section = parsed.path.strip('/').split('/', 1)[0]
        return SECTION_CANVASES.get(section, DEFAULT_CANVAS)
    except (ValueError, TypeError):
        return DEFAULT_CANVAS


def resize_hit(code, x, y, width, height, corner=16):
    """Win32 HT* resize targets, including corners approached from either edge."""
    if code in (12, 15):
        if x < corner:
            return 13 if code == 12 else 16
        if x >= width - corner:
            return 14 if code == 12 else 17
    if code in (10, 11):
        if y < corner:
            return 13 if code == 10 else 14
        if y >= height - corner:
            return 16 if code == 10 else 17
    return code


def restore_drag_origin(cursor_x, cursor_y, fraction, width, title_offset):
    """Preserve the grabbed horizontal position, including negative monitors."""
    return (cursor_x - round(width * max(0.0, min(1.0, fraction))),
            cursor_y - title_offset)


def install_pixel_chrome(window):
    """Run in before_show on the WinForms UI thread; revert on any failure."""
    from System.Drawing import Color, Font, Point
    from System.Windows.Forms import (Panel, Button, DockStyle, BorderStyle,
        FormBorderStyle, FormWindowState, FlatStyle, Screen, MouseButtons,
        Cursor, Cursors, ToolTip, AccessibleRole, SystemInformation)
    import ctypes
    from ctypes import wintypes

    form = window.native
    original_border = form.FormBorderStyle
    original_padding = form.Padding
    original_color = form.BackColor
    added, handlers, buttons, edges = [], [], [], []
    resources = []
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t

    def bind(control, event, handler):
        getattr(control, event).__iadd__(handler)
        handlers.append((control, event, handler))

    def native_drag(hit):
        user32.ReleaseCapture()
        user32.SendMessageW(int(form.Handle.ToInt64()), 0xA1, hit, 0)

    def toggle(_sender=None, _args=None):
        if form.WindowState == FormWindowState.Maximized:
            form.WindowState = FormWindowState.Normal
        else:
            form.MaximizedBounds = Screen.FromControl(form).WorkingArea
            form.WindowState = FormWindowState.Maximized

    try:
        scale = max(1.0, float(form.DeviceDpi) / 96)
        bar = Panel()
        bar.Name = 'StudyReviewWindowControls'
        bar.Height = round(26 * scale)
        bar.Dock = DockStyle.Top
        bar.BorderStyle = getattr(BorderStyle, 'None')
        bar.TabStop = False
        bar.AccessibleName = '窗口拖动区域'
        added.append(bar)
        drag = {'start': None, 'fraction': 0.5, 'offset': 0}

        def begin_move(_sender, event):
            if event.Button != MouseButtons.Left:
                return
            if event.Clicks == 2:
                drag['start'] = None
                toggle()
                return
            position = Cursor.Position
            drag.update(start=position,
                        fraction=(position.X - form.Left) / max(1, form.Width),
                        offset=min(event.Y, bar.Height // 2))
            bar.Capture = True

        def move(_sender, event):
            start = drag['start']
            if start is None or event.Button != MouseButtons.Left:
                return
            position = Cursor.Position
            threshold = SystemInformation.DragSize
            if (abs(position.X - start.X) < threshold.Width // 2
                    and abs(position.Y - start.Y) < threshold.Height // 2):
                return
            drag['start'] = None
            bar.Capture = False
            if form.WindowState == FormWindowState.Maximized:
                form.WindowState = FormWindowState.Normal
                x, y = restore_drag_origin(position.X, position.Y, drag['fraction'],
                                           form.Width, drag['offset'])
                form.Location = Point(x, y)
            else:
                # The threshold-crossing move may be the only MouseMove in a
                # quick/coalesced drag. Apply it before entering the OS loop;
                # otherwise that initial displacement is silently discarded.
                form.Location = Point(form.Left + position.X - start.X,
                                      form.Top + position.Y - start.Y)
            native_drag(2)  # HTCAPTION uses the standard Windows move loop.

        def end_move(_sender, _event):
            drag['start'] = None
            bar.Capture = False

        bind(bar, 'MouseDown', begin_move)
        bind(bar, 'MouseMove', move)
        bind(bar, 'MouseUp', end_move)
        tooltip = ToolTip()
        resources.append(tooltip)
        for index, (caption, accessible, action) in enumerate((
            ('−', '最小化', lambda s, e: setattr(form, 'WindowState', FormWindowState.Minimized)),
            ('□', '最大化', toggle),
            ('×', '关闭', lambda s, e: form.Close()),
        )):
            button = Button()
            button.Text = caption
            button.AccessibleName = accessible
            button.AccessibleRole = AccessibleRole.PushButton
            button.Width = round(44 * scale)
            button.Dock = DockStyle.Right
            button.FlatStyle = FlatStyle.Flat
            button.FlatAppearance.BorderSize = 0
            button.UseVisualStyleBackColor = False
            button.ForeColor = Color.FromArgb(67, 76, 62)
            button.Font = Font('Segoe UI', 11)
            button.TabStop = True
            button.TabIndex = index
            tooltip.SetToolTip(button, accessible)
            bind(button, 'Click', action)
            bar.Controls.Add(button)
            buttons.append(button)

        cursors = {10: Cursors.SizeWE, 11: Cursors.SizeWE,
                   12: Cursors.SizeNS, 15: Cursors.SizeNS,
                   13: Cursors.SizeNWSE, 17: Cursors.SizeNWSE,
                   14: Cursors.SizeNESW, 16: Cursors.SizeNESW}
        # These input targets have exactly the canvas color: no painted frame.
        for dock, hit in ((DockStyle.Left, 10), (DockStyle.Right, 11),
                          (DockStyle.Bottom, 15), (DockStyle.Top, 12)):
            edge = Panel()
            edge.Name = 'StudyReviewResize' + str(hit)
            edge.Dock = dock
            edge.Width = edge.Height = round(4 * scale)
            edge.BorderStyle = getattr(BorderStyle, 'None')
            edge.TabStop = False

            def target(sender, event, code=hit):
                return resize_hit(code, event.X, event.Y, sender.Width, sender.Height,
                                  round(16 * scale))

            def resize(sender, event, get_target=target):
                if event.Button == MouseButtons.Left and form.WindowState != FormWindowState.Maximized:
                    native_drag(get_target(sender, event))

            def resize_cursor(sender, event, get_target=target):
                sender.Cursor = cursors[get_target(sender, event)]

            bind(edge, 'MouseDown', resize)
            bind(edge, 'MouseMove', resize_cursor)
            added.append(edge)
            edges.append(edge)

        def sync_state(_sender=None, _args=None):
            maximized = form.WindowState == FormWindowState.Maximized
            for edge in edges:
                edge.Visible = not maximized
            buttons[1].Text = '❐' if maximized else '□'
            buttons[1].AccessibleName = '还原' if maximized else '最大化'
            tooltip.SetToolTip(buttons[1], buttons[1].AccessibleName)

        def sync_palette(_sender=None, _args=None):
            rgb = canvas_for_url(str(form.webview.Source))
            color = Color.FromArgb(*rgb)
            form.BackColor = color
            for control in added + buttons:
                control.BackColor = color
            hover = Color.FromArgb(*(max(0, c - 14) for c in rgb))
            for button in buttons:
                button.FlatAppearance.MouseOverBackColor = hover
                button.FlatAppearance.MouseDownBackColor = Color.FromArgb(*(max(0, c - 25) for c in rgb))
            buttons[2].FlatAppearance.MouseOverBackColor = Color.FromArgb(230, 189, 175)

        form.SuspendLayout()
        for control in added:
            form.Controls.Add(control)
        form.FormBorderStyle = getattr(FormBorderStyle, 'None')
        # Native notifications only choose a constant color. They never read or
        # execute scripts, expose host objects, or alter navigation.
        bind(form.webview, 'NavigationCompleted', sync_palette)
        bind(form, 'Resize', sync_state)
        sync_palette()
        sync_state()
        # Keep delegates, controls and tooltip alive for pythonnet's event bridge.
        window._pixel_chrome = (added, handlers, resources)
        return True
    except Exception:
        for control, event, handler in reversed(handlers):
            getattr(control, event).__isub__(handler)
        for control in added:
            if form.Controls.Contains(control):
                form.Controls.Remove(control)
            control.Dispose()
        for resource in resources:
            resource.Dispose()
        form.FormBorderStyle = original_border
        form.Padding = original_padding
        form.BackColor = original_color
        return False
    finally:
        form.ResumeLayout(True)

