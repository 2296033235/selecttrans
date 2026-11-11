import os
from pathlib import Path
import re
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

    def test_api_settings_round_trip_and_default_to_empty(self):
        self.assertEqual(translator.load_api_settings(),
                         {'api_key': '', 'base_url': '', 'model': ''})
        translator.save_api_settings('sk-test-only', 'https://api.example.com/v1', 'my-model')
        self.assertEqual(translator.load_api_settings(),
                         {'api_key': 'sk-test-only', 'base_url': 'https://api.example.com/v1',
                          'model': 'my-model'})
        translator.save_api_key('example.test-only')
        self.assertEqual(translator.load_api_settings()['model'], 'my-model')

    def test_old_config_without_endpoint_uses_defaults(self):
        self.config.write_text('[settings]\napi_key = example.test-only\n', encoding='utf-8')
        self.assertEqual(translator.load_api_settings(),
                         {'api_key': 'example.test-only', 'base_url': '', 'model': ''})

    def test_settings_dialog_returns_custom_endpoint_and_model(self):
        root = make_root(self)

        def widgets(widget, kind):
            for child in widget.winfo_children():
                if isinstance(child, kind):
                    yield child
                yield from widgets(child, kind)

        def fill():
            dialog = root.winfo_children()[-1]
            dialog.actions['confirm']()
            self.assertTrue(dialog.winfo_exists())       # 空 Key 不能保存
            dialog.actions['toggle_more']()
            key, base, model = widgets(dialog, translator.tk.Entry)
            self.assertTrue(base.winfo_ismapped())
            for widget, value in ((key, 'sk-test-only'),
                                  (base, 'https://api.example.com/v1/'),
                                  (model, 'my-model')):
                widget.delete(0, 'end')
                widget.insert(0, value)
            dialog.actions['confirm']()

        root.after(200, fill)
        self.assertEqual(translator.show_settings_dialog(root),
                         {'api_key': 'sk-test-only', 'base_url': 'https://api.example.com/v1',
                          'model': 'my-model'})

    def test_settings_dialog_cancel_returns_nothing(self):
        root = make_root(self)
        root.after(200, lambda: root.winfo_children()[-1].actions['cancel']())
        self.assertIsNone(translator.show_settings_dialog(root, {'api_key': 'example.test-only'}))

    def test_bundled_crayon_font_is_available(self):
        self.assertTrue(os.path.exists(translator.CRAYON_FONT_FILE))
        self.assertEqual(translator.crayon_font_family(), 'ZCOOL KuaiLe')
        art = translator.CrayonDrawing(120, 80)
        art.box((10, 10, 110, 50), translator.CRAYON_BLUE, scribble='#c8ecb5')
        self.assertEqual(art.image.size, (120, 80))
        self.assertNotEqual(art.image.getpixel((60, 30)), art.image.getpixel((2, 78)))

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

    def test_custom_endpoint_and_model(self):
        with patch.multiple(translator, API_BASE_URL='https://api.example.com/v1/',
                            API_MODEL='my-model'):
            translator.translate('Hello')
        args, kwargs = self.post.call_args
        self.assertEqual(args[0], 'https://api.example.com/v1/chat/completions')
        self.assertEqual(kwargs['json']['model'], 'my-model')

    def test_full_endpoint_url_is_used_as_is(self):
        url = 'https://api.example.com/openai/chat/completions'
        self.assertEqual(translator.chat_completions_url(url), url)
        self.assertEqual(translator.chat_completions_url(''),
                         translator.DEFAULT_BASE_URL + '/chat/completions')

    def test_settings_validation(self):
        validate = translator.validate_api_settings
        self.assertEqual(validate('', '', '')[0], None)
        self.assertEqual(validate('nodot-key-123', '', '')[0], None)
        self.assertEqual(validate('sk-abc', 'ftp://x', '')[0], None)
        self.assertEqual(
            validate(' sk-abc ', 'https://api.deepseek.com/', 'deepseek-chat')[0],
            {'api_key': 'sk-abc', 'base_url': 'https://api.deepseek.com',
             'model': 'deepseek-chat'})
        self.assertEqual(
            validate('example.test-only', translator.DEFAULT_BASE_URL, translator.MODEL)[0],
            {'api_key': 'example.test-only', 'base_url': '', 'model': ''})

    def test_network_failure(self):
        self.post.side_effect = translator.requests.Timeout('test timeout')
        self.assertEqual(translator.translate('Hello'), '[Error: test timeout]')

    def test_http_failure(self):
        self.response.raise_for_status.side_effect = translator.requests.HTTPError('test HTTP error')
        self.assertEqual(translator.translate('Hello'), '[Error: test HTTP error]')


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class ShortcutTests(unittest.TestCase):
    def setUp(self):
        state_patch = patch.multiple(translator, _simulating=False)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.addCleanup(translator.apply_hotkey, translator.DEFAULT_HOTKEY)
        translator.apply_hotkey(translator.DEFAULT_HOTKEY)
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
        self.assertFalse(translator._hotkey.pressed)
        self.thread.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class HotkeyTests(unittest.TestCase):
    """快捷键的解析、匹配与配置持久化。"""

    def setUp(self):
        self.addCleanup(translator.apply_hotkey, translator.DEFAULT_HOTKEY)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / 'translator_config.ini'
        config_patch = patch.object(translator, 'CONFIG_FILE', str(self.config))
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_missing_setting_defaults_to_double_ctrl(self):
        self.assertEqual(translator.load_hotkey(), 'double-ctrl')

    def test_parse_double_modifier(self):
        self.assertEqual(translator.parse_hotkey('Double-Alt'),
                         {'mode': 'double', 'key': 'alt'})

    def test_parse_combo(self):
        self.assertEqual(translator.parse_hotkey('Ctrl + Shift + T'),
                         {'mode': 'combo', 'keys': frozenset({'ctrl', 'shift', 't'})})

    def test_parse_single_key(self):
        self.assertEqual(translator.parse_hotkey('F2'),
                         {'mode': 'combo', 'keys': frozenset({'f2'})})

    def test_unparsable_text_falls_back(self):
        self.assertEqual(translator.parse_hotkey('+++'),
                         {'mode': 'double', 'key': 'ctrl'})

    def test_text_round_trip(self):
        for text in ('double-ctrl', 'double-shift', 'ctrl+c', 'ctrl+shift+t', 'f2'):
            self.assertEqual(translator.hotkey_text(translator.parse_hotkey(text)), text)

    def test_display_text_is_readable(self):
        self.assertEqual(translator.format_hotkey(translator.parse_hotkey('ctrl+c')),
                         'Ctrl+C')
        self.assertEqual(translator.format_hotkey(translator.parse_hotkey('double-ctrl')),
                         '双击 Ctrl')

    def test_key_names_are_normalized(self):
        key = translator.pynkb
        self.assertEqual(translator.key_name(key.Key.ctrl_r), 'ctrl')
        self.assertEqual(translator.key_name(key.KeyCode.from_char('C')), 'c')
        self.assertEqual(translator.key_name(key.KeyCode(vk=67, char='\x03')), 'c')
        self.assertEqual(translator.key_name(key.Key.f2), 'f2')

    def test_combo_triggers_once_per_press(self):
        matcher = translator.HotkeyMatcher(translator.parse_hotkey('ctrl+c'))
        self.assertFalse(matcher.press('ctrl'))
        self.assertTrue(matcher.press('c'))
        self.assertFalse(matcher.press('c'))       # 按住不放不重复触发
        matcher.release('c')
        matcher.release('ctrl')
        self.assertFalse(matcher.press('c'))       # 少一个键不触发
        self.assertTrue(matcher.press('ctrl'))

    def test_combo_needs_every_key(self):
        matcher = translator.HotkeyMatcher(translator.parse_hotkey('ctrl+shift+t'))
        matcher.press('ctrl')
        matcher.press('shift')
        self.assertFalse(matcher.press('x'))

    def test_double_mode_still_works(self):
        matcher = translator.HotkeyMatcher()
        with patch.object(translator.time, 'time', return_value=100.0):
            matcher.press('ctrl')
            self.assertFalse(matcher.release('ctrl'))
            matcher.press('ctrl')
            self.assertTrue(matcher.release('ctrl'))

    def test_double_mode_ignores_taps_with_other_keys(self):
        matcher = translator.HotkeyMatcher()
        with patch.object(translator.time, 'time', return_value=100.0):
            matcher.press('ctrl')
            matcher.press('c')
            matcher.release('c')
            self.assertFalse(matcher.release('ctrl'))
            matcher.press('ctrl')
            self.assertFalse(matcher.release('ctrl'))

    def test_hotkey_round_trip_in_config(self):
        translator.save_hotkey('ctrl+shift+t')
        self.assertEqual(translator.load_hotkey(), 'ctrl+shift+t')
        text = self.config.read_text(encoding='utf-8')
        self.assertIn('hotkey', text)
        self.assertIn('ctrl+shift+t', text)

    def test_apply_hotkey_switches_mode(self):
        translator.apply_hotkey('ctrl+c')
        self.assertEqual(translator._hotkey.spec['mode'], 'combo')
        translator.apply_hotkey(translator.DEFAULT_HOTKEY)
        self.assertEqual(translator._hotkey.spec['mode'], 'double')


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


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only application')
class FontSizeTests(unittest.TestCase):
    """字号设置：保存、范围、渲染和经典主题都要跟着变。"""

    def setUp(self):
        self.addCleanup(translator.set_glass_style, translator.get_glass_style())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / 'translator_config.ini'
        config_patch = patch.object(translator, 'CONFIG_FILE', str(self.config))
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_font_size_round_trip(self):
        translator.set_glass_style({'font_orig': 18, 'font_text': 22})
        translator.save_glass_style(translator.get_glass_style())
        translator.set_glass_style(translator.GLASS_DEFAULT_STYLE)
        translator.load_glass_style()
        self.assertEqual(translator.GLASS_FONT_ORIG, 18)
        self.assertEqual(translator.GLASS_FONT_TEXT, 22)

    def test_font_size_is_clamped_to_its_range(self):
        translator.set_glass_style({'font_orig': '999', 'font_text': '1'})
        self.assertEqual(translator.GLASS_FONT_ORIG, 28)
        self.assertEqual(translator.GLASS_FONT_TEXT, 10)

    def test_metrics_follow_the_configured_font_size(self):
        translator.set_glass_style({'font_orig': 12, 'font_text': 15})
        small = translator._glass_metrics('原文', '译文', 1.0)
        translator.set_glass_style({'font_orig': 20, 'font_text': 24})
        large = translator._glass_metrics('原文', '译文', 1.0)
        self.assertEqual(small['orig_font'].size, 12)
        self.assertEqual(large['orig_font'].size, 20)
        self.assertEqual(large['text_font'].size, 24)
        self.assertGreater(large['height'], small['height'])

    def test_old_config_without_font_size_keeps_the_defaults(self):
        self.config.write_text('[glass]\nblur = 12\n', encoding='utf-8')
        translator.set_glass_style(translator.GLASS_DEFAULT_STYLE)
        translator.load_glass_style()
        self.assertEqual(translator.GLASS_FONT_ORIG,
                         translator.GLASS_DEFAULT_STYLE['font_orig'])
        self.assertEqual(translator.GLASS_BLUR, 12)

    def test_classic_popup_follows_the_configured_font_size(self):
        root = make_root(self)
        translator.set_glass_style({'font_orig': 20, 'font_text': 26})
        manager = translator.PopupManager(root, poll=False)
        with patch.object(translator, 'glass_supported', return_value=False):
            manager._show('original', '翻译中…', 100, 100)
        frame = manager.popup.winfo_children()[0]
        original = frame.winfo_children()[0]
        result = frame.winfo_children()[2]
        self.assertEqual(int(re.search(r'(\d+)\s*\)?$', original.cget('font')).group(1)), 17)
        self.assertEqual(int(re.search(r'(\d+)\s*\)?$', result.cget('font')).group(1)), 22)

    def test_tray_menu_offers_the_appearance_editor(self):
        root = make_root(self)
        with patch.object(translator.pystray, 'Icon') as icon:
            translator.setup_tray(root)
        menu = icon.call_args.args[3]
        texts = [item.text for item in menu if isinstance(getattr(item, 'text', None), str)]
        self.assertIn('外观设置（字体 / 颜色）', texts)
        self.assertIn('接口设置（API Key / 模型）', texts)


if __name__ == '__main__':
    unittest.main()
