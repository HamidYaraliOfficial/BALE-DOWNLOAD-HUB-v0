# Developer guide

## Setup
```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.main                                   # run
QT_QPA_PLATFORM=offscreen python -m pytest -q        # tests (≈70 s; UI tests are headless)
python -m app.main --selftest                        # smoke test (also works in a PyInstaller build)
```
Data directory: `%APPDATA%\BaleDownloadHub` (Linux `~/.local/share/BaleDownloadHub`), override with env `BDH_HOME`.

## Where to change what
| Task | Place |
|---|---|
| Bale endpoint/field changed | `integrations/bale/adapter.py` (+ `client.py` for transport rules) |
| New setting | `core/config.py` model → `ui/pages/settings.py` `F(...)` → `scripts/i18n/field_strings.py` (title/description/how-to/example in 3 languages) → `python scripts/build_i18n.py` |
| New UI text | `scripts/i18n/page_strings.py` then `python scripts/build_i18n.py` (fails on missing translation/placeholder mismatch) |
| New bot command | `services/bot_service.py::_command` + strings `bot.*` + tests in `tests/integration/test_bot.py` |
| New DB column/table | `database/models.py` **and** a new Alembic revision in `database/migrations/versions/` (a test compares them) |
| New error code | raise `HubError(code=…)`, add `error.<code>` in `ui_strings.py` (test enforces it) |
| New help article | `scripts/build_help.py` |
| Theme | `ui/theme.py::PALETTES` |

## Conventions
* No blocking I/O on the GUI thread (`run_async`).
* Anything that may contain a secret goes through `core.logger.mask_text` before storage/display.
* Never delete outside `CleanupManager`; never build paths from untrusted names without `safe_join`.
* Use `subprocess` with lists only. No `shell=True` (an AST test fails the build).
* Event listeners must take the event name **positionally** (`def f(evt, /, **payload)`), payloads may contain `name`.

## Test tooling (`tests/helpers.py`)
* `LocalServer` – HTTP server with Range/ETag, redirects, drops, throttling, disguised files.
* `FakeBale` – in-memory Bale API (`reject_methods`, `deny_chats`, `fail_next`, `post_denied`…); parses real multipart.
* `conftest.make_ctx` builds a full `AppContext` wired to both fakes; `ctx`/`fake_bale`/`server` fixtures.

## Build
`build.bat` → `scripts/build.py` (PyInstaller, onedir by default, `onefile` optional). Data files bundled: `app/resources`, `app/localization`, `app/database/migrations`. Put `ffmpeg.exe`/`ffprobe.exe` into a `bin` folder next to the EXE if you want media details in a bundled build. Regenerate documentation assets: `python scripts/make_screenshots.py && python scripts/generate_pdf.py`, test report: `pytest --junitxml=j.xml && python scripts/make_test_report.py j.xml TEST_REPORT.md`.

## Release checklist
1. `pytest` all green · 2. `python -m app.main --selftest` · 3. bump `app/__init__.py` · 4. rebuild i18n/help/PDF · 5. `build.bat` on Windows and run the wizard against a real bot · 6. update `requirements.txt` pins only after re-running the suite.
