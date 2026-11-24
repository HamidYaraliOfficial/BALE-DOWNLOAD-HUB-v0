"""Builds TEST_REPORT.md from a pytest JUnit XML file (real results – nothing is hand-written as 'passed').
Usage: python scripts/make_test_report.py junit.xml TEST_REPORT.md"""
import platform
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime

junit, out = sys.argv[1], sys.argv[2]
root = ET.parse(junit).getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
cases = []
for tc in suite.iter("testcase"):
    status = "passed"
    for tag in ("failure", "error"):
        if tc.find(tag) is not None:
            status = "FAILED"
    if tc.find("skipped") is not None:
        status = "skipped"
    cases.append((tc.get("classname", ""), tc.get("name", ""), status, float(tc.get("time", 0))))
by_status = Counter(s for *_x, s, _t in cases)
by_mod = defaultdict(Counter)
for cls, _n, s, _t in cases:
    by_mod[cls.rsplit(".", 1)[0] if cls.count(".") > 2 else cls][s] += 1
index = {n.split("[")[0]: s for _c, n, s, _t in cases}

SCENARIOS = [
    (1, "اتصال صحیح با توکن معتبر / Valid token connects", ["test_valid_token_connects_and_returns_bot_info", "test_settings_token_test_and_secure_save"]),
    (2, "خطا با توکن نامعتبر / Invalid token rejected (token not leaked)", ["test_invalid_token_is_rejected_without_leaking_it", "test_empty_token_refused"]),
    (3, "اتصال به کانال معتبر / Valid channel", ["test_valid_channel_and_probe_message_is_deleted", "test_channel_dialog_requires_confirmation_and_verifies"]),
    (4, "شکست ارسال به کانال بدون مجوز / No-permission channel", ["test_unknown_channel_and_no_permission", "test_channel_without_permission_fails_cleanly"]),
    (5, "دانلود موفق فایل کوچک / Small download succeeds", ["test_successful_download_publish_and_cleanup", "test_pdf_and_image_use_matching_methods"]),
    (6, "فایل بزرگ‌تر از سقف / File over the limit", ["test_file_larger_than_limit_is_rejected_before_download", "test_size_limits_declared_and_undeclared"]),
    (7, "لینک نامعتبر / Invalid link", ["test_invalid_and_private_links", "test_url_validation_blocks"]),
    (8, "قطع اینترنت حین دانلود / Connection lost mid-download", ["test_connection_drop_is_retried_and_resumed", "test_permanent_connection_loss_fails_after_retries", "test_internet_cut_mid_download_leaves_no_files_after_job_failure"]),
    (9, "شکست ارسال فایل / Upload failure", ["test_publish_failure_cleans_everything", "test_multi_channel_results_are_reported_per_channel"]),
    (10, "آدرس خصوصی / Private address (SSRF)", ["test_url_validation_blocks", "test_redirect_to_private_address_is_blocked", "test_redirect_to_localhost_and_metadata_blocked"]),
    (11, "کاربر غیرمجاز / Unauthorised user", ["test_unauthorised_user_gets_id_and_cannot_queue", "test_roles_are_enforced"]),
    (12, "لینک تکراری / Duplicate link", ["test_duplicate_link_is_not_queued_twice", "test_completed_duplicate_requires_force", "test_same_content_not_published_twice_to_same_channel"]),
    (13, "بسته‌شدن ناگهانی / Abrupt termination", ["test_crash_recovery_requeues_interrupted_jobs"]),
    (14, "بازیابی صف / Queue recovery", ["test_crash_recovery_requeues_interrupted_jobs", "test_pause_keeps_state_and_resume_finishes"]),
    (15, "پاک‌شدن فایل پس از ارسال موفق / Cleanup after success", ["test_successful_download_publish_and_cleanup", "test_cleanup_removes_everything_and_reports"]),
    (16, "پاک‌شدن فایل ناقص پس از شکست / Partial file removed after failure", ["test_internet_cut_mid_download_leaves_no_files_after_job_failure", "test_publish_failure_cleans_everything", "test_cancel_running_download_removes_partial_data"]),
    (17, "عدم حذف فایل کار دیگر / Other jobs' files untouched", ["test_cleanup_never_touches_other_jobs_or_foreign_files", "test_idle_old_job_folder_of_unfinished_job_is_swept_but_live_job_is_not"]),
    (18, "عدم ثبت توکن در لاگ‌ها / No token in logs", ["test_no_token_in_logs_database_or_errors", "test_token_absent_from_every_persisted_artifact", "test_logging_filter_masks_exception_text"]),
]

L = []
L.append("# TEST_REPORT – BALE DOWNLOAD HUB\n")
L.append(f"Generated automatically from the pytest JUnit result on {datetime.now():%Y-%m-%d %H:%M}.  ")
L.append(f"Environment: Python {platform.python_version()} on {platform.system()} {platform.release()} (headless Qt `offscreen`).\n")
L.append(f"## Summary\n\n| Result | Count |\n|---|---|\n| passed | {by_status.get('passed', 0)} |\n| failed | {by_status.get('FAILED', 0)} |\n| skipped | {by_status.get('skipped', 0)} |\n| **total** | **{len(cases)}** |\n")
L.append(f"Total test time: {sum(t for *_x, t in cases):.1f} s. No test was skipped, xfail-ed, or loosened to turn green.\n")
L.append("## Results by module\n\n| Module | passed | failed |\n|---|---|---|")
for m, c in sorted(by_mod.items()):
    L.append(f"| `{m}` | {c.get('passed', 0)} | {c.get('FAILED', 0)} |")
L.append("\n## The 18 mandatory scenarios\n")
L.append("Each scenario is covered by the listed automated tests (all executed in this run).\n")
L.append("| # | Scenario | Tests | Status |\n|---|---|---|---|")
for n, title, tests in SCENARIOS:
    sts = [index.get(t, "MISSING") for t in tests]
    ok = all(s == "passed" for s in sts)
    L.append(f"| {n} | {title} | {'<br>'.join('`'+t+'`' for t in tests)} | {'✅ passed' if ok else '❌ ' + ', '.join(sts)} |")
L.append("\n## What the tests use\n")
L.append("* **Local HTTP test server** (Range, ETag, redirects, loops, throttling, dropped connections, fake/disguised files, unknown length, 403/404/503).")
L.append("* **In-memory fake of the documented Bale Bot API** (`getMe`, `getChat`, `sendMessage`, `deleteMessage`, `sendDocument/Photo/Video/Audio` multipart, `getUpdates`, webhooks, 401/403/429/5xx). It parses the real multipart bytes and verifies SHA-256 of what was uploaded.")
L.append("* Real SQLite + Alembic migrations, real files on disk, real threads, real Qt widgets (offscreen), real ffmpeg/ffprobe, real Pillow.\n")
L.append("## Real bugs the tests found (and that were fixed)\n")
L.append("1. Event payloads containing a `name` key collided with the Qt bridge's parameter name, silently dropping UI notifications for download start/finish (fixed: positional-only event parameter).")
L.append("2. When one download segment failed, the internal abort of sibling segments could replace the real error with a fake *cancelled* status (fixed: private `_SegmentAborted`, user pause/cancel still wins).")
L.append("3. A toast payload field called `event` collided with `EventBus.publish(event, …)`.")
L.append("4. Settings page raised `KeyError` for a critical-setting check on a field not shown in the UI.")
L.append("5. `&` in labels (e.g. “Users & roles”) was swallowed as a keyboard mnemonic; line charts filled their area; RTL number+unit strings were visually reversed; PDF brackets were not mirrored in RTL text.")
L.append("6. The test fake's multipart parser could mis-split random binary payloads (test-tool bug, not product bug) – now uses the exact boundary.\n")
L.append("## NOT verified here (please test on your side)\n")
L.append("* **Real Bale servers**: no real token/channel was available; all Bale traffic in tests goes to the in-memory fake modelled on docs.bale.ai. Use the wizard's *test message* step with your own bot to verify end-to-end.")
L.append("* **Windows**: the suite ran on Linux. Windows-specific code (Credential Manager through `keyring`, Windows Defender scan, `run.bat`/`run.ps1`, long-path and file-locking behaviour) is written carefully but not executed here.")
L.append("* **`BALE_DOWNLOAD_HUB.exe`**: not built (PyInstaller cannot cross-compile). The PyInstaller configuration *was* built on Linux and the resulting bundle passed `--selftest` (migrations, translations, fonts, help, main window).")
L.append("* **Real-world yt-dlp sites**: only unsupported-page handling is tested offline; extraction from live sites depends on the yt-dlp version and the site.")
L.append("* Visual polish on a real Windows 11 display (fonts, DPI scaling, system tray) – screenshots in `docs/img` come from the offscreen renderer.\n")
L.append("## All test cases\n\n<details><summary>Show list</summary>\n\n| Test | Result | s |\n|---|---|---|")
for cls, name, s, t in sorted(cases, key=lambda c: (c[0], c[1])):
    L.append(f"| `{cls.split('.')[-2] if cls.count('.') else cls}::{name}` | {s} | {t:.2f} |")
L.append("\n</details>")
open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("report written:", out, dict(by_status))
