# Repository Guidelines

## Project Structure & Module Organization

This is a Windows 10/11 desktop translator requiring Python 3.11+ with Tkinter. `translator.py` contains configuration, BigModel requests, keyboard listeners, the Tkinter popup, tray controls, and speech playback. The tray icon is generated in code; there is no separate assets directory.

`tests/test_translator.py` covers language detection, configuration, translation requests, and Ctrl gestures. Root-level batch scripts handle setup, launching, startup registration, and packaging. `translator.spec` configures PyInstaller. Runtime dependencies are pinned in `requirements.txt`; `requirements-dev.txt` adds packaging tools.

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

History currently contains one commit: `Initial open-source release of Double Ctrl Translator`. Use concise, descriptive commit subjects; no enforced prefix convention exists.

Keep each PR focused. Explain what changed, why, and how it was verified; link relevant issues and include screenshots for UI changes. Update dependency files and installation documentation together. Validate `build.bat` when changing packaging. See `CONTRIBUTING.md` for contribution details.

## Security & Configuration

Use `translator_config.ini.example` as the configuration template. Never commit the real `translator_config.ini`, credentials, private selected text, `.venv`, or build outputs. Keys are stored locally in plaintext. Review `git diff --cached` before committing, and redact sensitive information from screenshots and logs.
