#!/usr/bin/env python3
"""
极简翻译工具 - Double Ctrl to translate selected text
"""

import os
import sys
import time
import asyncio
import tempfile
import queue
import threading
import configparser
import winreg
import tkinter as tk
import ctypes
import requests
import pyperclip
import pystray
from PIL import Image, ImageDraw
from pynput import keyboard as pynkb
from pynput import mouse as pynmouse

# ── 常量 ─────────────────────────────────────────────────────

MODEL                 = "glm-4-flash-250414"
DOUBLE_CLICK_INTERVAL = 0.4
STARTUP_NAME          = "Translator"

BG       = '#1e1e1e'
BG2      = '#252525'
FG_ORIG  = '#555555'
FG_TRANS = '#f0f0f0'
FG_SEP   = '#2e2e2e'
SEL_BG   = '#3a5a8a'
ACCENT   = '#4a9eff'

# ── 路径 & 配置 ───────────────────────────────────────────────

def _app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_app_dir(), 'translator_config.ini')


def load_api_key() -> str:
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding='utf-8')
        return cfg.get('settings', 'api_key', fallback='').strip()
    return ''


def save_api_key(key: str):
    cfg = configparser.ConfigParser()
    cfg['settings'] = {'api_key': key}
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        cfg.write(f)


# ── 开机自启（注册表）────────────────────────────────────────

def is_startup_enabled() -> bool:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(k, STARTUP_NAME)
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def set_startup(enable: bool):
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Run",
                           0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, 'frozen', False):
                # 打包 exe 模式：直接用 exe 路径
                cmd = f'"{sys.executable}"'
            else:
                # 开发模式：pythonw + 脚本路径
                py = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
                script = os.path.abspath(__file__)
                cmd = f'"{py}" "{script}"'
            winreg.SetValueEx(k, STARTUP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, STARTUP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
    except Exception:
        pass


# ── 系统托盘图标 ──────────────────────────────────────────────

def _make_icon() -> Image.Image:
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, 61, 61], fill='#4a9eff')
    d.rectangle([15, 17, 49, 25], fill='white')   # T 横
    d.rectangle([28, 17, 36, 47], fill='white')   # T 竖
    return img


def setup_tray(root: tk.Tk) -> pystray.Icon:
    def on_change_key(icon, item):
        def _do():
            global API_KEY
            key = show_key_dialog(root, current_key=API_KEY)
            if key:
                save_api_key(key)
                API_KEY = key
        root.after(0, _do)

    def on_toggle_startup(icon, item):
        set_startup(not is_startup_enabled())

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.quit)

    menu = pystray.Menu(
        pystray.MenuItem('翻译工具', None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('修改 API Key', on_change_key),
        pystray.MenuItem('开机自启', on_toggle_startup,
                         checked=lambda item: is_startup_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('退出', on_quit),
    )
    icon = pystray.Icon(STARTUP_NAME, _make_icon(),
                        '翻译工具  (双击 Ctrl 翻译选中文字)', menu)
    icon.run_detached()
    return icon


# ── 首次设置 / 修改 Key 弹窗 ──────────────────────────────────

def show_key_dialog(root: tk.Tk, current_key: str = '') -> str | None:
    dialog = tk.Toplevel(root)
    dialog.title("翻译工具 - 设置")
    dialog.resizable(False, False)
    dialog.attributes('-topmost', True)
    dialog.configure(bg=BG)
    dialog.grab_set()
    pad = 24

    tk.Label(dialog, text="翻译工具设置",
             bg=BG, fg='#ffffff', font=('Segoe UI', 13, 'bold')
             ).pack(padx=pad, pady=(pad, 4), anchor='w')

    tk.Label(dialog,
             text="请输入您的 GLM API Key\n免费申请地址：bigmodel.cn  →  API Keys",
             bg=BG, fg='#888888', font=('Segoe UI', 9), justify='left'
             ).pack(padx=pad, anchor='w')

    tk.Frame(dialog, bg='#333333', height=1).pack(fill='x', padx=pad, pady=(14, 0))

    f = tk.Frame(dialog, bg=BG2, padx=12, pady=10)
    f.pack(fill='x', padx=pad, pady=(10, 0))

    tk.Label(f, text="API Key", bg=BG2, fg='#aaaaaa',
             font=('Segoe UI', 9)).pack(anchor='w')

    entry_var = tk.StringVar(value=current_key)
    entry = tk.Entry(f, textvariable=entry_var,
                     bg='#1a1a1a', fg='#f0f0f0', insertbackground='#ffffff',
                     relief='flat', font=('Consolas', 10), width=44, show='*')
    entry.pack(fill='x', pady=(4, 0), ipady=6)

    show_var = tk.BooleanVar()
    tk.Checkbutton(f, text="显示密钥", variable=show_var,
                   command=lambda: entry.config(show='' if show_var.get() else '*'),
                   bg=BG2, fg='#666666', selectcolor=BG2,
                   activebackground=BG2, font=('Segoe UI', 8), borderwidth=0
                   ).pack(anchor='w', pady=(4, 0))

    err_lbl = tk.Label(dialog, text="", bg=BG, fg='#ff6b6b', font=('Segoe UI', 9))
    err_lbl.pack(padx=pad, anchor='w')

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(fill='x', padx=pad, pady=(4, pad))

    result = {'key': None}

    def on_confirm():
        key = entry_var.get().strip()
        if not key:
            err_lbl.config(text="API Key 不能为空")
            return
        if '.' not in key or len(key) < 10:
            err_lbl.config(text="Key 格式不正确，请检查")
            return
        result['key'] = key
        dialog.destroy()

    tk.Button(btn_frame, text="取消",
              bg='#333333', fg='#888888', activebackground='#3a3a3a',
              relief='flat', font=('Segoe UI', 10),
              padx=16, pady=6, cursor='hand2', command=dialog.destroy
              ).pack(side='right', padx=(8, 0))

    tk.Button(btn_frame, text="  确认  ",
              bg=ACCENT, fg='#ffffff', activebackground='#3a8eef',
              relief='flat', font=('Segoe UI', 10, 'bold'),
              padx=16, pady=6, cursor='hand2', command=on_confirm
              ).pack(side='right')

    dialog.bind('<Return>', lambda e: on_confirm())
    dialog.bind('<Escape>', lambda e: dialog.destroy())

    dialog.update_idletasks()
    w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
    dialog.geometry(f'+{(sw-w)//2}+{(sh-h)//2}')
    entry.focus_set()
    dialog.wait_window()
    return result['key']


# ── 翻译 ─────────────────────────────────────────────────────

API_KEY = ''


def detect_lang(text: str) -> str:
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            return 'zh'
    return 'en'


def translate(text: str) -> str:
    prompt = (f"请将以下中文翻译成英文，只输出翻译结果：\n{text}"
              if detect_lang(text) == 'zh' else
              f"请将以下英文翻译成中文，只输出翻译结果：\n{text}")
    try:
        r = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 512, "temperature": 0.3},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[Error: {e}]"


def speak_text(text: str, btn: 'tk.Button', popup: 'tk.Toplevel'):
    """TTS via edge-tts → temp MP3 → Windows MCI playback."""
    def _do():
        path = None
        try:
            import edge_tts
            lang = detect_lang(text)
            voice = ('zh-CN-XiaoxiaoNeural' if lang == 'zh'
                     else 'en-US-JennyNeural')
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                path = f.name
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    edge_tts.Communicate(text, voice).save(path))
            finally:
                loop.close()
            wm = ctypes.windll.winmm
            wm.mciSendStringW('close tts1', None, 0, None)
            wm.mciSendStringW(
                f'open "{path}" type mpegvideo alias tts1', None, 0, None)
            wm.mciSendStringW('play tts1 wait', None, 0, None)
            wm.mciSendStringW('close tts1', None, 0, None)
        except Exception:
            pass
        finally:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass
            try:
                if popup.winfo_exists():
                    popup.after(0, lambda: btn.config(text='🔊', state='normal'))
            except Exception:
                pass
    threading.Thread(target=_do, daemon=True).start()


# ── 系统工具 ──────────────────────────────────────────────────

def get_mouse_pos() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def get_foreground_window() -> int:
    return ctypes.windll.user32.GetForegroundWindow()


class MouseSelectionTracker:
    """Remember a recent left-button drag without reading selected text."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start: tuple[int, int] | None = None
        self._bounds: tuple[int, int, int, int] | None = None
        self._window = 0
        self._finished_at = 0.0

    def clear(self):
        with self._lock:
            self._start = None
            self._bounds = None

    def on_click(self, x, y, button, pressed):
        if button != pynmouse.Button.left:
            return
        with self._lock:
            if pressed:
                self._start = (x, y)
                self._bounds = None
                return
            start = self._start
            self._start = None
            if not start or max(abs(x - start[0]), abs(y - start[1])) < 4:
                self._bounds = None
                return
            self._bounds = (min(start[0], x), min(start[1], y),
                            max(start[0], x), max(start[1], y))
            self._window = get_foreground_window()
            self._finished_at = time.monotonic()

    def on_scroll(self, x, y, dx, dy):
        self.clear()

    def get_bounds(self, now: float, window: int) -> tuple[int, int, int, int] | None:
        with self._lock:
            if (self._bounds and self._window == window
                    and 0 <= now - self._finished_at <= 60):
                return self._bounds
            return None


_mouse_selection = MouseSelectionTracker()


def resolve_selection_bounds(
    tracker: MouseSelectionTracker = _mouse_selection,
) -> tuple[int, int, int, int] | None:
    bounds = tracker.get_bounds(time.monotonic(), get_foreground_window())
    if bounds:
        _selection_diagnostic('mouse_drag_bounds', f'bounds={bounds}')
        return bounds
    return get_selection_bounds()


def _selection_diagnostic(status: str, detail: str = ''):
    path = os.environ.get('TRANSLATOR_SELECTION_DIAGNOSTICS')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as log:
            log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} '
                      f'{status} {detail}\n')
    except OSError:
        pass


def get_selection_bounds() -> tuple[int, int, int, int] | None:
    """Return the visible selected text bounds from Windows UI Automation."""
    try:
        import comtypes
        comtypes.CoInitialize()
        try:
            import uiautomation as auto
            control = auto.GetFocusedControl()
            if not control:
                _selection_diagnostic('no_focused_control')
                return None
            for depth in range(6):
                pattern = control.GetPattern(auto.PatternId.TextPattern)
                if pattern:
                    selection = pattern.GetSelection()
                    rectangles = [
                        rect
                        for selected in selection
                        for rect in selected.GetBoundingRectangles()
                        if rect.right - rect.left > 1 and rect.bottom > rect.top
                    ]
                    if rectangles:
                        bounds = (min(rect.left for rect in rectangles),
                                  min(rect.top for rect in rectangles),
                                  max(rect.right for rect in rectangles),
                                  max(rect.bottom for rect in rectangles))
                        _selection_diagnostic('bounds_found',
                                              f'control={control.ControlTypeName} '
                                              f'depth={depth} ranges={len(selection)} '
                                              f'rects={len(rectangles)} bounds={bounds}')
                        return bounds
                    _selection_diagnostic('no_valid_rectangles',
                                          f'control={control.ControlTypeName} '
                                          f'depth={depth} ranges={len(selection)}')
                parent = control.GetParentControl()
                if not parent:
                    break
                control = parent
            _selection_diagnostic('no_text_pattern_or_selection')
            return None
        finally:
            comtypes.CoUninitialize()
    except Exception as error:
        _selection_diagnostic('uia_error', type(error).__name__)
        return None


def get_work_area(x: int, y: int) -> tuple[int, int, int, int]:
    import win32api
    import win32con
    monitor = win32api.MonitorFromPoint((x, y), win32con.MONITOR_DEFAULTTONEAREST)
    return win32api.GetMonitorInfo(monitor)['Work']


def choose_popup_position(
    bounds: tuple[int, int, int, int], width: int, height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int]:
    left, top, right, bottom = bounds
    work_left, work_top, work_right, work_bottom = work_area
    min_x, min_y = work_left + 8, work_top + 8
    max_x = max(min_x, work_right - width - 8)
    max_y = max(min_y, work_bottom - height - 8)

    if right + 12 <= max_x:
        px = right + 12
    elif left - width - 12 >= min_x:
        px = left - width - 12
    else:
        px = min(max(right + 12, min_x), max_x)

    if bottom + 12 <= max_y:
        py = bottom + 12
    elif top - height - 12 >= min_y:
        py = top - height - 12
    else:
        py = min(max(bottom + 12, min_y), max_y)
    return px, py


def send_ctrl_c():
    global _simulating
    _simulating = True
    VK_CTRL, VK_C, KEYUP = 0x11, 0x43, 0x0002
    ctypes.windll.user32.keybd_event(VK_CTRL, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_C, 0, KEYUP, 0)
    ctypes.windll.user32.keybd_event(VK_CTRL, 0, KEYUP, 0)
    time.sleep(0.15)
    _simulating = False


def apply_rounded_corners(hwnd):
    try:
        v = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


# ── 后台翻译线程 ──────────────────────────────────────────────

_ui_queue: queue.Queue = queue.Queue()
_simulating          = False
_ctrl_pressed        = False   # Ctrl 当前是否按住
_ctrl_press_time     = 0.0     # Ctrl 按下的时间
_last_ctrl_click_t   = 0.0     # 上一次有效单击的释放时间
_other_key_in_ctrl   = False   # Ctrl 按住期间是否按了其他键


def translation_worker():
    mx, my = get_mouse_pos()
    selection_bounds = resolve_selection_bounds()
    try:
        old_clip = pyperclip.paste()
    except Exception:
        old_clip = ''
    pyperclip.copy('')
    send_ctrl_c()
    text = pyperclip.paste().strip()
    try:
        if old_clip:
            pyperclip.copy(old_clip)
    except Exception:
        pass
    if not text:
        return
    _ui_queue.put(('show', text, '翻译中…', mx, my, selection_bounds))
    _ui_queue.put(('update', translate(text)))


MAX_HOLD = 0.35   # 超过此时长视为长按，忽略


def on_key_press(key):
    global _ctrl_pressed, _ctrl_press_time, _other_key_in_ctrl, _simulating
    if _simulating:
        return
    if key in (pynkb.Key.ctrl_l, pynkb.Key.ctrl_r):
        if not _ctrl_pressed:          # 避免长按重复触发
            _ctrl_pressed      = True
            _ctrl_press_time   = time.time()
            _other_key_in_ctrl = False
    else:
        _mouse_selection.clear()
        if _ctrl_pressed:              # Ctrl 按住时又按了其他键（如 C、V）
            _other_key_in_ctrl = True


def on_key_release(key):
    global _ctrl_pressed, _last_ctrl_click_t, _simulating
    if _simulating:
        return
    if key not in (pynkb.Key.ctrl_l, pynkb.Key.ctrl_r):
        return
    if not _ctrl_pressed:
        return

    hold = time.time() - _ctrl_press_time
    _ctrl_pressed = False

    # 长按 或 期间按了其他键 → 不计入双击
    if hold > MAX_HOLD or _other_key_in_ctrl:
        _last_ctrl_click_t = 0.0
        return

    now = time.time()
    if now - _last_ctrl_click_t < DOUBLE_CLICK_INTERVAL:
        _last_ctrl_click_t = 0.0
        threading.Thread(target=translation_worker, daemon=True).start()
    else:
        _last_ctrl_click_t = now


# ── 悬浮窗管理 ────────────────────────────────────────────────

class PopupManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.popup = None
        self.result_text: tk.Text | None = None
        self.copy_btn: tk.Button | None = None
        self.speak_btn: tk.Button | None = None
        self._translation: str = ''       # 缓存翻译结果，供复制使用
        self._original: str = ''          # 缓存原文，供朗读使用
        self._mouse_listener = None
        self._popup_anchor = (0, 0)
        self._selection_bounds = None
        self._popup_dragged = False
        self._poll()

    def _poll(self):
        try:
            while True:
                msg = _ui_queue.get_nowait()
                if msg[0] == 'show':
                    _, text, placeholder, x, y, selection_bounds = msg
                    self._show(text, placeholder, x, y, selection_bounds)
                elif msg[0] == 'update':
                    if self.result_text and self.popup and self.popup.winfo_exists():
                        self._set_result(msg[1])
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _set_result(self, text: str):
        tw = self.result_text
        tw.config(state='normal')
        tw.delete('1.0', 'end')
        tw.insert('1.0', text)
        tw.update_idletasks()
        lines = tw.count('1.0', 'end', 'displaylines')
        if lines:
            tw.config(height=max(1, min(lines[0], 10)))
        tw.config(state='disabled')
        self._translation = text          # 缓存翻译结果，供复制使用
        if self.copy_btn and self.popup and self.popup.winfo_exists():
            self.copy_btn.config(text='⧉')
        if self.speak_btn and self.popup and self.popup.winfo_exists():
            self.speak_btn.config(state='normal', fg='#888888')
        if self.popup and self.popup.winfo_exists():
            self._position_popup()

    def _position_popup(self):
        popup = self.popup
        popup.update_idletasks()
        pw, ph = popup.winfo_reqwidth(), popup.winfo_reqheight()

        if self._popup_dragged:
            x, y = popup.winfo_rootx(), popup.winfo_rooty()
            work_left, work_top, work_right, work_bottom = get_work_area(x, y)
            px = min(max(x, work_left + 8), max(work_left + 8, work_right - pw - 8))
            py = min(max(y, work_top + 8), max(work_top + 8, work_bottom - ph - 8))
        else:
            x, y = self._popup_anchor
            if self._selection_bounds:
                work_area = get_work_area(self._selection_bounds[2],
                                          self._selection_bounds[3])
                px, py = choose_popup_position(self._selection_bounds, pw, ph,
                                               work_area)
            else:
                px, py = choose_popup_position((x, y, x, y), pw, ph,
                                               get_work_area(x, y))
        popup.geometry(f'+{px}+{py}')
        popup.update_idletasks()

    def _show(self, text: str, placeholder: str, x: int, y: int,
              selection_bounds: tuple[int, int, int, int] | None = None):
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()

        self._original = text             # 缓存原文，供朗读使用
        self._popup_anchor = (x, y)
        self._selection_bounds = selection_bounds
        self._popup_dragged = False
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        popup.attributes('-alpha', 0.94)
        popup.configure(bg=BG)

        frame = tk.Frame(popup, bg=BG, padx=16, pady=14)
        frame.pack(fill='both', expand=True)

        # 原文（灰色截断）
        orig = (text[:80] + '…') if len(text) > 80 else text
        orig_label = tk.Label(frame, text=orig, bg=BG, fg=FG_ORIG,
                              font=('Segoe UI', 9), wraplength=340,
                              justify='left', cursor='fleur')
        orig_label.pack(anchor='w')

        drag_offset = [0, 0]

        def start_drag(event):
            drag_offset[:] = [event.x_root - popup.winfo_rootx(),
                              event.y_root - popup.winfo_rooty()]

        def drag_popup(event):
            self._popup_dragged = True
            work_left, work_top, work_right, work_bottom = get_work_area(
                event.x_root, event.y_root)
            px = min(max(event.x_root - drag_offset[0], work_left + 8),
                     max(work_left + 8, work_right - popup.winfo_width() - 8))
            py = min(max(event.y_root - drag_offset[1], work_top + 8),
                     max(work_top + 8, work_bottom - popup.winfo_height() - 8))
            popup.geometry(f'+{px}+{py}')

        for widget in (frame, orig_label):
            widget.bind('<ButtonPress-1>', start_drag)
            widget.bind('<B1-Motion>', drag_popup)

        tk.Frame(frame, bg=FG_SEP, height=1).pack(fill='x', pady=(8, 8))

        # 译文（可选中复制）
        result_text = tk.Text(
            frame, bg=BG, fg='#ffffff',
            font=('Microsoft YaHei UI', 11), width=36, height=1,
            wrap='word', relief='flat', borderwidth=0, highlightthickness=0,
            selectbackground=SEL_BG, selectforeground='#ffffff',
            inactiveselectbackground=SEL_BG, undo=False, cursor='xterm',
            spacing1=1, spacing3=2,
        )
        result_text.insert('1.0', placeholder)
        result_text.config(state='disabled')
        result_text.pack(anchor='w', fill='x')
        self.result_text = result_text

        # Ctrl+C / Ctrl+A
        def enable_copy(e):
            if e.keysym.lower() == 'c':
                try:
                    sel = result_text.get('sel.first', 'sel.last')
                except tk.TclError:
                    sel = result_text.get('1.0', 'end-1c')
                popup.clipboard_clear()
                popup.clipboard_append(sel)
            elif e.keysym.lower() == 'a':
                result_text.tag_add('sel', '1.0', 'end')
            return 'break'
        result_text.bind('<Control-KeyPress>', enable_copy)

        # 底部：复制 + 朗读按钮
        btn_row = tk.Frame(frame, bg=BG)
        btn_row.pack(fill='x', pady=(6, 0))

        def do_copy():
            # 直接用缓存的翻译文本，避免读错 widget 内容
            txt = self._translation
            if txt:
                pyperclip.copy(txt)
                copy_btn.config(text='✓')
                popup.after(1500,
                            lambda: copy_btn.config(text='⧉') if popup.winfo_exists() else None)

        copy_btn = tk.Button(
            btn_row, text='⧉',
            bg=BG, fg='#888888',
            activebackground=BG, activeforeground='#bbbbbb',
            relief='flat', borderwidth=0,
            font=('Segoe UI', 12), cursor='hand2',
            padx=2, pady=0, command=do_copy,
        )
        copy_btn.pack(side='right')
        self.copy_btn = copy_btn

        def do_speak():
            txt = self._original          # 朗读原文
            if txt:
                speak_btn.config(text='…', state='disabled')
                speak_text(txt, speak_btn, popup)

        speak_btn = tk.Button(
            btn_row, text='🔊',
            bg=BG, fg='#444444',
            activebackground=BG, activeforeground='#aaaaaa',
            relief='flat', borderwidth=0,
            font=('Segoe UI', 11), cursor='hand2',
            padx=2, pady=0, state='disabled',
            command=do_speak,
        )
        speak_btn.pack(side='right', padx=(0, 6))
        self.speak_btn = speak_btn

        # 靠近选区右下角；拖动原文区域可手动调整位置。
        self.popup = popup
        self._position_popup()

        popup.update()
        try:
            apply_rounded_corners(ctypes.windll.user32.GetParent(popup.winfo_id()))
        except Exception:
            pass

        popup.after(300, lambda: self._watch_outside_click(popup))

    def _watch_outside_click(self, popup):
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        if not popup.winfo_exists():
            return

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            if not popup.winfo_exists():
                return False
            self.root.after(0, lambda: self._check_outside(popup))

        listener = pynmouse.Listener(on_click=on_click)
        listener.daemon = True
        listener.start()
        self._mouse_listener = listener

    def _check_outside(self, popup):
        if not popup.winfo_exists():
            return
        cx, cy = get_mouse_pos()
        px, py = popup.winfo_rootx(), popup.winfo_rooty()
        pw, ph = popup.winfo_width(), popup.winfo_height()
        if not (px <= cx <= px + pw and py <= cy <= py + ph):
            popup.destroy()
            if self._mouse_listener:
                try:
                    self._mouse_listener.stop()
                except Exception:
                    pass
                self._mouse_listener = None


# ── 入口 ─────────────────────────────────────────────────────

def main():
    global API_KEY

    root = tk.Tk()
    root.withdraw()

    is_first_run = not os.path.exists(CONFIG_FILE)

    API_KEY = load_api_key()
    while not API_KEY:
        key = show_key_dialog(root)
        if key is None:
            root.destroy()
            return
        save_api_key(key)
        API_KEY = key

    # 首次运行时自动开机自启（仅 exe 模式）
    if is_first_run and getattr(sys, 'frozen', False):
        set_startup(True)

    pynkb.Listener(on_press=on_key_press, on_release=on_key_release,
                   daemon=True).start()
    pynmouse.Listener(on_click=_mouse_selection.on_click,
                     on_scroll=_mouse_selection.on_scroll,
                     daemon=True).start()
    setup_tray(root)
    PopupManager(root)
    root.mainloop()


if __name__ == '__main__':
    main()
