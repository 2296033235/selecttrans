#!/usr/bin/env python3
"""
SelectTrans - 划词即译的 Windows 桌面翻译工具。

选中文字后按快捷键，在鼠标旁显示中英翻译；支持自定义组合键、
液态玻璃悬浮窗、字号与颜色调整、朗读和托盘常驻。
"""

import functools
import math
import os
import random
import re
import sys
import time
import asyncio
import tempfile
import queue
import threading
import configparser
import winreg
import tkinter as tk
from tkinter import colorchooser
import ctypes
import requests
import pyperclip
import pystray
from ctypes import wintypes
from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter,
                 ImageFont, ImageStat, ImageTk)
from pynput import keyboard as pynkb
from pynput import mouse as pynmouse

# ── 常量 ─────────────────────────────────────────────────────

APP_NAME              = "SelectTrans"
MODEL                 = "glm-4-flash-250414"
DEFAULT_BASE_URL      = "https://open.bigmodel.cn/api/paas/v4"   # OpenAI 兼容接口
DOUBLE_CLICK_INTERVAL = 0.4
STARTUP_NAME          = APP_NAME      # 开机自启在注册表里的值名

BG       = '#1e1e1e'
BG2      = '#252525'
FG_ORIG  = '#555555'
FG_TRANS = '#f0f0f0'
FG_SEP   = '#2e2e2e'
SEL_BG   = '#3a5a8a'
ACCENT   = '#4a9eff'

# 液态玻璃悬浮窗：截取悬浮窗背后的屏幕，模糊、提饱和度、边缘折射后画成玻璃，
# 再叠上文字和按钮，整张图片显示在分层窗口里。尺寸均为 100% 缩放下的像素。
GLASS_TINT_COLOR   = '#ffffff'  # 玻璃颜色
GLASS_TINT_ALPHA   = 28         # 玻璃颜色浓度，0 为完全清透
GLASS_BLUR         = 6          # 背景模糊半径
GLASS_SATURATION   = 140        # 背景饱和度（%）
GLASS_BRIGHTNESS   = 104        # 背景亮度（%）
GLASS_REFRACTION   = 10         # 边缘折射：最外沿取到玻璃外多远的画面
GLASS_REFRACT_BAND = 18         # 折射带宽度
GLASS_TEXT_MODE    = 'auto'     # auto 按背景深浅自动选 / dark / light
GLASS_TEXT         = '#141418'  # 深色文字
GLASS_TEXT_LIGHT   = '#ffffff'  # 浅色文字
GLASS_FONT_ORIG    = 12         # 原文字号（100% 缩放下的像素）
GLASS_FONT_TEXT    = 15         # 译文字号
GLASS_HALO         = 0          # 文字衬光浓度，调高后花哨背景上更易读
GLASS_SOLID        = '#f4f4f6'  # 截不到背景时的不透明底色
GLASS_SOLID_ALPHA  = 245
GLASS_SEP_ALPHA    = 40     # 分隔线浓度（颜色跟随文字）
GLASS_EDGE_ALPHA   = 28     # 外沿深色细线的浓度，让玻璃在白色背景上有轮廓
GLASS_WIDTH        = 372
GLASS_MAX_LINES    = 14
GLASS_RADIUS       = 14
GLASS_RIM_PEAK     = 230    # 白色高光描边的最大浓度
GLASS_RIM_BASE     = 0.18   # 描边在非高光处的亮度（相对 GLASS_RIM_PEAK）
GLASS_GLINT_BR     = 0.75   # 右下角高光相对左上角的强度
GLASS_RIM_WIDTH    = 1.33
GLASS_SHEEN_PEAK   = 34
GLASS_SHEEN_HEIGHT = 12     # 不超过上边距
GLASS_REFRESH_MS   = 600    # 背后画面变化时多久跟着更新一次

# ── 路径 & 配置 ───────────────────────────────────────────────

def _app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_app_dir(), 'selecttrans_config.ini')


def _read_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding='utf-8')
    return cfg


def _write_config(cfg: configparser.ConfigParser):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        cfg.write(f)


def load_api_settings() -> dict:
    """api_key, base_url and model; empty base_url / model mean the defaults."""
    cfg = _read_config()
    return {key: cfg.get('settings', key, fallback='').strip()
            for key in ('api_key', 'base_url', 'model')}


def save_api_settings(api_key: str, base_url: str = '', model: str = ''):
    cfg = _read_config()
    if not cfg.has_section('settings'):
        cfg.add_section('settings')
    cfg['settings'].update(api_key=api_key, base_url=base_url, model=model)
    _write_config(cfg)


def load_api_key() -> str:
    return load_api_settings()['api_key']


def save_api_key(key: str):
    cfg = _read_config()
    if not cfg.has_section('settings'):
        cfg.add_section('settings')
    cfg['settings']['api_key'] = key
    _write_config(cfg)


# 外观设置里能调的项：配置项名 → (常量名, 取值)。
# 取值是 'color'、可选值元组，或数值范围 (最小, 最大)。
GLASS_STYLE_FIELDS = {
    'tint_color': ('GLASS_TINT_COLOR', 'color'),
    'tint_alpha': ('GLASS_TINT_ALPHA', (0, 255)),
    'blur':       ('GLASS_BLUR', (0, 30)),
    'saturation': ('GLASS_SATURATION', (0, 250)),
    'brightness': ('GLASS_BRIGHTNESS', (50, 150)),
    'refraction': ('GLASS_REFRACTION', (0, 30)),
    'radius':     ('GLASS_RADIUS', (0, 30)),
    'rim':        ('GLASS_RIM_PEAK', (0, 255)),
    'sheen':      ('GLASS_SHEEN_PEAK', (0, 255)),
    'edge':       ('GLASS_EDGE_ALPHA', (0, 255)),
    'separator':  ('GLASS_SEP_ALPHA', (0, 255)),
    'text_mode':  ('GLASS_TEXT_MODE', ('auto', 'dark', 'light')),
    'text_dark':  ('GLASS_TEXT', 'color'),
    'text_light': ('GLASS_TEXT_LIGHT', 'color'),
    'font_orig':  ('GLASS_FONT_ORIG', (9, 28)),
    'font_text':  ('GLASS_FONT_TEXT', (10, 32)),
    'halo':       ('GLASS_HALO', (0, 255)),
}
_HEX_COLOR = re.compile(r'#[0-9a-fA-F]{6}')


def get_glass_style() -> dict:
    g = globals()
    return {key: g[name] for key, (name, _) in GLASS_STYLE_FIELDS.items()}


def set_glass_style(style: dict):
    """应用外观设置。缺少或无效的项保持原值，数值限制在各自范围内。"""
    g = globals()
    for key, (name, kind) in GLASS_STYLE_FIELDS.items():
        if key not in style:
            continue
        value = str(style[key]).strip()
        if kind == 'color':
            if _HEX_COLOR.fullmatch(value):
                g[name] = value.lower()
        elif isinstance(kind, tuple) and isinstance(kind[0], str):
            if value in kind:
                g[name] = value
        else:
            try:
                g[name] = min(kind[1], max(kind[0], int(float(value))))
            except ValueError:
                pass


GLASS_DEFAULT_STYLE = get_glass_style()
GLASS_PRESETS = {
    '清透': GLASS_DEFAULT_STYLE,
    '磨砂': {**GLASS_DEFAULT_STYLE, 'blur': 16, 'tint_alpha': 70, 'saturation': 120,
             'halo': 150},
    '深色': {**GLASS_DEFAULT_STYLE, 'tint_color': '#101014', 'tint_alpha': 110,
             'blur': 12, 'rim': 120, 'sheen': 16, 'edge': 60, 'text_mode': 'light',
             'halo': 150},
}


def load_glass_style():
    cfg = _read_config()
    if cfg.has_section('glass'):
        set_glass_style(dict(cfg['glass']))


def save_glass_style(style: dict):
    cfg = _read_config()
    cfg['glass'] = {key: str(value) for key, value in style.items()}
    _write_config(cfg)


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
    """托盘图标：圆角方块上的三行文本，中间一行是高亮的选中内容，右下角一支向下箭头。"""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3, 3, 60, 60], radius=15, fill='#2563eb')
    d.rounded_rectangle([14, 15, 50, 20], radius=2, fill='#e6f1fb')
    d.rounded_rectangle([14, 26, 43, 31], radius=2, fill='#fcd34d')   # 选中的一行
    d.rounded_rectangle([14, 37, 35, 42], radius=2, fill='#e6f1fb')
    d.rectangle([46, 42, 50, 51], fill='#ffffff')                     # 箭头杆
    d.polygon([(40, 49), (56, 49), (48, 58)], fill='#ffffff')         # 箭头头部
    return img


def setup_tray(root: tk.Tk) -> pystray.Icon:
    def on_settings(icon, item):
        def _do():
            settings = show_settings_dialog(root, current_api_settings())
            if settings:
                save_api_settings(**settings)
                apply_api_settings(settings)
                icon.update_menu()
        root.after(0, _do)

    def on_appearance(icon, item):
        def _do():
            open_style_editor(root)
        root.after(0, _do)

    def on_hotkey(icon, item):
        def _do():
            open_hotkey_dialog(root)
        root.after(0, _do)

    def on_toggle_startup(icon, item):
        set_startup(not is_startup_enabled())

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.quit)

    menu = pystray.Menu(
        pystray.MenuItem(APP_NAME, None, enabled=False),
        pystray.MenuItem(lambda item: f'模型：{API_MODEL or MODEL}', None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('接口设置（API Key / 模型）', on_settings),
        pystray.MenuItem('外观设置（字体 / 颜色）', on_appearance),
        pystray.MenuItem('快捷键设置', on_hotkey),
        pystray.MenuItem('开机自启', on_toggle_startup,
                         checked=lambda item: is_startup_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('退出', on_quit),
    )
    icon = pystray.Icon(STARTUP_NAME, _make_icon(),
                        f'{APP_NAME}  ({format_hotkey(_hotkey.spec)} 划词翻译)', menu)
    icon.run_detached()
    return icon


# ── 首次设置 / 修改 Key 弹窗 ──────────────────────────────────

def validate_api_settings(api_key: str, base_url: str, model: str) -> tuple[dict | None, str]:
    """Normalize the dialog input; returns (settings, '') or (None, error message).

    Values equal to the defaults are stored empty so a later change of the
    default endpoint or model reaches users who never customized them.
    """
    api_key, base_url, model = api_key.strip(), base_url.strip().rstrip('/'), model.strip()
    if not api_key:
        return None, "API Key 不能为空"
    if base_url and not re.match(r'https?://[^\s/]+', base_url):
        return None, "接口地址需以 http:// 或 https:// 开头"
    if base_url == DEFAULT_BASE_URL:
        base_url = ''
    if model == MODEL:
        model = ''
    # 智谱的 Key 形如 id.secret；其他服务商格式各不相同，不做检查。
    if not base_url and ('.' not in api_key or len(api_key) < 10):
        return None, "Key 格式不正确，请检查（智谱 Key 形如 xxx.xxx）"
    return {'api_key': api_key, 'base_url': base_url, 'model': model}, ''


def resource_path(*parts: str) -> str:
    """Files bundled next to the script, or inside the PyInstaller archive."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


CRAYON_FONT_FILE = resource_path('assets', 'fonts', 'ZCOOLKuaiLe-Regular.ttf')
CRAYON_PAPER = '#fffaf0'
CRAYON_INK = '#34344e'
CRAYON_MUTED = '#8a8296'
CRAYON_RED = '#e8503a'
CRAYON_ORANGE = '#f39a1e'
CRAYON_YELLOW = '#fcd535'
CRAYON_GREEN = '#58b84a'
CRAYON_DARK_GREEN = '#2f8f3a'
CRAYON_BLUE = '#3a7bd5'
CRAYON_SKY = '#8fd0f5'
CRAYON_PINK = '#f48fb1'
CRAYON_PURPLE = '#8e6bd8'
CRAYON_TITLE_COLORS = (CRAYON_RED, CRAYON_ORANGE, CRAYON_GREEN, CRAYON_BLUE,
                       CRAYON_PURPLE, CRAYON_PINK)


@functools.lru_cache(maxsize=1)
def crayon_font_family() -> str:
    """Register the bundled childlike font for this process; Tk and GDI can then use it."""
    try:
        if (os.path.exists(CRAYON_FONT_FILE)
                and ctypes.windll.gdi32.AddFontResourceExW(CRAYON_FONT_FILE, 0x10, 0)):
            return 'ZCOOL KuaiLe'                     # 0x10 = FR_PRIVATE
    except Exception:
        pass
    return 'Microsoft YaHei UI'


class CrayonDrawing:
    """Childlike crayon drawing on paper: waxy, wobbly strokes and scribbled fills."""

    def __init__(self, width: int, height: int, scale: float = 1.0, seed: int = 7):
        self.size = (width, height)
        self.scale = scale
        self.rng = random.Random(seed)
        speck = Image.effect_noise(self.size, 10)
        self.image = Image.merge('RGB', [
            ImageChops.add(Image.new('L', self.size, c), speck, offset=-128)
            for c in _hex_rgb(CRAYON_PAPER)])
        # 蜡笔在纸上留下的颗粒：随机把一部分笔触“擦掉”。
        self.grain = Image.effect_noise(self.size, 70).point(
            [0 if v < 55 else min(255, (v - 55) * 4) for v in range(256)])

    def px(self, value: float) -> float:
        return value * self.scale

    def mask(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        mask = Image.new('L', self.size, 0)
        return mask, ImageDraw.Draw(mask)

    def lay(self, mask: Image.Image, color: str, clip: Image.Image | None = None,
            grain: bool = True):
        if clip is not None:
            mask = ImageChops.multiply(mask, clip)
        if grain:
            mask = ImageChops.multiply(mask, self.grain)
        self.image.paste(color, (0, 0, *self.size), mask)

    def _wobble(self, points: list[tuple[float, float]], amount: float
                ) -> list[tuple[float, float]]:
        rng = self.rng
        f1, f2 = rng.uniform(0.15, 0.3), rng.uniform(0.5, 0.9)
        p1, p2, p3 = (rng.uniform(0, math.tau) for _ in range(3))
        return [(x + amount * (math.sin(i * f1 + p1) + 0.4 * math.sin(i * f2 + p2)),
                 y + amount * (math.sin(i * f1 + p3) + 0.4 * math.sin(i * f2 + p1)))
                for i, (x, y) in enumerate(points)]

    def stroke(self, d: ImageDraw.ImageDraw, points: list[tuple[float, float]],
               width: float, passes: int = 2, wobble: float = 1.2, alpha: int = 235):
        for _ in range(passes):
            pts = self._wobble(points, self.px(wobble))
            d.line(pts, fill=alpha, width=max(1, round(self.px(width) * self.rng.uniform(0.8, 1.1))),
                   joint='curve')

    @staticmethod
    def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
        out = [points[0]]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            n = max(1, round(math.hypot(x1 - x0, y1 - y0) / step))
            out.extend((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1))
        return out

    def rounded_path(self, box: tuple, radius: float, overshoot: float = 0.06
                     ) -> list[tuple[float, float]]:
        x0, y0, x1, y1 = box
        r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
        corners = [(x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                   (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)]
        points = [(x0 + r, y0)]
        for cx, cy, start in corners:
            points.extend((cx + r * math.cos(math.radians(start + a)),
                           cy + r * math.sin(math.radians(start + a))) for a in range(0, 91, 15))
        points.append((x0 + r, y0))
        points = self._resample(points, self.px(8))
        # 小朋友画框常常收不住笔，终点多画出去一点。
        return points + points[1:max(2, round(len(points) * overshoot))]

    def box(self, box: tuple, color: str, width: float = 2.4, radius: float = 10,
            fill: str | None = None, scribble: str | None = None):
        box = tuple(self.px(v) for v in box)
        shape, sd = self.mask()
        sd.rounded_rectangle(box, radius=self.px(radius), fill=255)
        if fill:
            self.image.paste(fill, (0, 0, *self.size), shape)
        if scribble:
            self.scribble(box, scribble, shape)
        mask, d = self.mask()
        self.stroke(d, self.rounded_path(box, self.px(radius)), width)
        self.lay(mask, color)

    def scribble(self, box: tuple, color: str, clip: Image.Image, spacing: float = 5,
                 width: float = 5):
        """Back-and-forth coloring strokes, the way children fill a shape."""
        x0, y0, x1, y1 = box
        step, slant = self.px(spacing), (y1 - y0) * 0.55
        points, x, top = [], x0 - slant, True
        while x < x1 + slant:
            jitter = self.rng.uniform(-step * 0.3, step * 0.3)
            points.append((x + slant + jitter, y0 - self.px(3)) if top
                          else (x + jitter, y1 + self.px(3)))
            x += step
            top = not top
        mask, d = self.mask()
        self.stroke(d, points, width, passes=1, wobble=0.6, alpha=200)
        self.lay(mask, color, clip)

    def checkbox(self, x: float, y: float, size: float = 16):
        self.box((x, y, x + size, y + size), CRAYON_INK, width=2, radius=3, fill='#ffffff')

    def triangle(self, x: float, y: float, size: float, down: bool, color: str):
        s = size
        pts = ([(x, y), (x + s, y), (x + s / 2, y + s * 0.8)] if down
               else [(x, y), (x + s * 0.8, y + s / 2), (x, y + s)])
        pts = [(self.px(a), self.px(b)) for a, b in pts]
        shape, sd = self.mask()
        sd.polygon(pts, fill=255)
        self.lay(shape, color)

    def sun(self, cx: float, cy: float, r: float):
        cx, cy, r = self.px(cx), self.px(cy), self.px(r)
        rays, d = self.mask()
        for i in range(10):
            a = i * math.tau / 10 + self.rng.uniform(-0.08, 0.08)
            inner, outer = r * 1.3, r * self.rng.uniform(1.65, 1.85)
            self.stroke(d, self._resample([(cx + inner * math.cos(a), cy + inner * math.sin(a)),
                                           (cx + outer * math.cos(a), cy + outer * math.sin(a))],
                                          self.px(6)), 3, wobble=0.5)
        self.lay(rays, CRAYON_ORANGE)
        shape, sd = self.mask()
        sd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        self.scribble((cx - r, cy - r, cx + r, cy + r), CRAYON_YELLOW, shape, spacing=4, width=5)
        ring, d = self.mask()
        self.stroke(d, [(cx + r * math.cos(t / 20 * math.tau), cy + r * math.sin(t / 20 * math.tau))
                        for t in range(23)], 2.6)
        self.lay(ring, CRAYON_ORANGE)
        face, d = self.mask()
        for ex in (-0.35, 0.35):
            d.ellipse((cx + ex * r - self.px(2.4), cy - 0.25 * r - self.px(2.4),
                       cx + ex * r + self.px(2.4), cy - 0.25 * r + self.px(2.4)), fill=255)
        self.stroke(d, [(cx + 0.45 * r * math.cos(math.radians(a)),
                         cy + 0.05 * r + 0.4 * r * math.sin(math.radians(a)))
                        for a in range(20, 161, 20)], 2.2, passes=1, wobble=0.3)
        self.lay(face, CRAYON_INK)
        cheeks, d = self.mask()
        for ex in (-0.6, 0.6):
            d.ellipse((cx + ex * r - self.px(4), cy + 0.15 * r - self.px(3),
                       cx + ex * r + self.px(4), cy + 0.15 * r + self.px(3)), fill=170)
        self.lay(cheeks, CRAYON_PINK)

    def cloud(self, x: float, y: float, w: float):
        # 几团重叠的圆：(圆心 x, 圆心 y, 半径)，都按云的宽度 w 计算。
        bumps = [(0.2, 0.32, 0.17), (0.42, 0.22, 0.22), (0.66, 0.27, 0.19), (0.84, 0.36, 0.13)]
        shape, sd = self.mask()
        for bx, by, br in bumps:
            sd.ellipse((self.px(x + (bx - br) * w), self.px(y + (by - br) * w),
                        self.px(x + (bx + br) * w), self.px(y + (by + br) * w)), fill=255)
        bbox = shape.getbbox() or (0, 0, 1, 1)
        self.scribble(bbox, '#e3f3fd', shape, spacing=4, width=5)
        edge = shape.filter(ImageFilter.FIND_EDGES).point([0 if v < 60 else 255 for v in range(256)])
        edge = edge.filter(ImageFilter.MaxFilter(3))
        self.lay(edge, CRAYON_SKY)

    def flower(self, x: float, y: float, ground: float, petal: str, size: float = 9):
        stem, d = self.mask()
        self.stroke(d, self._resample([(self.px(x), self.px(ground)),
                                       (self.px(x + 2), self.px((ground + y) / 2)),
                                       (self.px(x), self.px(y))], self.px(6)), 2.4, wobble=0.6)
        self.lay(stem, CRAYON_DARK_GREEN)
        petals, d = self.mask()
        for i in range(5):
            a = i * math.tau / 5 - math.pi / 2
            px_, py = x + size * 0.8 * math.cos(a), y + size * 0.8 * math.sin(a)
            r = size * 0.55
            d.ellipse((self.px(px_ - r), self.px(py - r), self.px(px_ + r), self.px(py + r)), fill=235)
        self.lay(petals, petal)
        core, d = self.mask()
        r = size * 0.42
        d.ellipse((self.px(x - r), self.px(y - r), self.px(x + r), self.px(y + r)), fill=255)
        self.lay(core, CRAYON_YELLOW)

    def grass(self, top: float, bottom: float, width: float):
        shape, sd = self.mask()
        sd.rectangle((0, self.px(top + 8), self.px(width), self.px(bottom)), fill=255)
        self.scribble((0, self.px(top + 8), self.px(width), self.px(bottom)), '#b5e3a1',
                      shape, spacing=5, width=6)
        blades, d = self.mask()
        x = 2.0
        while x < width:
            h = self.rng.uniform(9, 17)
            lean = self.rng.uniform(-3, 3)
            self.stroke(d, [(self.px(x), self.px(top + 12)), (self.px(x + lean), self.px(top + 12 - h))],
                        2.0, passes=1, wobble=0.3)
            x += self.rng.uniform(4, 8)
        self.lay(blades, CRAYON_GREEN)


def show_settings_dialog(root: tk.Tk, current: dict | None = None) -> dict | None:
    """API Key plus optional base URL and model; returns the new settings or None.

    The window is a crayon drawing: Pillow paints the paper, frames and
    doodles, and the input boxes sit on top of the painted frames.
    """
    current = current or {}
    family = crayon_font_family()
    dialog = tk.Toplevel(root)
    dialog.title(f"{APP_NAME} - 设置")
    dialog.resizable(False, False)
    dialog.attributes('-topmost', True)
    dialog.configure(bg=CRAYON_PAPER)
    dialog.grab_set()
    scale = ui_scale(dialog)

    def px(value: float) -> int:
        return round(value * scale)

    W = 470
    canvas = tk.Canvas(dialog, width=px(W), height=px(400), bg=CRAYON_PAPER,
                       highlightthickness=0, borderwidth=0)
    canvas.pack()
    entry_style = dict(bg='#ffffff', fg=CRAYON_INK, insertbackground=CRAYON_INK,
                       relief='flat', borderwidth=0, highlightthickness=0,
                       font=('Consolas', 11))
    key_var = tk.StringVar(value=current.get('api_key', ''))
    base_var = tk.StringVar(value=current.get('base_url') or DEFAULT_BASE_URL)
    model_var = tk.StringVar(value=current.get('model') or MODEL)
    key_entry = tk.Entry(canvas, textvariable=key_var, show='*', **entry_style)
    base_entry = tk.Entry(canvas, textvariable=base_var, **entry_style)
    model_entry = tk.Entry(canvas, textvariable=model_var, **entry_style)

    state = {'expanded': bool(current.get('base_url') or current.get('model')),
             'show_key': False, 'error': '', 'test': '', 'test_color': CRAYON_MUTED,
             'testing': False}
    hotspots: dict[str, tuple] = {}
    result = {'settings': None}

    def font(size: int, bold: bool = False):
        return (family, size, 'bold') if bold else (family, size)

    def render():
        canvas.delete('all')
        hotspots.clear()
        expanded = state['expanded']
        y_more = 236
        y_error = y_more + (284 if expanded else 0)
        y_buttons = y_error + 30
        height = y_buttons + 112
        canvas.config(height=px(height))

        art = CrayonDrawing(px(W), px(height), scale)
        art.cloud(250, 18, 92)
        art.sun(W - 58, 54, 24)
        art.box((24, 150, W - 24, 192), CRAYON_BLUE, fill='#ffffff')
        art.checkbox(28, 203)
        art.triangle(30, y_more + 4, 13, expanded, CRAYON_ORANGE)
        if expanded:
            art.box((24, y_more + 58, W - 24, y_more + 100), CRAYON_PURPLE, fill='#ffffff')
            art.box((24, y_more + 136, W - 24, y_more + 178), CRAYON_GREEN, fill='#ffffff')
            art.box((24, y_more + 238, 132, y_more + 274), CRAYON_DARK_GREEN,
                    scribble='#c8ecb5', radius=12)
            art.box((144, y_more + 238, 252, y_more + 274), CRAYON_ORANGE,
                    scribble='#fde6a6', radius=12)
        art.box((W - 252, y_buttons, W - 140, y_buttons + 42), CRAYON_RED,
                scribble='#f9b8a8', radius=14, width=2.8)
        art.box((W - 128, y_buttons, W - 24, y_buttons + 42), CRAYON_MUTED,
                scribble='#e6e1ee', radius=14)
        art.grass(height - 46, height, W)
        for fx, color in ((34, CRAYON_RED), (70, CRAYON_PINK), (112, CRAYON_PURPLE),
                          (150, CRAYON_ORANGE)):
            art.flower(fx, height - 58 + art.rng.uniform(-4, 4), height - 30, color)
        canvas.image = ImageTk.PhotoImage(art.image, master=dialog)
        canvas.create_image(0, 0, image=canvas.image, anchor='nw')

        x = px(26)
        for i, ch in enumerate(APP_NAME):
            item = canvas.create_text(x, px(22), text=ch, anchor='nw', font=font(22),
                                      fill=CRAYON_TITLE_COLORS[i % len(CRAYON_TITLE_COLORS)])
            x = canvas.bbox(item)[2] + px(1)
        canvas.create_text(px(28), px(72), anchor='nw', font=font(11), fill=CRAYON_INK,
                           text="请输入您的 API Key")
        canvas.create_text(px(28), px(96), anchor='nw', font=font(9), fill=CRAYON_MUTED,
                           text="默认使用智谱 GLM，免费申请：bigmodel.cn → API Keys")
        canvas.create_text(px(28), px(124), anchor='nw', font=font(11), fill=CRAYON_BLUE,
                           text="API Key")
        canvas.create_window(px(38), px(171), window=key_entry, anchor='w',
                             width=px(W - 76), height=px(26))
        if state['show_key']:
            canvas.create_line(px(31), px(211), px(36), px(217), px(46), px(201),
                               fill=CRAYON_RED, width=px(3), capstyle='round',
                               joinstyle='round', smooth=True)
        canvas.create_text(px(52), px(211), anchor='w', font=font(10), fill=CRAYON_INK,
                           text="显示密钥")
        hotspots['show_key'] = (26, 199, 120, 223)

        canvas.create_text(px(50), px(y_more + 10), anchor='w', font=font(11),
                           fill=CRAYON_ORANGE, text="更多设置（接口地址、模型）")
        hotspots['toggle'] = (26, y_more - 4, 270, y_more + 24)
        if expanded:
            canvas.create_text(px(28), px(y_more + 34), anchor='nw', font=font(11),
                               fill=CRAYON_PURPLE, text="接口地址（Base URL）")
            canvas.create_window(px(38), px(y_more + 79), window=base_entry, anchor='w',
                                 width=px(W - 76), height=px(26))
            canvas.create_text(px(28), px(y_more + 112), anchor='nw', font=font(11),
                               fill=CRAYON_DARK_GREEN, text="模型")
            canvas.create_window(px(38), px(y_more + 157), window=model_entry, anchor='w',
                                 width=px(W - 76), height=px(26))
            canvas.create_text(px(28), px(y_more + 188), anchor='nw', font=font(9),
                               fill=CRAYON_MUTED, justify='left',
                               text="支持 OpenAI 兼容接口，例如 https://api.deepseek.com、\n"
                                    "https://api.openai.com/v1，会自动补上 /chat/completions。")
            canvas.create_text(px(78), px(y_more + 256), font=font(11), fill=CRAYON_INK,
                               text="测试中…" if state['testing'] else "测试连接", tags='test')
            canvas.create_text(px(198), px(y_more + 256), font=font(11), fill=CRAYON_INK,
                               text="恢复默认")
            hotspots['test'] = (24, y_more + 238, 132, y_more + 274)
            hotspots['reset'] = (144, y_more + 238, 252, y_more + 274)
            canvas.create_text(px(264), px(y_more + 256), anchor='w', font=font(9),
                               fill=state['test_color'], text=state['test'],
                               width=px(W - 290))
        canvas.create_text(px(28), px(y_error + 12), anchor='w', font=font(10),
                           fill=CRAYON_RED, text=state['error'], width=px(W - 56))
        canvas.create_text(px(W - 196), px(y_buttons + 21), font=font(13), fill=CRAYON_INK,
                           text="确认")
        canvas.create_text(px(W - 76), px(y_buttons + 21), font=font(13), fill=CRAYON_INK,
                           text="取消")
        hotspots['confirm'] = (W - 252, y_buttons, W - 140, y_buttons + 42)
        hotspots['cancel'] = (W - 128, y_buttons, W - 24, y_buttons + 42)
        return height

    def hit(event) -> str | None:
        x, y = event.x / scale, event.y / scale
        for name, (x0, y0, x1, y1) in hotspots.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def on_motion(event):
        canvas.config(cursor='hand2' if hit(event) else '')

    def on_click(event):
        actions = {'show_key': toggle_key, 'toggle': toggle_more, 'test': run_test,
                   'reset': reset_endpoint, 'confirm': on_confirm, 'cancel': dialog.destroy}
        name = hit(event)
        if name:
            actions[name]()

    def toggle_key():
        state['show_key'] = not state['show_key']
        key_entry.config(show='' if state['show_key'] else '*')
        render()

    def toggle_more():
        state['expanded'] = not state['expanded']
        render()
        keep_on_screen()

    def reset_endpoint():
        base_var.set(DEFAULT_BASE_URL)
        model_var.set(MODEL)
        state['test'] = ''
        render()

    def run_test():
        if state['testing']:
            return
        settings, error = validate_api_settings(key_var.get(), base_var.get(), model_var.get())
        if not settings:
            state.update(test=error, test_color=CRAYON_RED)
            render()
            return
        state.update(testing=True, test='', test_color=CRAYON_MUTED)
        render()
        outcome = {}

        def work():
            try:
                outcome['text'] = request_translation('Hello', settings['api_key'],
                                                      settings['base_url'], settings['model'])
            except Exception as e:
                outcome['error'] = str(e)

        def wait():
            if not dialog.winfo_exists():
                return
            if not outcome:
                dialog.after(100, wait)
                return
            state['testing'] = False
            if 'error' in outcome:
                state.update(test=f"连接失败：{outcome['error'][:160]}", test_color=CRAYON_RED)
            else:
                state.update(test=f"连接成功：Hello → {outcome['text'][:40]}",
                             test_color=CRAYON_DARK_GREEN)
            render()

        threading.Thread(target=work, daemon=True).start()
        dialog.after(100, wait)

    def on_confirm():
        settings, error = validate_api_settings(key_var.get(), base_var.get(), model_var.get())
        if not settings:
            state['error'] = error
            render()
            return
        result['settings'] = settings
        dialog.destroy()

    def keep_on_screen():
        dialog.update_idletasks()
        left, top, right, bottom = get_work_area(dialog.winfo_rootx(), dialog.winfo_rooty())
        y = min(dialog.winfo_y(), bottom - dialog.winfo_height() - px(40))
        dialog.geometry(f'+{dialog.winfo_x()}+{max(top, y)}')

    canvas.bind('<Motion>', on_motion)
    canvas.bind('<Button-1>', on_click)
    dialog.bind('<Return>', lambda e: on_confirm())
    dialog.bind('<Escape>', lambda e: dialog.destroy())
    # 按钮都是画出来的，没有控件可点；测试和辅助功能通过这里直接触发。
    dialog.actions = {'toggle_more': toggle_more, 'confirm': on_confirm,
                      'cancel': dialog.destroy, 'test': run_test,
                      'reset': reset_endpoint, 'show_key': toggle_key}

    render()
    dialog.update_idletasks()
    w, h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
    dialog.geometry(f'+{(sw - w) // 2}+{max(0, (sh - h) // 2 - px(60))}')
    key_entry.focus_set()
    dialog.wait_window()
    return result['settings']


# ── 翻译 ─────────────────────────────────────────────────────

API_KEY = ''
API_BASE_URL = ''     # 空字符串表示 DEFAULT_BASE_URL
API_MODEL = ''        # 空字符串表示 MODEL


def apply_api_settings(settings: dict):
    global API_KEY, API_BASE_URL, API_MODEL
    API_KEY = settings.get('api_key', '')
    API_BASE_URL = settings.get('base_url', '')
    API_MODEL = settings.get('model', '')


def current_api_settings() -> dict:
    return {'api_key': API_KEY, 'base_url': API_BASE_URL, 'model': API_MODEL}


def chat_completions_url(base_url: str = '') -> str:
    """Accept either a base such as https://api.openai.com/v1 or the full endpoint."""
    base = (base_url.strip() or DEFAULT_BASE_URL).rstrip('/')
    return base if base.endswith('/chat/completions') else base + '/chat/completions'


def detect_lang(text: str) -> str:
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            return 'zh'
    return 'en'


def request_translation(text: str, api_key: str, base_url: str = '',
                        model: str = '') -> str:
    prompt = (f"请将以下中文翻译成英文，只输出翻译结果：\n{text}"
              if detect_lang(text) == 'zh' else
              f"请将以下英文翻译成中文，只输出翻译结果：\n{text}")
    r = requests.post(
        chat_completions_url(base_url),
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model.strip() or MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 512, "temperature": 0.3},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def translate(text: str) -> str:
    try:
        return request_translation(text, API_KEY, API_BASE_URL, API_MODEL)
    except Exception as e:
        return f"[Error: {e}]"


def speak_text(text: str, on_done, popup: 'tk.Toplevel'):
    """TTS via edge-tts → temp MP3 → Windows MCI playback; on_done runs on the Tk thread."""
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
                    popup.after(0, on_done)
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


def enable_dpi_awareness():
    """Work in physical pixels, like UI Automation and the mouse hooks.

    Importing uiautomation switches the process to per-monitor DPI awareness
    as a side effect. Doing it before Tk starts keeps the selection bounds,
    cursor position and window geometry in the same coordinate space.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def ui_scale(root: tk.Misc) -> float:
    return root.winfo_fpixels('1i') / 96


def apply_rounded_corners(hwnd):
    try:
        v = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def glass_supported() -> bool:
    """Glass follows the system "transparency effects" setting."""
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        ) as key:
            return winreg.QueryValueEx(key, 'EnableTransparency')[0] != 0
    except OSError:
        return True


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


class _BlendFunction(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte),
                ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


def make_layered(hwnd):
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    style = user32.GetWindowLongPtrW(hwnd, -20)                   # GWL_EXSTYLE
    user32.SetWindowLongPtrW(hwnd, -20, style | 0x80000)          # WS_EX_LAYERED


def _gdi_prototypes():
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                             wintypes.DWORD]
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    return user32, gdi32


def capture_screen(x: int, y: int, width: int, height: int,
                   exclude_hwnd=None) -> Image.Image | None:
    """Copy a screen area as RGB, leaving exclude_hwnd out of the picture.

    The window stays visible on the monitor while it is excluded, so the
    popup can see what is behind itself without flickering. Returns None when
    the window cannot be excluded (Windows 10 before 2004).
    """
    user32, gdi32 = _gdi_prototypes()
    if exclude_hwnd and not user32.SetWindowDisplayAffinity(exclude_hwnd, 0x11):
        return None                                   # WDA_EXCLUDEFROMCAPTURE
    screen = memory = bitmap = None
    try:
        if exclude_hwnd:
            ctypes.windll.dwmapi.DwmFlush()           # 等系统按新的设置合成一帧
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height,
                                   1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), 0,
                                        ctypes.byref(bits), None, 0)
        if not bitmap:
            return None
        previous = gdi32.SelectObject(memory, bitmap)
        ok = gdi32.BitBlt(memory, 0, 0, width, height, screen, x, y, 0x00CC0020)  # SRCCOPY
        gdi32.SelectObject(memory, previous)
        if not ok:
            return None
        data = ctypes.string_at(bits, width * height * 4)
        return Image.frombuffer('RGB', (width, height), data, 'raw', 'BGRX', 0, 1)
    finally:
        if exclude_hwnd:
            user32.SetWindowDisplayAffinity(exclude_hwnd, 0)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory:
            gdi32.DeleteDC(memory)
        if screen:
            user32.ReleaseDC(None, screen)


def premultiplied_bgra(image: Image.Image) -> bytes:
    r, g, b, a = image.split()
    return Image.merge(
        'RGBA', [ImageChops.multiply(c, a) for c in (b, g, r)] + [a]).tobytes()


def update_layered_window(hwnd, image: Image.Image, x: int, y: int) -> bool:
    """Show an RGBA image as the whole content of a layered window."""
    user32, gdi32 = _gdi_prototypes()
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.HDC, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD]

    width, height = image.size
    pixels = premultiplied_bgra(image)
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height,
                               1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), 0,
                                    ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            return False
        ctypes.memmove(bits, pixels, len(pixels))
        previous = gdi32.SelectObject(memory, bitmap)
        blend = _BlendFunction(0, 0, 255, 1)                       # AC_SRC_OVER, AC_SRC_ALPHA
        ok = user32.UpdateLayeredWindow(
            hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
            ctypes.byref(wintypes.SIZE(width, height)), memory,
            ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend),
            2)                                                     # ULW_ALPHA
        gdi32.SelectObject(memory, previous)
        return bool(ok)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)


def _glass_glint(t: float) -> float:
    """Rim brightness along the 135° diagonal: glints at top-left and bottom-right."""
    top_left = math.exp(-((t - 0.18) / 0.14) ** 2)
    bottom_right = GLASS_GLINT_BR * math.exp(-((t - 0.85) / 0.12) ** 2)
    return GLASS_RIM_BASE + (1 - GLASS_RIM_BASE) * max(top_left, bottom_right)


def render_glass_highlight(width: int, height: int, ui_scale: float = 1.0,
                           radius: int = GLASS_RADIUS) -> Image.Image:
    """Edge highlight for the glass popup; brightness is added onto the glass."""
    width, height = max(width, 2), max(height, 2)
    ss = 3                                   # 超采样倍数，用于抗锯齿
    big = (width * ss, height * ss)
    radius = round(radius * ui_scale * ss)

    # 描边内缩约 1.3px，给最外沿的深色细线留位置。
    inset = max(1, round(4 * ui_scale))
    line = max(1, round(GLASS_RIM_WIDTH * ss * ui_scale))
    rim_mask = Image.new('L', big, 0)
    ImageDraw.Draw(rim_mask).rounded_rectangle(
        (inset, inset, big[0] - 1 - inset, big[1] - 1 - inset),
        radius=max(0, radius - inset), outline=255, width=line)
    rim_mask = rim_mask.resize((width, height), Image.LANCZOS)

    fill_inset = inset + line
    fill_mask = Image.new('L', big, 0)
    ImageDraw.Draw(fill_mask).rounded_rectangle(
        (fill_inset, fill_inset, big[0] - 1 - fill_inset, big[1] - 1 - fill_inset),
        radius=max(0, radius - fill_inset), fill=255)
    fill_mask = fill_mask.resize((width, height), Image.LANCZOS)

    vertical = Image.linear_gradient('L').resize((width, height))
    horizontal = (Image.linear_gradient('L').transpose(Image.Transpose.TRANSPOSE)
                  .resize((width, height)))
    diagonal = ImageChops.add(horizontal, vertical, scale=2.0)

    rim = ImageChops.multiply(
        diagonal.point([round(GLASS_RIM_PEAK * _glass_glint(i / 255))
                        for i in range(256)]),
        rim_mask)

    # 光泽只铺在顶部留白里，不压在文字上。
    sheen_height = max(1, min(round(GLASS_SHEEN_HEIGHT * ui_scale), height))
    sheen_strip = Image.linear_gradient('L').resize((width, sheen_height)).point(
        [round(GLASS_SHEEN_PEAK * (1 - i / 255) ** 2) for i in range(256)])
    sheen = Image.new('L', (width, height), 0)
    sheen.paste(sheen_strip, (0, 0))
    sheen = ImageChops.multiply(sheen, fill_mask)
    return ImageChops.add(rim, sheen).convert('RGB')


@functools.lru_cache(maxsize=8)
def _glass_font(size: int) -> ImageFont.ImageFont:
    for name, index in (('msyh.ttc', 1), ('msyh.ttc', 0), ('segoeui.ttf', 0)):
        try:
            return ImageFont.truetype(name, size, index=index)   # 1 = Microsoft YaHei UI
        except OSError:
            continue
    return ImageFont.load_default(size)


# 英文单词（含紧随的标点和空格）整体换行，中日韩字符可在任意字符间换行。
_WRAP_TOKEN = re.compile(
    r'[^\s\u2e80-\u9fff\uac00-\ud7af\u3000-\u303f\uff00-\uffef]+\s*|\s+|.')


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: float) -> list[str]:
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for token in _WRAP_TOKEN.findall(paragraph):
            if font.getlength(line + token) <= max_width:
                line += token
                continue
            if line.strip():
                lines.append(line.rstrip())
            line = token.lstrip()
            while line and font.getlength(line) > max_width:   # 超长单词按字符拆开
                cut = len(line) - 1
                while cut > 1 and font.getlength(line[:cut]) > max_width:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line.rstrip())
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines


def _hex_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _draw_icon(kind: str, size: int, color: tuple[int, int, int, int]) -> Image.Image:
    """Line icon drawn on a 24-unit grid, supersampled for smooth strokes."""
    ss = 4
    unit = size * ss / 24
    icon = Image.new('RGBA', (size * ss, size * ss), color[:3] + (0,))
    d = ImageDraw.Draw(icon)
    width = max(1, round(1.7 * unit))

    def p(*coords):
        return [round(c * unit) for c in coords]

    if kind == 'copy':
        radius = round(2 * unit)
        d.rounded_rectangle(p(9, 5, 19, 15), radius=radius, outline=color, width=width)
        # 擦掉前面那张纸遮住的部分，再画前面的纸。
        d.rounded_rectangle(p(3.5, 6.5, 16.5, 19.5), radius=radius, fill=color[:3] + (0,))
        d.rounded_rectangle(p(5, 8, 15, 18), radius=radius, outline=color, width=width)
    elif kind == 'done':
        d.line(p(6, 12.5, 10, 16.5, 18, 7.5), fill=color, width=width, joint='curve')
    elif kind == 'speak':
        d.polygon(p(4, 10, 8, 10, 12.5, 6, 12.5, 18, 8, 14, 4, 14), fill=color)
        d.arc(p(9, 8, 17, 16), -55, 55, fill=color, width=width)
        d.arc(p(8, 4.5, 21, 19.5), -55, 55, fill=color, width=width)
    elif kind == 'busy':
        for cx in (7, 12, 17):
            d.ellipse(p(cx - 1.6, 10.4, cx + 1.6, 13.6), fill=color)
    return icon.resize((size, size), Image.LANCZOS)


def _glass_metrics(original: str, translation: str, ui_scale: float) -> dict:
    def px(value: float) -> int:
        return round(value * ui_scale)

    width = px(GLASS_WIDTH)
    pad_x, pad_top, pad_bottom = px(16), px(14), px(12)
    content_width = width - 2 * pad_x
    orig_font, text_font = (_glass_font(px(GLASS_FONT_ORIG)),
                            _glass_font(px(GLASS_FONT_TEXT)))
    orig_line, text_line = round(orig_font.size * 1.45), round(text_font.size * 1.55)
    button = px(26)

    orig = (original[:80] + '…') if len(original) > 80 else original
    orig_lines = wrap_text(orig, orig_font, content_width)[:3]
    text_lines = wrap_text(translation, text_font, content_width)
    if len(text_lines) > GLASS_MAX_LINES:
        text_lines = text_lines[:GLASS_MAX_LINES]
        text_lines[-1] = text_lines[-1].rstrip() + '…'

    sep_y = pad_top + len(orig_lines) * orig_line + px(6)
    text_y = sep_y + 1 + px(9)
    button_y = text_y + len(text_lines) * text_line + px(4)
    return {
        'width': width, 'height': button_y + button + pad_bottom, 'pad_x': pad_x,
        'pad_top': pad_top, 'orig_font': orig_font, 'text_font': text_font,
        'orig_line': orig_line, 'text_line': text_line, 'orig_lines': orig_lines,
        'text_lines': text_lines, 'sep_y': sep_y, 'text_y': text_y,
        'button_y': button_y, 'button': button,
    }


def glass_popup_size(original: str, translation: str,
                     ui_scale: float = 1.0) -> tuple[int, int]:
    metrics = _glass_metrics(original, translation, ui_scale)
    return metrics['width'], metrics['height']


def glass_backdrop_margin(ui_scale: float = 1.0) -> int:
    """How far around the popup the captured backdrop reaches for blur and refraction."""
    return math.ceil((GLASS_REFRACTION + 2 * GLASS_BLUR + 2) * ui_scale)


def _virtual_screen() -> tuple[int, int, int, int]:
    metric = ctypes.windll.user32.GetSystemMetrics
    left, top = metric(76), metric(77)               # SM_XVIRTUALSCREEN / SM_YVIRTUALSCREEN
    return left, top, left + metric(78), top + metric(79)


def capture_backdrop(x: int, y: int, width: int, height: int,
                     exclude_hwnd=None) -> Image.Image | None:
    """capture_screen, with parts beyond the screens filled from the nearest edge."""
    left, top, right, bottom = _virtual_screen()
    x0, y0 = max(x, left), max(y, top)
    x1, y1 = min(x + width, right), min(y + height, bottom)
    if x1 <= x0 or y1 <= y0:
        return None
    shot = capture_screen(x0, y0, x1 - x0, y1 - y0, exclude_hwnd)
    if shot is None or shot.size == (width, height):
        return shot
    # 屏幕外截到的是黑色，折射会把它带进玻璃边缘，所以用最边上的像素拉伸补齐。
    ox, oy = x0 - x, y0 - y
    sw, sh = shot.size
    full = Image.new('RGB', (width, height))
    full.paste(shot, (ox, oy))
    if ox:
        full.paste(shot.crop((0, 0, 1, sh)).resize((ox, sh)), (0, oy))
    if width - ox - sw:
        full.paste(shot.crop((sw - 1, 0, sw, sh)).resize((width - ox - sw, sh)),
                   (ox + sw, oy))
    if oy:
        full.paste(full.crop((0, oy, width, oy + 1)).resize((width, oy)), (0, 0))
    if height - oy - sh:
        full.paste(full.crop((0, oy + sh - 1, width, oy + sh)).resize(
            (width, height - oy - sh)), (0, oy + sh))
    return full


def _refraction_mesh(width: int, height: int, margin: int, strength: float,
                     band: float) -> list:
    """Image.MESH data that samples further outside near the edges, like a glass lens."""
    # 折射场按圆角至少为折射带宽度的形状计算，转角处不会出现折痕。
    corner = min(max(band, GLASS_RADIUS), width / 2, height / 2)
    half_w, half_h = width / 2, height / 2

    def source(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - half_w, y - half_h
        qx, qy = abs(dx) - (half_w - corner), abs(dy) - (half_h - corner)
        if qx > 0 and qy > 0:
            length = math.hypot(qx, qy)
            depth = corner - length
            nx, ny = qx / length, qy / length
        elif qx >= qy:
            depth, nx, ny = corner - qx, 1.0, 0.0
        else:
            depth, nx, ny = corner - qy, 0.0, 1.0
        t = max(0.0, 1 - depth / band)
        offset = strength * t * t
        return (x + margin + math.copysign(nx, dx) * offset,
                y + margin + math.copysign(ny, dy) * offset)

    def stops(length: int) -> list[int]:
        step = max(2, round(band / 8))
        near = set(range(0, math.ceil(band) + 1, step))
        values = {0, length, *near, *(length - v for v in near)}
        return sorted(v for v in values if 0 <= v <= length)

    xs, ys = stops(width), stops(height)
    mesh = []
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            mesh.append(((x0, y0, x1, y1),
                         source(x0, y0) + source(x0, y1) + source(x1, y1) + source(x1, y0)))
    return mesh


@functools.lru_cache(maxsize=16)
def _glass_frame(width: int, height: int, ui_scale: float, radius: int, edge_alpha: int,
                 rim: tuple) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Rounded shape, dark outer line and white highlight (all 'L' masks)."""
    ss = 3
    big_radius = round(radius * ui_scale) * ss
    shape = Image.new('L', (width * ss, height * ss), 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        (0, 0, width * ss - 1, height * ss - 1), radius=big_radius, fill=255)
    shape = shape.resize((width, height), Image.LANCZOS)
    edge = Image.new('L', (width * ss, height * ss), 0)
    ImageDraw.Draw(edge).rounded_rectangle(
        (0, 0, width * ss - 1, height * ss - 1), radius=big_radius,
        outline=edge_alpha, width=ss)
    edge = edge.resize((width, height), Image.LANCZOS)
    highlight = ImageChops.multiply(
        render_glass_highlight(width, height, ui_scale, radius).convert('L'), shape)
    return shape, edge, highlight


def render_glass_background(backdrop: Image.Image | None, size: tuple[int, int],
                            ui_scale: float = 1.0) -> Image.Image:
    """The glass without text: the backdrop blurred, refracted and tinted.

    backdrop is the screen behind the popup plus glass_backdrop_margin() on
    every side; None draws an opaque fallback.
    """
    width, height = size
    if backdrop is None:
        glass = Image.new('RGB', size, GLASS_SOLID)
    else:
        image = backdrop.convert('RGB')
        margin = (image.width - width) // 2
        if GLASS_BLUR:
            image = image.filter(ImageFilter.GaussianBlur(GLASS_BLUR * ui_scale))
        if GLASS_SATURATION != 100:
            image = ImageEnhance.Color(image).enhance(GLASS_SATURATION / 100)
        if GLASS_BRIGHTNESS != 100:
            image = ImageEnhance.Brightness(image).enhance(GLASS_BRIGHTNESS / 100)
        strength = GLASS_REFRACTION * ui_scale
        if strength and margin > 0:
            glass = image.transform(
                size, Image.Transform.MESH,
                _refraction_mesh(width, height, margin, min(strength, margin),
                                 GLASS_REFRACT_BAND * ui_scale),
                Image.Resampling.BILINEAR)
        else:
            glass = image.crop((margin, margin, margin + width, margin + height))
        if GLASS_TINT_ALPHA:
            glass = Image.blend(glass, Image.new('RGB', size, GLASS_TINT_COLOR),
                                GLASS_TINT_ALPHA / 255)

    rim = (GLASS_RIM_PEAK, GLASS_RIM_BASE, GLASS_GLINT_BR, GLASS_RIM_WIDTH,
           GLASS_SHEEN_PEAK, GLASS_SHEEN_HEIGHT)
    shape, edge, highlight = _glass_frame(width, height, ui_scale, GLASS_RADIUS,
                                          GLASS_EDGE_ALPHA, rim)
    if backdrop is None:
        shape = shape.point([v * GLASS_SOLID_ALPHA // 255 for v in range(256)])
    glass = glass.convert('RGBA')
    glass.putalpha(shape)
    glass.alpha_composite(Image.merge('RGBA', [Image.new('L', size, 0)] * 3 + [edge]))
    glass.alpha_composite(Image.merge('RGBA', [Image.new('L', size, 255)] * 3 + [highlight]))
    return glass


def _glass_ink(background: Image.Image, box: tuple[int, int, int, int]
               ) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Text color and its halo color for the given glass area."""
    mode = GLASS_TEXT_MODE
    if mode == 'auto':
        brightness = ImageStat.Stat(background.convert('RGB').convert('L').crop(box)).mean[0]
        mode = 'dark' if brightness >= 150 else 'light'
    ink = _hex_rgb(GLASS_TEXT if mode == 'dark' else GLASS_TEXT_LIGHT)
    luminance = 0.299 * ink[0] + 0.587 * ink[1] + 0.114 * ink[2]
    return ink, ((255, 255, 255) if luminance < 128 else (0, 0, 0))


def render_glass_popup(original: str, translation: str, ui_scale: float = 1.0, *,
                       background: Image.Image | None = None, hover: str | None = None,
                       copy_state: str = 'idle',
                       speak_state: str = 'disabled') -> tuple[Image.Image, dict]:
    """Draw the whole glass popup as an RGBA image.

    background comes from render_glass_background(); without it the opaque
    fallback is used. Returns the image and the button hit boxes. copy_state
    is 'idle' or 'done'; speak_state is 'disabled', 'ready' or 'busy'.
    """
    def px(value: float) -> int:
        return round(value * ui_scale)

    m = _glass_metrics(original, translation, ui_scale)
    width, height, pad_x = m['width'], m['height'], m['pad_x']
    size = (width, height)
    if background is None or background.size != size:
        background = render_glass_background(None, size, ui_scale)
    image = background.copy()
    ink, halo = _glass_ink(background, (pad_x, m['pad_top'], width - pad_x,
                                        m['button_y']))

    def paint(mask: Image.Image, alpha: int, glow: bool = True):
        if glow and GLASS_HALO:
            spread = mask.filter(ImageFilter.GaussianBlur(max(1, px(2.5))))
            spread = spread.point([min(255, round(v * 4 * GLASS_HALO / 255))
                                   for v in range(256)])
            image.alpha_composite(Image.merge(
                'RGBA', [Image.new('L', size, c) for c in halo] + [spread]))
        mask = mask.point([v * alpha // 255 for v in range(256)])
        image.alpha_composite(Image.merge(
            'RGBA', [Image.new('L', size, c) for c in ink] + [mask]))

    def text_mask(lines: list[str], top: int, step: int, font) -> Image.Image:
        mask = Image.new('L', size, 0)
        d = ImageDraw.Draw(mask)
        for i, line in enumerate(lines):
            d.text((pad_x, top + i * step), line, font=font, fill=255)
        return mask

    paint(text_mask(m['orig_lines'], m['pad_top'], m['orig_line'], m['orig_font']), 165)
    separator = Image.new('L', size, 0)
    ImageDraw.Draw(separator).line((pad_x, m['sep_y'], width - pad_x, m['sep_y']),
                                   fill=255, width=1)
    paint(separator, GLASS_SEP_ALPHA, glow=False)
    paint(text_mask(m['text_lines'], m['text_y'], m['text_line'], m['text_font']), 255)

    layout = {}
    button, button_y = m['button'], m['button_y']
    buttons = [('copy', 'done' if copy_state == 'done' else 'copy', bool(translation)),
               ('speak', 'busy' if speak_state == 'busy' else 'speak',
                speak_state == 'ready')]
    x = width - pad_x - button + px(4)
    for name, icon, enabled in buttons:
        box = (x, button_y, x + button, button_y + button)
        layout[name] = box
        active = hover == name and enabled
        if active:
            plate = Image.new('L', size, 0)
            ImageDraw.Draw(plate).rounded_rectangle(box, radius=px(7), fill=255)
            paint(plate, 26, glow=False)
        mark = Image.new('L', size, 0)
        mark.paste(_draw_icon(icon, button, (255, 255, 255, 255)).getchannel('A'), (x, button_y))
        paint(mark, 255 if active else 175 if enabled else 70)
        x -= button + px(4)
    return image, layout


# ── 后台翻译线程 ──────────────────────────────────────────────

_ui_queue: queue.Queue = queue.Queue()
_simulating          = False


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


# ── 快捷键 ────────────────────────────────────────────────────
#
# 配置里存的是文本：'double-ctrl'（双击修饰键）或 'ctrl+shift+t'（组合键），
# 单个按键如 'f2' 也算组合键的一种。双击模式保留原有手势：短按、期间不按其他键。

DEFAULT_HOTKEY = 'double-ctrl'
_DOUBLE_MODIFIERS = ('ctrl', 'alt', 'shift', 'win')
_MODIFIER_KEYS = frozenset(_DOUBLE_MODIFIERS)
_MODIFIER_ALIASES = {
    'ctrl_l': 'ctrl', 'ctrl_r': 'ctrl',
    'control_l': 'ctrl', 'control_r': 'ctrl',
    'shift_l': 'shift', 'shift_r': 'shift',
    'alt_l': 'alt', 'alt_r': 'alt', 'alt_gr': 'alt',
    'cmd': 'win', 'cmd_l': 'win', 'cmd_r': 'win',
    'win_l': 'win', 'win_r': 'win',
}
_KEY_LABELS = {
    'ctrl': 'Ctrl', 'shift': 'Shift', 'alt': 'Alt', 'win': 'Win',
    'space': 'Space', 'tab': 'Tab', 'enter': 'Enter', 'esc': 'Esc',
    'backspace': 'Backspace', 'delete': 'Delete', 'insert': 'Insert',
    'home': 'Home', 'end': 'End', 'page_up': 'PageUp', 'page_down': 'PageDown',
    'caps_lock': 'CapsLock', 'print_screen': 'PrintScreen',
    'scroll_lock': 'ScrollLock', 'pause': 'Pause', 'menu': 'Menu',
}
_MODIFIER_ORDER = {'ctrl': 0, 'shift': 1, 'alt': 2, 'win': 3}


def key_name(key) -> str:
    """把 pynput 的按键对象转成规范名：修饰键归一，字符键取小写。

    Ctrl 组合下字符键的 char 往往是控制字符（Ctrl+C 是 \\x03），
    这时退回用 vk 还原成字母、数字或功能键名。
    """
    name = getattr(key, 'name', None)
    if name:
        return _MODIFIER_ALIASES.get(name, name)
    char = getattr(key, 'char', None)
    if char and char.isprintable() and not char.isspace():
        return char.lower()
    vk = getattr(key, 'vk', None)
    if vk is None:
        return ''
    if 65 <= vk <= 90:                      # A-Z
        return chr(vk).lower()
    if 48 <= vk <= 57:                      # 0-9
        return chr(vk)
    if 112 <= vk <= 123:                    # F1-F12
        return f'f{vk - 111}'
    return f'vk{vk}'


def parse_hotkey(text: str) -> dict:
    """解析快捷键配置文本。

    返回 {'mode': 'double', 'key': 'ctrl'} 或 {'mode': 'combo', 'keys': frozenset}。
    无法识别时退回默认的双击 Ctrl。
    """
    raw = (text or '').strip().lower().replace(' ', '')
    if raw.startswith('double-') and raw[7:] in _MODIFIER_KEYS:
        return {'mode': 'double', 'key': raw[7:]}
    keys = frozenset(_MODIFIER_ALIASES.get(part, part)
                     for part in raw.split('+') if part)
    if keys:
        return {'mode': 'combo', 'keys': keys}
    return {'mode': 'double', 'key': 'ctrl'}


def hotkey_text(spec: dict) -> str:
    """把解析结果写回配置文本。"""
    if spec['mode'] == 'double':
        return f"double-{spec['key']}"
    return '+'.join(sorted(spec['keys'],
                           key=lambda k: (_MODIFIER_ORDER.get(k, 9), k)))


def format_hotkey(spec: dict) -> str:
    """给界面显示的可读文本。"""
    if spec['mode'] == 'double':
        return f"双击 {_KEY_LABELS.get(spec['key'], spec['key'].title())}"
    parts = sorted(spec['keys'], key=lambda k: (_MODIFIER_ORDER.get(k, 9), k))
    return '+'.join(_KEY_LABELS.get(p, p.upper() if len(p) == 1 else p.title())
                    for p in parts)


class HotkeyMatcher:
    """把全局按键流翻译成“是否触发了快捷键”。

    double 模式沿用双击修饰键的手势：短按、且按住期间没按其他键。
    combo 模式在最后一个键按下时触发一次，直到松开其中任意键才重新生效，
    这样按住不放也不会反复翻译。
    """

    def __init__(self, spec: dict | None = None):
        self.spec = spec or parse_hotkey(DEFAULT_HOTKEY)
        self.reset()

    def reset(self):
        self._pressed: set[str] = set()
        self._mod_down = False
        self._mod_press_t = 0.0
        self._last_click_t = 0.0
        self._other_key = False
        self._fired = False

    @property
    def pressed(self) -> bool:
        """双击模式下修饰键是否按住；组合模式下是否有键按住。"""
        if self.spec['mode'] == 'double':
            return self._mod_down
        return bool(self._pressed)

    def set_spec(self, spec: dict):
        self.spec = spec
        self.reset()

    def press(self, name: str) -> bool:
        if not name:
            return False
        if self.spec['mode'] == 'double':
            return self._press_double(name)
        self._pressed.add(name)
        if not self._fired and self._pressed == self.spec['keys']:
            self._fired = True
            return True
        return False

    def release(self, name: str) -> bool:
        if not name:
            return False
        if self.spec['mode'] == 'double':
            return self._release_double(name)
        self._pressed.discard(name)
        if not self.spec['keys'] <= self._pressed:
            self._fired = False
        return False

    def _press_double(self, name: str) -> bool:
        if name == self.spec['key']:
            if not self._mod_down:          # 避免长按重复触发
                self._mod_down = True
                self._mod_press_t = time.time()
                self._other_key = False
        else:
            self._other_key = True
        return False

    def _release_double(self, name: str) -> bool:
        if name != self.spec['key'] or not self._mod_down:
            return False
        hold = time.time() - self._mod_press_t
        self._mod_down = False
        # 长按 或 期间按了其他键（如 Ctrl+C）→ 不计入双击
        if hold > MAX_HOLD or self._other_key:
            self._last_click_t = 0.0
            return False
        now = time.time()
        if now - self._last_click_t < DOUBLE_CLICK_INTERVAL:
            self._last_click_t = 0.0
            return True
        self._last_click_t = now
        return False


_hotkey = HotkeyMatcher()


def apply_hotkey(text: str):
    """切换生效的快捷键；无法解析时退回默认的双击 Ctrl。"""
    _hotkey.set_spec(parse_hotkey(text))


def load_hotkey() -> str:
    cfg = _read_config()
    return cfg.get('settings', 'hotkey', fallback=DEFAULT_HOTKEY).strip() or DEFAULT_HOTKEY


def save_hotkey(text: str):
    cfg = _read_config()
    if not cfg.has_section('settings'):
        cfg.add_section('settings')
    cfg.set('settings', 'hotkey', text)
    _write_config(cfg)


def on_key_press(key):
    if _simulating:
        return
    name = key_name(key)
    if not name:
        return
    if name not in _MODIFIER_KEYS:      # 修饰键之外的动作视为新的操作
        _mouse_selection.clear()
    if _hotkey.press(name):
        threading.Thread(target=translation_worker, daemon=True).start()


def on_key_release(key):
    if _simulating:
        return
    if _hotkey.release(key_name(key)):
        threading.Thread(target=translation_worker, daemon=True).start()


# ── 悬浮窗管理 ────────────────────────────────────────────────

class PopupManager:
    def __init__(self, root: tk.Tk, poll: bool = True):
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
        self._drag_offset = (0, 0)
        self._scale = ui_scale(root)
        # 玻璃模式下悬浮窗的内容是一整张图片，按钮状态都记在这里。
        self._glass = False
        self._glass_hwnd = None
        self._glass_pos = (0, 0)
        self._glass_size = (1, 1)
        self._glass_text = ''
        self._glass_shot: Image.Image | None = None      # 截到的背后画面
        self._glass_bg: Image.Image | None = None        # 由它画出的玻璃
        self._glass_shown = False
        self._glass_pending = None
        self._glass_image: Image.Image | None = None
        self._glass_layout: dict = {}
        self._glass_hover: str | None = None
        self._copy_state = 'idle'
        self._speak_state = 'disabled'
        self._press_target: str | None = None
        if poll:
            self._poll()

    def _px(self, value: int) -> int:
        return round(value * self._scale)

    def _poll(self):
        try:
            while True:
                msg = _ui_queue.get_nowait()
                if msg[0] == 'show':
                    _, text, placeholder, x, y, selection_bounds = msg
                    self._show(text, placeholder, x, y, selection_bounds)
                elif msg[0] == 'update':
                    if self.popup and self.popup.winfo_exists():
                        self._set_result(msg[1])
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _set_result(self, text: str):
        self._translation = text          # 缓存翻译结果，供复制使用
        if self._glass:
            self._glass_text = text
            self._copy_state = 'idle'
            self._speak_state = 'ready'
            self._glass_size = glass_popup_size(self._original, text, self._scale)
        else:
            tw = self.result_text
            tw.config(state='normal')
            tw.delete('1.0', 'end')
            tw.insert('1.0', text)
            tw.update_idletasks()
            lines = tw.count('1.0', 'end', 'displaylines')
            if lines:
                tw.config(height=max(1, min(lines[0], 10)))
            tw.config(state='disabled')
            if self.copy_btn and self.popup and self.popup.winfo_exists():
                self.copy_btn.config(text='⧉')
            if self.speak_btn and self.popup and self.popup.winfo_exists():
                self.speak_btn.config(state='normal', fg='#888888')
        if self.popup and self.popup.winfo_exists():
            self._position_popup()

    def _popup_size(self) -> tuple[int, int]:
        if self._glass:
            return self._glass_size
        self.popup.update_idletasks()
        return self.popup.winfo_reqwidth(), self.popup.winfo_reqheight()

    def _position_popup(self):
        popup = self.popup
        pw, ph = self._popup_size()

        if self._popup_dragged:
            x, y = (self._glass_pos if self._glass
                    else (popup.winfo_rootx(), popup.winfo_rooty()))
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
        if self._glass:
            # 先截新位置背后的画面再显示，玻璃里不会出现上一次的内容。
            self._glass_pos = (px, py)
            self._glass_capture()
            self._render_glass()
        self._move_popup(px, py)
        popup.update_idletasks()

    def _move_popup(self, px: int, py: int):
        if self._glass:
            # 分层窗口的大小由图片决定；同时写明宽高，免得 Tk 按自己的尺寸改回去。
            w, h = self._glass_size
            self._glass_pos = (px, py)
            self.popup.geometry(f'{w}x{h}+{px}+{py}')
        else:
            self.popup.geometry(f'+{px}+{py}')

    def _start_drag(self, x_root: int, y_root: int):
        x, y = (self._glass_pos if self._glass
                else (self.popup.winfo_rootx(), self.popup.winfo_rooty()))
        self._drag_offset = (x_root - x, y_root - y)

    def _drag_to(self, x_root: int, y_root: int):
        self._popup_dragged = True
        pw, ph = (self._glass_size if self._glass
                  else (self.popup.winfo_width(), self.popup.winfo_height()))
        work_left, work_top, work_right, work_bottom = get_work_area(x_root, y_root)
        px = min(max(x_root - self._drag_offset[0], work_left + 8),
                 max(work_left + 8, work_right - pw - 8))
        py = min(max(y_root - self._drag_offset[1], work_top + 8),
                 max(work_top + 8, work_bottom - ph - 8))
        self._move_popup(px, py)

    def _show(self, text: str, placeholder: str, x: int, y: int,
              selection_bounds: tuple[int, int, int, int] | None = None):
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()

        self._original = text             # 缓存原文，供朗读使用
        self._translation = ''
        self._popup_anchor = (x, y)
        self._selection_bounds = selection_bounds
        self._popup_dragged = False
        self._glass = glass_supported()
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        self.popup = popup

        if self._glass:
            self._build_glass(popup, placeholder)
        else:
            self._build_classic(popup, text, placeholder)

        # 靠近选区右下角；按住空白处可拖动。
        self._position_popup()

        popup.update()
        if not self._glass:
            try:
                apply_rounded_corners(ctypes.windll.user32.GetParent(popup.winfo_id()))
            except Exception:
                pass

        popup.after(300, lambda: self._watch_outside_click(popup))

    # ── 玻璃模式 ──

    def _build_glass(self, popup: tk.Toplevel, placeholder: str):
        self._glass_text = placeholder
        self._glass_size = glass_popup_size(self._original, placeholder, self._scale)
        self._glass_shot = self._glass_bg = None
        self._glass_shown = False
        self._glass_pending = None
        self._glass_hover = None
        self._copy_state = 'idle'
        self._speak_state = 'disabled'
        self._press_target = None
        # 先在屏幕外创建窗口并切换为分层窗口，避免闪出一个空白方块。
        popup.geometry('1x1+-32000+-32000')
        popup.update_idletasks()
        self._glass_hwnd = ctypes.windll.user32.GetParent(popup.winfo_id())
        make_layered(self._glass_hwnd)
        popup.after(GLASS_REFRESH_MS, lambda: self._glass_tick(popup))

        popup.configure(cursor='fleur')
        popup.bind('<Motion>', lambda e: self._glass_set_hover(self._glass_hit(e.x, e.y)))
        popup.bind('<Leave>', lambda e: self._glass_set_hover(None))
        popup.bind('<ButtonPress-1>', self._glass_press)
        popup.bind('<B1-Motion>', self._glass_drag)
        popup.bind('<ButtonRelease-1>', self._glass_release)
        popup.bind('<Control-KeyPress>', self._glass_key)

    def _glass_capture(self) -> bool:
        """Capture what is behind the popup again; True when the glass changed."""
        width, height = self._glass_size
        margin = glass_backdrop_margin(self._scale)
        x, y = self._glass_pos
        # 窗口还在屏幕外时不用排除它；之后每次截图都先把自己排除掉。
        shot = capture_backdrop(x - margin, y - margin, width + 2 * margin,
                                height + 2 * margin,
                                self._glass_hwnd if self._glass_shown else None)
        fresh = self._glass_bg is not None and self._glass_bg.size == (width, height)
        if shot is None and fresh:
            return False
        if (fresh and shot is not None and self._glass_shot is not None
                and shot.size == self._glass_shot.size
                and ImageChops.difference(shot, self._glass_shot).getbbox() is None):
            return False
        self._glass_shot = shot
        self._glass_bg = render_glass_background(shot, (width, height), self._scale)
        return True

    def _glass_tick(self, popup: tk.Toplevel):
        if popup is not self.popup or not popup.winfo_exists():
            return
        if self._glass_capture():
            self._render_glass()
        popup.after(GLASS_REFRESH_MS, lambda: self._glass_tick(popup))

    def _glass_refresh_soon(self):
        if self._glass_pending is None and self.popup:
            self._glass_pending = self.popup.after(15, self.refresh_backdrop)

    def refresh_backdrop(self):
        """Redraw the glass now if what is behind the popup has changed."""
        self._glass_pending = None
        if self.popup and self.popup.winfo_exists() and self._glass_capture():
            self._render_glass()

    def restyle(self):
        """Redraw the open popup after the glass style changed."""
        if self._glass and self.popup and self.popup.winfo_exists():
            self._glass_bg = render_glass_background(self._glass_shot, self._glass_size,
                                                     self._scale)
            self._render_glass()

    def _render_glass(self, push: bool = True):
        if self._glass_bg is None or self._glass_bg.size != self._glass_size:
            self._glass_capture()
        self._glass_image, self._glass_layout = render_glass_popup(
            self._original, self._glass_text, self._scale, background=self._glass_bg,
            hover=self._glass_hover, copy_state=self._copy_state,
            speak_state=self._speak_state)
        if push and self.popup and self.popup.winfo_exists():
            update_layered_window(self._glass_hwnd, self._glass_image, *self._glass_pos)
            self._glass_shown = True

    def _glass_hit(self, x: int, y: int) -> str | None:
        enabled = {'copy': bool(self._translation),
                   'speak': self._speak_state == 'ready'}
        for name, (x0, y0, x1, y1) in self._glass_layout.items():
            if enabled.get(name) and x0 <= x < x1 and y0 <= y < y1:
                return name
        return None

    def _glass_set_hover(self, name: str | None):
        if name == self._glass_hover or not self.popup or not self.popup.winfo_exists():
            return
        self._glass_hover = name
        self.popup.configure(cursor='hand2' if name else 'fleur')
        self._render_glass()

    def _glass_press(self, event):
        self._press_target = self._glass_hit(event.x, event.y)
        if self._press_target is None:
            self._start_drag(event.x_root, event.y_root)

    def _glass_drag(self, event):
        if self._press_target is None:
            self._drag_to(event.x_root, event.y_root)
            self._glass_refresh_soon()

    def _glass_release(self, event):
        target, self._press_target = self._press_target, None
        if target and target == self._glass_hit(event.x, event.y):
            self._glass_action(target)

    def _glass_key(self, event):
        if event.keysym.lower() == 'c':
            self._glass_action('copy')
        return 'break'

    def _glass_action(self, name: str):
        popup = self.popup

        def still_open() -> bool:
            return popup is self.popup and popup.winfo_exists()

        if name == 'copy' and self._translation:
            pyperclip.copy(self._translation)
            self._copy_state = 'done'
            self._render_glass()

            def reset_copy():
                if still_open():
                    self._copy_state = 'idle'
                    self._render_glass()
            popup.after(1500, reset_copy)
        elif name == 'speak' and self._speak_state == 'ready':
            self._speak_state = 'busy'
            self._render_glass()

            def speak_done():
                if still_open():
                    self._speak_state = 'ready'
                    self._render_glass()
            speak_text(self._original, speak_done, popup)

    # ── 经典模式（系统不支持透明效果时） ──

    def _build_classic(self, popup: tk.Toplevel, text: str, placeholder: str):
        popup.attributes('-alpha', 0.94)
        popup.configure(bg=BG)

        frame = tk.Frame(popup, bg=BG, padx=self._px(16), pady=self._px(14))
        frame.pack(fill='both', expand=True)

        # 原文（灰色截断）。经典主题比玻璃小一号，保持两边的观感接近。
        orig = (text[:80] + '…') if len(text) > 80 else text
        orig_label = tk.Label(frame, text=orig, bg=BG, fg=FG_ORIG,
                              font=('Segoe UI', max(7, GLASS_FONT_ORIG - 3)),
                              wraplength=self._px(340),
                              justify='left', cursor='fleur')
        orig_label.pack(anchor='w')

        for widget in (frame, orig_label):
            widget.bind('<ButtonPress-1>',
                        lambda e: self._start_drag(e.x_root, e.y_root))
            widget.bind('<B1-Motion>', lambda e: self._drag_to(e.x_root, e.y_root))

        tk.Frame(frame, bg=FG_SEP, height=1).pack(
            fill='x', pady=(self._px(8), self._px(8)))

        # 译文（可选中复制）
        result_text = tk.Text(
            frame, bg=BG, fg='#ffffff',
            font=('Microsoft YaHei UI', max(8, GLASS_FONT_TEXT - 4)), width=36, height=1,
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
        btn_row.pack(fill='x', pady=(self._px(6), 0))

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
                speak_text(txt, lambda: speak_btn.config(text='🔊', state='normal'),
                           popup)

        speak_btn = tk.Button(
            btn_row, text='🔊',
            bg=BG, fg='#444444',
            activebackground=BG, activeforeground='#aaaaaa',
            relief='flat', borderwidth=0,
            font=('Segoe UI', 11), cursor='hand2',
            padx=2, pady=0, state='disabled',
            command=do_speak,
        )
        speak_btn.pack(side='right', padx=(0, self._px(6)))
        self.speak_btn = speak_btn

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


# ── 外观设置窗口 ──────────────────────────────────────────────

STYLE_SAMPLE = ('Liquid glass makes the translation popup feel light and modern.',
                '液态玻璃让翻译悬浮窗显得轻盈而现代。')
# 两列控件：('title', 标题) / ('color' | 'scale' | 'mode', 配置项名, 标签)
_STYLE_LAYOUT = (
    (('title', '玻璃'),
     ('color', 'tint_color', '玻璃颜色'), ('scale', 'tint_alpha', '颜色浓度'),
     ('scale', 'blur', '模糊'), ('scale', 'saturation', '饱和度 %'),
     ('scale', 'brightness', '亮度 %'), ('scale', 'refraction', '边缘折射'),
     ('scale', 'radius', '圆角')),
    (('title', '文字'),
     ('scale', 'font_orig', '原文字号'), ('scale', 'font_text', '译文字号'),
     ('mode', 'text_mode', '文字颜色'), ('color', 'text_dark', '深色文字'),
     ('color', 'text_light', '浅色文字'), ('scale', 'halo', '文字衬光'),
     ('title', '高光'),
     ('scale', 'rim', '白色描边'), ('scale', 'sheen', '顶部光泽'),
     ('scale', 'edge', '外沿细线'), ('scale', 'separator', '分隔线')),
)
_TEXT_MODES = (('auto', '自动'), ('dark', '深色'), ('light', '浅色'))
_style_editor: tk.Toplevel | None = None


class _StylePreview(PopupManager):
    # 预览不能因为点击外观窗口而关闭。
    def _watch_outside_click(self, popup):
        pass


def open_style_editor(root: tk.Tk, on_close=None) -> tk.Toplevel:
    """Window for adjusting the glass, with a live preview popup beside it."""
    global _style_editor
    if _style_editor is not None and _style_editor.winfo_exists():
        _style_editor.deiconify()
        _style_editor.lift()
        _style_editor.focus_force()
        return _style_editor

    opened = get_glass_style()
    win = tk.Toplevel(root)
    _style_editor = win
    win.title(f'{APP_NAME} - 外观设置')
    win.resizable(False, False)
    win.attributes('-topmost', True)
    scale = ui_scale(win)

    def px(value: float) -> int:
        return round(value * scale)

    font = ('Microsoft YaHei UI', 9)
    bold = (font[0], 10, 'bold')
    body = tk.Frame(win, padx=px(16), pady=px(12))
    body.pack(fill='both', expand=True)
    if not glass_supported():
        tk.Label(body, text='系统的“透明效果”已关闭（设置 → 个性化 → 颜色），'
                            '翻译框会显示为深色经典样式，这里的设置暂时不生效。',
                 fg='#c0392b', font=font, wraplength=px(560), justify='left'
                 ).pack(anchor='w', pady=(0, px(8)))

    preview = _StylePreview(root, poll=False)
    win.preview = preview
    variables: dict[str, tk.Variable] = {}
    swatches: dict[str, tk.Label] = {}
    pending = [None]

    def refresh():
        pending[0] = None
        if not win.winfo_exists():
            return
        if preview.popup and preview.popup.winfo_exists():
            preview.restyle()
            return
        win.update_idletasks()
        preview._show(STYLE_SAMPLE[0], '翻译中…',
                      win.winfo_rootx() + win.winfo_width(), win.winfo_rooty())
        preview._set_result(STYLE_SAMPLE[1])

    def schedule():
        if pending[0] is not None:
            win.after_cancel(pending[0])
        pending[0] = win.after(60, refresh)

    def sync():
        style = get_glass_style()
        for key, var in variables.items():
            var.set(style[key])
        for key, swatch in swatches.items():
            swatch.config(bg=style[key])

    def commit(changes: dict, update_fields: bool = True):
        set_glass_style(changes)
        if update_fields:
            sync()
        schedule()

    def apply(style: dict):
        set_glass_style(style)
        sync()
        schedule()

    def pick(key: str, title: str):
        _, chosen = colorchooser.askcolor(variables[key].get(), parent=win, title=title)
        if chosen:
            commit({key: chosen})

    presets = tk.Frame(body)
    presets.pack(anchor='w', pady=(0, px(4)))
    tk.Label(presets, text='预设', font=bold).pack(side='left', padx=(0, px(10)))
    for name, preset in GLASS_PRESETS.items():
        tk.Button(presets, text=name, font=font, padx=px(10),
                  command=lambda p=preset: apply(p)).pack(side='left', padx=(0, px(6)))

    columns = tk.Frame(body)
    columns.pack(anchor='w')
    for c, rows in enumerate(_STYLE_LAYOUT):
        column = tk.Frame(columns)
        column.grid(row=0, column=c, sticky='nw', padx=(0, px(28) if c == 0 else 0))
        for r, row in enumerate(rows):
            if row[0] == 'title':
                tk.Label(column, text=row[1], font=bold).grid(
                    row=r, column=0, columnspan=2, sticky='w',
                    pady=(px(10), px(2)))
                continue
            kind, key, label = row
            tk.Label(column, text=label, font=font).grid(row=r, column=0, sticky='w',
                                                         padx=(0, px(10)))
            cell = tk.Frame(column)
            cell.grid(row=r, column=1, sticky='w', pady=px(2))
            if kind == 'color':
                var = tk.StringVar()
                swatch = tk.Label(cell, width=4, relief='solid', borderwidth=1,
                                  cursor='hand2')
                swatch.pack(side='left', ipady=px(1))
                swatch.bind('<Button-1>', lambda e, k=key, t=label: pick(k, t))
                swatches[key] = swatch
                entry = tk.Entry(cell, textvariable=var, width=9, font=('Consolas', 9))
                entry.pack(side='left', padx=(px(6), 0))
                for event in ('<Return>', '<FocusOut>'):
                    entry.bind(event, lambda e, k=key: commit({k: variables[k].get()}))
            elif kind == 'mode':
                var = tk.StringVar()
                for value, text in _TEXT_MODES:
                    tk.Radiobutton(cell, text=text, value=value, variable=var, font=font,
                                   command=lambda k=key: commit({k: variables[k].get()})
                                   ).pack(side='left')
            else:
                low, high = GLASS_STYLE_FIELDS[key][1]
                var = tk.IntVar()
                tk.Scale(cell, from_=low, to=high, orient='horizontal', variable=var,
                         length=px(180), showvalue=False, borderwidth=0,
                         highlightthickness=0,
                         command=lambda _v, k=key: commit({k: variables[k].get()},
                                                          update_fields=False)
                         ).pack(side='left')
                tk.Label(cell, textvariable=var, width=4, anchor='e', font=font
                         ).pack(side='left')
            variables[key] = var

    footer = tk.Frame(body)
    footer.pack(fill='x', pady=(px(14), 0))
    status = tk.Label(footer, font=font, fg='#c0392b')

    def close(restore: bool):
        global _style_editor
        if restore:
            set_glass_style(opened)
        if preview.popup and preview.popup.winfo_exists():
            preview.popup.destroy()
        _style_editor = None
        win.destroy()
        if on_close:
            on_close()

    def save():
        try:
            save_glass_style(get_glass_style())
        except OSError as e:
            status.config(text=f'保存失败：{e}')
            return
        close(restore=False)

    tk.Button(footer, text='  保存  ', font=font, command=save).pack(side='right')
    tk.Button(footer, text='取消', font=font, padx=px(8),
              command=lambda: close(restore=True)).pack(side='right', padx=(0, px(6)))
    tk.Button(footer, text='恢复默认', font=font, padx=px(8),
              command=lambda: apply(GLASS_DEFAULT_STYLE)).pack(side='left')
    status.pack(side='left', padx=(px(8), 0))
    win.protocol('WM_DELETE_WINDOW', lambda: close(restore=True))
    win.bind('<Escape>', lambda e: close(restore=True))

    sync()
    win.update_idletasks()
    # 放在屏幕中间偏左，右边留出位置给预览。
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    left, top, right, bottom = get_work_area(*get_mouse_pos())
    x = max(left + px(16), (left + right) // 2 - w + px(40))
    y = max(top + px(16), top + (bottom - top - h) // 3)
    win.geometry(f'+{x}+{y}')
    win.update()
    refresh()
    return win


# ── 快捷键设置窗口 ────────────────────────────────────────────

_hotkey_dialog: tk.Toplevel | None = None


def open_hotkey_dialog(root: tk.Tk) -> tk.Toplevel:
    """快捷键设置：显示当前设置，可捕获组合键或选双击修饰键。"""
    global _hotkey_dialog
    if _hotkey_dialog is not None and _hotkey_dialog.winfo_exists():
        _hotkey_dialog.deiconify()
        _hotkey_dialog.lift()
        _hotkey_dialog.focus_force()
        return _hotkey_dialog

    current = [load_hotkey()]
    capturing = [False]
    held_mods: set[str] = set()

    win = tk.Toplevel(root)
    _hotkey_dialog = win
    win.title(f'{APP_NAME} - 快捷键')
    win.resizable(False, False)
    win.attributes('-topmost', True)
    scale = ui_scale(win)

    def px(value: float) -> int:
        return round(value * scale)

    font = ('Microsoft YaHei UI', 9)
    body = tk.Frame(win, padx=px(18), pady=px(14))
    body.pack(fill='both', expand=True)

    tip = ('点“按下新快捷键”后直接按组合键，例如 Ctrl+Shift+T；'
           '也可以从下面的预设里选双击某个修饰键。')
    tk.Label(body, text='当前快捷键', font=font, fg='#666666').pack(anchor='w')
    display = tk.Label(body, text=format_hotkey(parse_hotkey(current[0])),
                       font=('Microsoft YaHei UI', 15, 'bold'), fg=ACCENT)
    display.pack(anchor='w', pady=(px(2), px(8)))
    hint = tk.Label(body, text=tip, font=font, fg='#666666',
                    justify='left', wraplength=px(430))
    hint.pack(anchor='w', pady=(0, px(10)))

    def stop_capture():
        capturing[0] = False
        held_mods.clear()
        win.unbind('<KeyPress>')

    def show(text: str):
        current[0] = text
        display.config(text=format_hotkey(parse_hotkey(text)), fg=ACCENT)
        hint.config(text=tip)
        stop_capture()

    def on_key(event):
        if not capturing[0]:
            return
        mod = {'Control_L': 'ctrl', 'Control_R': 'ctrl',
               'Shift_L': 'shift', 'Shift_R': 'shift',
               'Alt_L': 'alt', 'Alt_R': 'alt',
               'Win_L': 'win', 'Win_R': 'win'}.get(event.keysym)
        if mod:
            held_mods.add(mod)
            return
        mods = set(held_mods)
        if event.state & 0x0004:            # Control
            mods.add('ctrl')
        if event.state & 0x0001:            # Shift
            mods.add('shift')
        if event.state & 0x20000:           # Alt
            mods.add('alt')
        show(hotkey_text({'mode': 'combo',
                          'keys': frozenset(mods | {event.keysym.lower()})}))
        return 'break'

    def start_capture():
        capturing[0] = True
        held_mods.clear()
        display.config(text='请按下快捷键…', fg=CRAYON_RED)
        hint.config(text='等待按键：按下组合键即可，按 Esc 取消。')
        win.focus_force()
        win.bind('<KeyPress>', on_key)

    row = tk.Frame(body)
    row.pack(anchor='w', pady=(0, px(6)))
    tk.Button(row, text='按下新快捷键', font=font, command=start_capture
              ).pack(side='left', padx=(0, px(8)))
    for name in _DOUBLE_MODIFIERS:
        tk.Button(row, text=f'双击 {_KEY_LABELS[name]}', font=font,
                  command=lambda n=name: show(f'double-{n}')
                  ).pack(side='left', padx=(0, px(6)))

    tk.Label(body, justify='left', wraplength=px(430), font=font, fg=CRAYON_ORANGE,
             text='注意：Ctrl+C 这类系统快捷键也能设，但设置后每次复制都会弹出翻译窗，'
                  '因为程序本身也靠模拟 Ctrl+C 取走选中文字。'
             ).pack(anchor='w', pady=(px(6), px(10)))

    footer = tk.Frame(body)
    footer.pack(fill='x')
    status = tk.Label(footer, font=font, fg='#c0392b')

    def close():
        global _hotkey_dialog
        stop_capture()
        _hotkey_dialog = None
        win.destroy()

    def on_escape(event):
        if capturing[0]:
            show(current[0])
        else:
            close()

    def save():
        try:
            save_hotkey(current[0])
        except OSError as e:
            status.config(text=f'保存失败：{e}')
            return
        apply_hotkey(current[0])
        close()

    tk.Button(footer, text='  保存  ', font=font, command=save).pack(side='right')
    tk.Button(footer, text='取消', font=font, padx=px(8),
              command=close).pack(side='right', padx=(0, px(6)))
    tk.Button(footer, text='恢复默认', font=font, padx=px(8),
              command=lambda: show(DEFAULT_HOTKEY)).pack(side='left')
    status.pack(side='left', padx=(px(8), 0))
    win.protocol('WM_DELETE_WINDOW', close)
    win.bind('<Escape>', on_escape)

    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    left, top, right, bottom = get_work_area(*get_mouse_pos())
    win.geometry(f'+{(left + right - w) // 2}'
                 f'+{max(top + px(30), (top + bottom - h) // 2)}')
    win.focus_force()
    return win


# ── 入口 ─────────────────────────────────────────────────────

def main():
    enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()

    is_first_run = not os.path.exists(CONFIG_FILE)

    apply_api_settings(load_api_settings())
    while not API_KEY:
        settings = show_settings_dialog(root, current_api_settings())
        if settings is None:
            root.destroy()
            return
        save_api_settings(**settings)
        apply_api_settings(settings)
    load_glass_style()
    apply_hotkey(load_hotkey())

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
