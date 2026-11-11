# Repository Guidelines

## Project Structure & Module Organization

This is a Windows 10/11 desktop translator requiring Python 3.11+ with Tkinter. `translator.py` contains configuration, BigModel requests, keyboard listeners, the Tkinter popup, tray controls, and speech playback. The trigger is configurable through the tray's hotkey editor and stored as `[settings] hotkey`: `double-ctrl` keeps the double-tap gesture, while values such as `ctrl+shift+t` or `f2` are matched by `HotkeyMatcher`. The tray icon is generated in code; `assets/fonts/` only carries the ZCOOL KuaiLe font used by the settings dialog. The glass popup is a layered window drawn with Pillow from a capture of the screen behind it; its style, including the original and translation font sizes, lives in the `GLASS_*` constants, can be changed from the tray's appearance editor, and is saved in the `[glass]` section of `translator_config.ini`. `tools/glass_tuner.py` opens that editor over synthetic test backdrops.

`tests/test_translator.py` covers language detection, configuration, translation requests, and Ctrl gestures. Root-level batch scripts handle setup, launching, startup registration, and packaging. `build.bat` holds the PyInstaller options; the generated spec lives in `build-public\` and is not tracked. Runtime dependencies are pinned in `requirements.txt`; `requirements-dev.txt` adds packaging tools.

## Build, Test, and Development Commands

Run these commands from the repository root in PowerShell:

```powershell
.\setup.bat
.\start.bat
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\build.bat
```

- `setup.bat` creates `.venv` and installs runtime dependencies.
- `start.bat` launches the application with console diagnostics.
- `unittest discover` runs the unit suite; `pip check` checks dependency compatibility.
- `build.bat` installs development dependencies and produces `releases\translator.exe`, using `build-public\` for build caches.

Use `debug_setup.bat` to diagnose Python or dependency problems.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Follow surrounding quote styles and existing type annotations. Keep changes focused and preserve the source's section organization. No formatter or linter is currently configured.

## Testing Guidelines

Use standard-library `unittest` and `unittest.mock`. Name test files `test_*.py` and methods `test_<behavior>`. Add regression tests for changed behavior; no numeric coverage threshold is configured.

Run tests on Windows; they are skipped on other platforms. Mock network requests, use temporary configuration files, and avoid real credentials or startup-registry changes. Manually verify affected selection, popup, clipboard, tray, and speech interactions; unit tests do not cover those integrations.

## Commit & Pull Request Guidelines

History starts with `Initial open-source release of Double Ctrl Translator` and has grown since; use concise, descriptive commit subjects; no enforced prefix convention exists.

Keep each PR focused. Explain what changed, why, and how it was verified; link relevant issues and include screenshots for UI changes. Update dependency files and installation documentation together. Validate `build.bat` when changing packaging. See `CONTRIBUTING.md` for contribution details.

## Security & Configuration

Use `translator_config.ini.example` as the configuration template. Never commit the real `translator_config.ini`, credentials, private selected text, `.venv`, or build outputs. Keys are stored locally in plaintext. Review `git diff --cached` before committing, and redact sensitive information from screenshots and logs.
