"""液态玻璃调节器：在几种测试背景上打开 SelectTrans 的“外观”窗口，方便对比效果。"""

import os
import sys
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import selecttrans as tr  # noqa: E402

BACKDROPS = ['风景渐变', '彩色条纹', '白色网页', '深色网页']


def _font(size: int) -> ImageFont.ImageFont:
    for name in ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf', 'segoeui.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw_backdrop(kind: str, width: int, height: int, scale: float) -> Image.Image:
    img = Image.new('RGB', (width, height), 'white')
    d = ImageDraw.Draw(img)
    line_h = round(34 * scale)
    body, title = _font(round(20 * scale)), _font(round(34 * scale))
    if kind == '彩色条纹':
        colors = ['#ff4d4d', '#ffd24d', '#4dff88', '#4dc3ff', '#b84dff', '#ffffff', '#202020']
        step = round(50 * scale)
        for i in range(width // step + 1):
            d.rectangle((i * step, 0, i * step + step, height), fill=colors[i % len(colors)])
        for j in range(height // line_h):
            d.text((round(30 * scale), j * line_h + round(6 * scale)),
                   'The quick brown fox 背景文字 jumps over the lazy dog ' * 2,
                   fill='black', font=_font(round(22 * scale)))
    elif kind in ('白色网页', '深色网页'):
        dark = kind == '深色网页'
        bg, fg, muted = (('#1e1f22', '#e6e6e6', '#8a8a8a') if dark
                         else ('#ffffff', '#202124', '#5f6368'))
        d.rectangle((0, 0, width, height), fill=bg)
        d.rectangle((0, 0, width, round(64 * scale)), fill='#2b2d31' if dark else '#f1f3f4')
        d.text((round(40 * scale), round(84 * scale)), 'Liquid Glass — Design Notes',
               fill='#8ab4f8' if dark else '#1a0dab', font=title)
        y = round(150 * scale)
        while y < height:
            d.text((round(40 * scale), y),
                   'Glass surfaces refract and blur whatever sits behind them, '
                   'so the content stays readable while the context shows through. '
                   '这是一段用于测试的正文文字。',
                   fill=fg if (y // line_h) % 4 else muted, font=body)
            y += line_h
    elif kind == '风景渐变':
        top, bottom = (40, 90, 200), (255, 150, 80)
        for y in range(height):
            t = y / max(1, height - 1)
            d.line((0, y, width, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
        for cx, cy, r, c in [(0.2, 0.3, 0.12, '#ffe066'), (0.55, 0.45, 0.18, '#ff6b9a'),
                             (0.8, 0.25, 0.1, '#7bffb0'), (0.4, 0.8, 0.22, '#3d2c8d')]:
            R = round(r * width)
            d.ellipse((round(cx * width) - R, round(cy * height) - R,
                       round(cx * width) + R, round(cy * height) + R), fill=c)
    return img


def main():
    tr.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    tr.load_glass_style()
    scale = tr.ui_scale(root)
    px = lambda v: round(v * scale)  # noqa: E731

    editor = tr.open_style_editor(root, on_close=root.destroy)
    editor.update_idletasks()
    # 背景窗口放在外观窗口右边，预览的翻译框正好浮在它上面。
    bd_w, bd_h = px(900), px(560)
    bd_x = editor.winfo_rootx() + editor.winfo_width() + px(4)
    bd_y = editor.winfo_rooty() - px(60)
    backdrop = tk.Toplevel(root)
    backdrop.title('测试背景（点上面的按钮切换）')
    backdrop.geometry(f'{bd_w}x{bd_h}+{bd_x}+{bd_y}')
    # 置顶，否则从命令行启动时它可能被压在当前窗口下面；预览框再提到它上面。
    backdrop.attributes('-topmost', True)
    backdrop.protocol('WM_DELETE_WINDOW', backdrop.withdraw)
    bar = tk.Frame(backdrop)
    bar.pack(fill='x')
    canvas = tk.Canvas(backdrop, highlightthickness=0)
    canvas.pack(fill='both', expand=True)

    def show(kind: str):
        backdrop.update_idletasks()
        w, h = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        canvas.image = ImageTk.PhotoImage(draw_backdrop(kind, w, h, scale), master=backdrop)
        canvas.delete('all')
        canvas.create_image(0, 0, image=canvas.image, anchor='nw')
        backdrop.update()
        popup = editor.preview.popup
        if popup and popup.winfo_exists():
            popup.lift()
        editor.lift()
        editor.preview.refresh_backdrop()

    for kind in BACKDROPS:
        tk.Button(bar, text=kind, font=('Microsoft YaHei UI', 9),
                  command=lambda k=kind: show(k)).pack(side='left', padx=px(4), pady=px(4))
    backdrop.after(100, lambda: show(BACKDROPS[0]))
    root.mainloop()


if __name__ == '__main__':
    main()
