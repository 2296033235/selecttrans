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
        root = translator.tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
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
        root = translator.tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        manager = translator.PopupManager(root)
        with patch.object(translator, 'get_work_area', return_value=(0, 0, 2048, 1112)):
            manager._show('original', '翻译中…', 570, 263)
            popup = manager.popup
            self.assertEqual((popup.winfo_rootx(), popup.winfo_rooty()),
                             (582, 275))


if __name__ == '__main__':
    unittest.main()
