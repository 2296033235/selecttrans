import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'win32':
    import translator
else:
    translator = None


def make_root(test):
    root = translator.tk.Tk()
    root.withdraw()

    def destroy():
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.tk.call('after', 'cancel', job)
        root.destroy()

    test.addCleanup(destroy)
    return root


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class LanguageTests(unittest.TestCase):
    def test_english(self):
        self.assertEqual(translator.detect_lang('Hello, world!'), 'en')

    def test_chinese(self):
        self.assertEqual(translator.detect_lang('\u4f60\u597d'), 'zh')

    def test_mixed_text_uses_chinese(self):
        self.assertEqual(translator.detect_lang('Hello \u4f60\u597d'), 'zh')

    def test_empty_text(self):
        self.assertEqual(translator.detect_lang(''), 'en')


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / 'translator_config.ini'
        config_patch = patch.object(translator, 'CONFIG_FILE', str(self.config))
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_missing_config(self):
        self.assertEqual(translator.load_api_key(), '')

    def test_empty_config(self):
        self.config.touch()
        self.assertEqual(translator.load_api_key(), '')

    def test_config_round_trip(self):
        translator.save_api_key('example.test-only')
        self.assertEqual(translator.load_api_key(), 'example.test-only')

    def test_glass_style_and_api_key_share_the_config(self):
        self.addCleanup(translator.set_glass_style, translator.get_glass_style())
        translator.save_api_key('example.test-only')
        translator.save_glass_style({**translator.GLASS_DEFAULT_STYLE, 'blur': 20})
        translator.save_api_key('example.changed')
        translator.set_glass_style(translator.GLASS_DEFAULT_STYLE)
        translator.load_glass_style()
        self.assertEqual(translator.GLASS_BLUR, 20)
        self.assertEqual(translator.load_api_key(), 'example.changed')

    @staticmethod
    def _editor_buttons(editor):
        return {widget.cget('text').strip(): widget
                for frame in editor.winfo_children()[0].winfo_children()
                for widget in frame.winfo_children()
                if isinstance(widget, translator.tk.Button)}

    def test_style_editor_previews_and_cancels_or_saves(self):
        self.addCleanup(translator.set_glass_style, translator.get_glass_style())
        root = make_root(self)

        def blank(x, y, width, height, exclude_hwnd=None):
            return translator.Image.new('RGB', (width, height))

        with patch.object(translator, 'capture_backdrop', side_effect=blank), \
             patch.object(translator, 'glass_supported', return_value=True):
            editor = translator.open_style_editor(root)
            self.assertIs(translator.open_style_editor(root), editor)
            self.assertTrue(editor.preview.popup.winfo_exists())
            self._editor_buttons(editor)['深色'].invoke()
            self.assertEqual(translator.GLASS_TEXT_MODE, 'light')
            self._editor_buttons(editor)['取消'].invoke()
            self.assertEqual(translator.GLASS_TEXT_MODE, 'auto')
            self.assertIsNone(translator._style_editor)

            editor = translator.open_style_editor(root)
            self._editor_buttons(editor)['磨砂'].invoke()
            self._editor_buttons(editor)['保存'].invoke()
        self.assertFalse(editor.winfo_exists())
        self.assertIn('blur = 16', self.config.read_text(encoding='utf-8'))

    def test_source_directory(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(
                translator._app_dir(),
                os.path.dirname(os.path.abspath(translator.__file__)),
            )

    def test_executable_directory(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(
                translator._app_dir(), os.path.dirname(sys.executable),
            )


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class TranslationTests(unittest.TestCase):
    def setUp(self):
        api_patch = patch.object(translator, 'API_KEY', 'example.test-only')
        api_patch.start()
        self.addCleanup(api_patch.stop)
        request_patch = patch.object(translator.requests, 'post')
        self.post = request_patch.start()
        self.addCleanup(request_patch.stop)
        self.response = Mock()
        self.response.json.return_value = {
            'choices': [{'message': {'content': '  translated text  '}}],
        }
        self.post.return_value = self.response

    def test_english_request(self):
        self.assertEqual(translator.translate('Hello'), 'translated text')
        self.response.raise_for_status.assert_called_once_with()
        args, kwargs = self.post.call_args
        self.assertEqual(args[0], 'https://open.bigmodel.cn/api/paas/v4/chat/completions')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer example.test-only')
        self.assertEqual(kwargs['json']['model'], translator.MODEL)
        self.assertIn('\u82f1\u6587\u7ffb\u8bd1\u6210\u4e2d\u6587', kwargs['json']['messages'][0]['content'])
        self.assertEqual(kwargs['timeout'], 30)

    def test_chinese_request(self):
        translator.translate('\u4f60\u597d')
        prompt = self.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('\u4e2d\u6587\u7ffb\u8bd1\u6210\u82f1\u6587', prompt)

    def test_network_failure(self):
        self.post.side_effect = translator.requests.Timeout('test timeout')
        self.assertEqual(translator.translate('Hello'), '[Error: test timeout]')

    def test_http_failure(self):
        self.response.raise_for_status.side_effect = translator.requests.HTTPError('test HTTP error')
        self.assertEqual(translator.translate('Hello'), '[Error: test HTTP error]')


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class ShortcutTests(unittest.TestCase):
    def setUp(self):
        state_patch = patch.multiple(
            translator,
            _simulating=False,
            _ctrl_pressed=False,
            _ctrl_press_time=0.0,
            _last_ctrl_click_t=0.0,
            _other_key_in_ctrl=False,
        )
        state_patch.start()
        self.addCleanup(state_patch.stop)
        thread_patch = patch.object(translator.threading, 'Thread')
        self.thread = thread_patch.start()
        self.addCleanup(thread_patch.stop)

    def test_double_ctrl_starts_worker(self):
        with patch.object(translator.time, 'time', return_value=100.0):
            for _ in range(2):
                translator.on_key_press(translator.pynkb.Key.ctrl_l)
                translator.on_key_release(translator.pynkb.Key.ctrl_l)
        self.thread.assert_called_once_with(target=translator.translation_worker, daemon=True)
        self.thread.return_value.start.assert_called_once_with()

    def test_ctrl_c_does_not_start_worker(self):
        with patch.object(translator.time, 'time', return_value=100.0):
            translator.on_key_press(translator.pynkb.Key.ctrl_l)
            translator.on_key_press(translator.pynkb.KeyCode.from_char('c'))
            translator.on_key_release(translator.pynkb.Key.ctrl_l)
        self.thread.assert_not_called()

    def test_long_hold_does_not_start_worker(self):
        with patch.object(translator.time, 'time', side_effect=[100.0, 101.0]):
            translator.on_key_press(translator.pynkb.Key.ctrl_l)
            translator.on_key_release(translator.pynkb.Key.ctrl_l)
        self.thread.assert_not_called()

    def test_simulated_input_is_ignored(self):
        with patch.object(translator, '_simulating', True):
            translator.on_key_press(translator.pynkb.Key.ctrl_l)
            translator.on_key_release(translator.pynkb.Key.ctrl_l)
        self.assertFalse(translator._ctrl_pressed)
        self.thread.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class PopupTests(unittest.TestCase):
    def test_mouse_drag_bounds_are_used_before_ui_automation(self):
        tracker = translator.MouseSelectionTracker()
        with patch.object(translator.time, 'monotonic', return_value=100.0), \
             patch.object(translator, 'get_foreground_window', return_value=42):
            tracker.on_click(650, 250, translator.pynmouse.Button.left, True)
            tracker.on_click(110, 165, translator.pynmouse.Button.left, False)
            with patch.object(translator, 'get_selection_bounds') as uia:
                self.assertEqual(translator.resolve_selection_bounds(tracker),
                                 (110, 165, 650, 250))
                uia.assert_not_called()

    def test_mouse_drag_is_discarded_after_other_click_or_window_change(self):
        tracker = translator.MouseSelectionTracker()
        with patch.object(translator.time, 'monotonic', return_value=100.0), \
             patch.object(translator, 'get_foreground_window', return_value=42):
            tracker.on_click(110, 165, translator.pynmouse.Button.left, True)
            tracker.on_click(650, 250, translator.pynmouse.Button.left, False)
        self.assertIsNone(tracker.get_bounds(100.1, 43))
        with patch.object(translator.time, 'monotonic', return_value=101.0), \
             patch.object(translator, 'get_foreground_window', return_value=42):
            tracker.on_click(110, 165, translator.pynmouse.Button.left, True)
            tracker.on_click(650, 250, translator.pynmouse.Button.left, False)
            tracker.on_click(700, 400, translator.pynmouse.Button.left, True)
            tracker.on_click(700, 400, translator.pynmouse.Button.left, False)
        self.assertIsNone(tracker.get_bounds(101.1, 42))

    def test_keyboard_selection_uses_ui_automation_when_no_mouse_drag(self):
        tracker = translator.MouseSelectionTracker()
        with patch.object(translator, 'get_selection_bounds',
                          return_value=(50, 100, 300, 140)) as uia:
            self.assertEqual(translator.resolve_selection_bounds(tracker),
                             (50, 100, 300, 140))
            uia.assert_called_once_with()

    def test_selection_bounds_cover_every_selected_line(self):
        selected = Mock()
        selected.GetText.return_value = 'x'
        selected.GetBoundingRectangles.return_value = [
            SimpleNamespace(left=50, top=110, right=239, bottom=142),
            SimpleNamespace(left=90, top=270, right=503, bottom=366),
        ]
        control = Mock()
        control.GetPattern.return_value.GetSelection.return_value = [selected]
        with patch('uiautomation.GetFocusedControl', return_value=control):
            self.assertEqual(translator.get_selection_bounds(), (50, 110, 503, 366))

    def test_selection_bounds_use_visible_range_when_text_is_unavailable(self):
        selected = Mock()
        selected.GetText.return_value = ''
        selected.GetBoundingRectangles.return_value = [
            SimpleNamespace(left=70, top=160, right=600, bottom=188),
        ]
        control = Mock()
        control.GetPattern.return_value.GetSelection.return_value = [selected]
        with patch('uiautomation.GetFocusedControl', return_value=control):
            self.assertEqual(translator.get_selection_bounds(), (70, 160, 600, 188))

    def test_selection_bounds_find_text_pattern_on_parent_document(self):
        selected = Mock()
        selected.GetBoundingRectangles.return_value = [
            SimpleNamespace(left=76, top=165, right=1100, bottom=251),
        ]
        document = Mock()
        document.ControlTypeName = 'DocumentControl'
        document.GetPattern.return_value.GetSelection.return_value = [selected]
        outer_group = Mock()
        outer_group.ControlTypeName = 'GroupControl'
        outer_group.GetPattern.return_value = None
        outer_group.GetParentControl.return_value = document
        focused_group = Mock()
        focused_group.ControlTypeName = 'GroupControl'
        focused_group.GetPattern.return_value = None
        focused_group.GetParentControl.return_value = outer_group
        with patch('uiautomation.GetFocusedControl', return_value=focused_group):
            self.assertEqual(translator.get_selection_bounds(), (76, 165, 1100, 251))

    def test_selection_diagnostics_record_missing_text_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / 'selection.log'
            control = Mock()
            control.ControlTypeName = 'DocumentControl'
            control.GetPattern.return_value = None
            control.GetParentControl.return_value = None
            with patch.dict(os.environ, {
                'TRANSLATOR_SELECTION_DIAGNOSTICS': str(log_path),
            }), patch('uiautomation.GetFocusedControl', return_value=control):
                self.assertIsNone(translator.get_selection_bounds())
            self.assertIn('no_text_pattern_or_selection',
                          log_path.read_text(encoding='utf-8'))

    def test_popup_position_is_below_right_of_selection(self):
        self.assertEqual(
            translator.choose_popup_position((50, 110, 503, 366), 370, 300,
                                             (0, 0, 2048, 1112)),
            (515, 378),
        )

    def test_popup_position_flips_at_screen_edges(self):
        self.assertEqual(
            translator.choose_popup_position((1700, 900, 1950, 1050), 370, 300,
                                             (0, 0, 2048, 1112)),
            (1318, 588),
        )

    def test_popup_repositions_after_translation_expands(self):
        root = make_root(self)
        manager = translator.PopupManager(root)
        with patch.object(translator, 'get_work_area', return_value=(0, 0, 1000, 700)):
            manager._show('original', '翻译中…', 0, 0,
                          selection_bounds=(50, 500, 300, 520))
            popup = manager.popup
            self.assertEqual((popup.winfo_rootx(), popup.winfo_rooty()),
                             (312, 532))

            manager._set_result('translated line\n' * 10)
            popup.update_idletasks()
            self.assertEqual(popup.winfo_rootx(), 312)
            self.assertLess(popup.winfo_rooty() + popup.winfo_height(), 500)

    def test_popup_without_selection_bounds_stays_near_mouse(self):
        root = make_root(self)
        manager = translator.PopupManager(root)
        with patch.object(translator, 'get_work_area', return_value=(0, 0, 2048, 1112)):
            manager._show('original', '翻译中…', 570, 263)
            popup = manager.popup
            self.assertEqual((popup.winfo_rootx(), popup.winfo_rooty()),
                             (582, 275))


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class GlassTests(unittest.TestCase):
    def test_highlight_matches_size_and_keeps_center_clear(self):
        image = translator.render_glass_highlight(370, 160)
        self.assertEqual((image.mode, image.size), ('RGB', (370, 160)))
        self.assertEqual(image.getpixel((185, 80)), (0, 0, 0))
        self.assertGreater(image.convert('L').getextrema()[1], 100)

    def test_highlight_glints_at_top_left_more_than_top_right(self):
        image = translator.render_glass_highlight(370, 160).convert('L')
        top_left = max(image.getpixel((40, y)) for y in range(5))
        top_right = max(image.getpixel((330, y)) for y in range(5))
        self.assertGreater(top_left, top_right * 1.5)

    def test_sheen_stays_inside_top_padding(self):
        image = translator.render_glass_highlight(370, 160).convert('L')
        self.assertGreater(image.getpixel((185, 4)), 0)
        self.assertEqual(
            [image.getpixel((185, y))
             for y in range(translator.GLASS_SHEEN_HEIGHT, 160 - 6)],
            [0] * (160 - 6 - translator.GLASS_SHEEN_HEIGHT))

    def test_glass_unsupported_when_transparency_disabled(self):
        with patch.object(translator.winreg, 'OpenKey'), \
             patch.object(translator.winreg, 'QueryValueEx', return_value=(0, 4)):
            self.assertFalse(translator.glass_supported())
        with patch.object(translator.winreg, 'OpenKey'), \
             patch.object(translator.winreg, 'QueryValueEx', return_value=(1, 4)):
            self.assertTrue(translator.glass_supported())

    def test_sheen_scales_with_display(self):
        image = translator.render_glass_highlight(560, 190, 1.5).convert('L')
        sheen_end = round(translator.GLASS_SHEEN_HEIGHT * 1.5)
        self.assertGreater(image.getpixel((280, sheen_end - 4)), 0)
        self.assertEqual(
            [image.getpixel((280, y)) for y in range(sheen_end, 190 - 9)],
            [0] * (190 - 9 - sheen_end))

    def test_dpi_awareness_prefers_per_monitor(self):
        windll = Mock()
        with patch.object(translator.ctypes, 'windll', windll):
            translator.enable_dpi_awareness()
        windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
        windll.user32.SetProcessDPIAware.assert_not_called()

    def test_dpi_awareness_falls_back_to_system_aware(self):
        windll = Mock()
        windll.shcore.SetProcessDpiAwareness.side_effect = OSError
        with patch.object(translator.ctypes, 'windll', windll):
            translator.enable_dpi_awareness()
        windll.user32.SetProcessDPIAware.assert_called_once_with()

    def test_wrap_keeps_english_words_and_breaks_cjk_anywhere(self):
        font = translator._glass_font(15)
        self.assertEqual(
            translator.wrap_text('hello world', font, font.getlength('hello wor')),
            ['hello', 'world'])
        self.assertEqual(
            translator.wrap_text('一二三四五六', font, font.getlength('一二三')),
            ['一二三', '四五六'])
        self.assertEqual(translator.wrap_text('a\nb', font, 200), ['a', 'b'])

    def test_wrap_splits_words_longer_than_a_line(self):
        font = translator._glass_font(15)
        width = font.getlength('abcde')
        lines = translator.wrap_text('abcdefghijkl', font, width)
        self.assertGreater(len(lines), 1)
        self.assertEqual(''.join(lines), 'abcdefghijkl')
        self.assertTrue(all(font.getlength(line) <= width for line in lines))

    def setUp(self):
        self.addCleanup(translator.set_glass_style, translator.get_glass_style())

    def test_glass_popup_image_is_rounded_and_opaque_inside(self):
        image, layout = translator.render_glass_popup('original', '译文', 1.0,
                                                      speak_state='ready')
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.width, translator.GLASS_WIDTH)
        alpha = image.getchannel('A')
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertGreaterEqual(alpha.getpixel((image.width // 2, 3)),
                                translator.GLASS_SOLID_ALPHA)
        copy_box, speak_box = layout['copy'], layout['speak']
        self.assertLessEqual(copy_box[2], image.width)
        self.assertLessEqual(copy_box[3], image.height)
        self.assertLess(speak_box[2], copy_box[0] + 1)

    def test_glass_popup_scales_and_limits_long_translations(self):
        small, _ = translator.render_glass_popup('o', 'line\n' * 3, 1.0)
        large, _ = translator.render_glass_popup('o', 'line\n' * 3, 1.5)
        self.assertEqual(large.width, round(translator.GLASS_WIDTH * 1.5))
        limit, _ = translator.render_glass_popup(
            'o', 'line\n' * translator.GLASS_MAX_LINES, 1.0)
        huge, _ = translator.render_glass_popup('o', 'line\n' * 100, 1.0)
        self.assertEqual(huge.height, limit.height)
        self.assertGreater(limit.height, small.height)

    def test_text_color_follows_background_brightness(self):
        box = (0, 0, 50, 50)
        light = translator.Image.new('RGBA', (50, 50), (250, 250, 250, 255))
        dark = translator.Image.new('RGBA', (50, 50), (20, 20, 30, 255))
        dark_ink = translator._hex_rgb(translator.GLASS_TEXT)
        light_ink = translator._hex_rgb(translator.GLASS_TEXT_LIGHT)
        self.assertEqual(translator._glass_ink(light, box), (dark_ink, (255, 255, 255)))
        self.assertEqual(translator._glass_ink(dark, box), (light_ink, (0, 0, 0)))
        translator.set_glass_style({'text_mode': 'dark'})
        self.assertEqual(translator._glass_ink(dark, box)[0], dark_ink)

    def test_edges_refract_what_is_outside_the_glass(self):
        translator.set_glass_style({'blur': 0, 'tint_alpha': 0, 'saturation': 100,
                                    'brightness': 100, 'refraction': 10, 'rim': 0,
                                    'sheen': 0, 'edge': 0})
        margin = translator.glass_backdrop_margin()
        backdrop = translator.Image.new('RGB', (200 + 2 * margin, 100 + 2 * margin), 'red')
        backdrop.paste((0, 0, 255), (margin, margin, margin + 200, margin + 100))
        glass = translator.render_glass_background(backdrop, (200, 100))
        self.assertEqual(glass.getpixel((100, 50))[:3], (0, 0, 255))
        self.assertGreater(glass.getpixel((1, 50))[0], 200)
        translator.set_glass_style({'refraction': 0})
        flat = translator.render_glass_background(backdrop, (200, 100))
        self.assertEqual(flat.getpixel((1, 50))[:3], (0, 0, 255))

    def test_style_values_are_validated(self):
        translator.set_glass_style({'tint_color': '#ABCDEF', 'tint_alpha': '999',
                                    'blur': 'x', 'text_mode': 'neon', 'text_dark': 'red'})
        style = translator.get_glass_style()
        self.assertEqual(style['tint_color'], '#abcdef')
        self.assertEqual(style['tint_alpha'], 255)
        self.assertEqual(style['blur'], translator.GLASS_DEFAULT_STYLE['blur'])
        self.assertEqual(style['text_mode'], translator.GLASS_DEFAULT_STYLE['text_mode'])
        self.assertEqual(style['text_dark'], translator.GLASS_DEFAULT_STYLE['text_dark'])

    def _show_popup(self, glass, scale=1.0, backdrop='#3060c0'):
        root = make_root(self)
        with patch.object(translator, 'ui_scale', return_value=scale):
            manager = translator.PopupManager(root, poll=False)
        self.captures = []

        def capture(x, y, width, height, exclude_hwnd=None):
            self.captures.append(exclude_hwnd)
            if backdrop is None:
                return None
            return translator.Image.new('RGB', (width, height), self.backdrop_color)

        self.backdrop_color = backdrop
        capture_patch = patch.object(translator, 'capture_backdrop', side_effect=capture)
        capture_patch.start()
        self.addCleanup(capture_patch.stop)
        with patch.object(translator, 'glass_supported', return_value=glass):
            manager._show('original', '翻译中…', 100, 100)
        return manager

    @staticmethod
    def _click(manager, box, handler):
        x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        px, py = manager._glass_pos
        return handler(SimpleNamespace(x=x, y=y, x_root=px + x, y_root=py + y))

    def test_glass_popup_shows_the_captured_backdrop(self):
        manager = self._show_popup(glass=True)
        manager.popup.update_idletasks()
        self.assertEqual((manager.popup.winfo_width(), manager.popup.winfo_height()),
                         manager._glass_image.size)
        self.assertEqual(self.captures, [None])
        center = manager._glass_image.getpixel((manager._glass_image.width // 2, 5))
        self.assertGreater(center[2], center[0])
        self.assertEqual(center[3], 255)

    def test_glass_refreshes_only_when_the_backdrop_changes(self):
        manager = self._show_popup(glass=True)
        self.assertFalse(manager._glass_capture())
        self.assertEqual(self.captures[-1], manager._glass_hwnd)
        self.backdrop_color = '#c03030'
        self.assertTrue(manager._glass_capture())

    def test_glass_popup_turns_solid_when_capture_fails(self):
        manager = self._show_popup(glass=True, backdrop=None)
        alpha = manager._glass_image.getchannel('A')
        self.assertEqual(alpha.getpixel((alpha.width // 2, alpha.height // 2)),
                         translator.GLASS_SOLID_ALPHA)

    def test_glass_copy_button_copies_whole_translation(self):
        manager = self._show_popup(glass=True)
        self.assertIsNone(manager._glass_hit(*manager._glass_layout['copy'][:2]))
        manager._set_result('完整的译文')
        box = manager._glass_layout['copy']
        with patch.object(translator.pyperclip, 'copy') as copy:
            self._click(manager, box, manager._glass_press)
            self._click(manager, box, manager._glass_release)
        copy.assert_called_once_with('完整的译文')
        self.assertEqual(manager._copy_state, 'done')

    def test_glass_speak_button_is_enabled_after_translation(self):
        manager = self._show_popup(glass=True)
        box = manager._glass_layout['speak']
        self.assertIsNone(manager._glass_hit(box[0] + 2, box[1] + 2))
        manager._set_result('译文')
        with patch.object(translator, 'speak_text') as speak:
            self._click(manager, manager._glass_layout['speak'], manager._glass_press)
            self._click(manager, manager._glass_layout['speak'], manager._glass_release)
        speak.assert_called_once()
        self.assertEqual(speak.call_args.args[0], 'original')
        self.assertEqual(manager._speak_state, 'busy')

    def test_glass_popup_drags_from_blank_area(self):
        manager = self._show_popup(glass=True)
        start = manager._glass_pos
        with patch.object(translator, 'get_work_area', return_value=(0, 0, 4000, 3000)):
            manager._glass_press(SimpleNamespace(x=5, y=5, x_root=start[0] + 5,
                                                 y_root=start[1] + 5))
            manager._glass_drag(SimpleNamespace(x=5, y=5, x_root=start[0] + 105,
                                                y_root=start[1] + 45))
        self.assertTrue(manager._popup_dragged)
        self.assertEqual(manager._glass_pos, (start[0] + 100, start[1] + 40))

    def test_classic_popup_spacing_follows_display_scale(self):
        manager = self._show_popup(glass=False, scale=1.5)
        frame = manager.popup.winfo_children()[0]
        self.assertEqual(int(frame.cget('padx')), 24)
        self.assertEqual(int(frame.cget('pady')), 21)
        original = frame.winfo_children()[0]
        self.assertEqual(int(original.cget('wraplength')), 510)

    def test_popup_falls_back_to_opaque_theme_without_glass(self):
        manager = self._show_popup(glass=False)
        self.assertEqual(manager.popup.cget('bg'), translator.BG)
        self.assertAlmostEqual(float(manager.popup.attributes('-alpha')), 0.94, places=2)


if __name__ == '__main__':
    unittest.main()
