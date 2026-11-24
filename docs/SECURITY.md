# Security

## Threat model (short)
The app takes URLs from people (desktop user, bot users, local programs), fetches arbitrary remote data, writes it to disk and uploads it to a messenger. Main risks: SSRF, malicious files/archives, path escape, secret leakage, abuse by unauthorised users, runaway resource use.

## Controls and where they live
| Risk | Control | Code | Test |
|---|---|---|---|
| SSRF | http/https only; reject credentials in URL; block localhost, `.local/.internal`, private/loopback/link-local/multicast/reserved/CGNAT, IPv4-mapped & 6to4, decimal/hex IPv4 forms; resolve DNS and check **all** answers; re-validate **every redirect hop** | `security/url_safety.py`, `downloader/direct.py::HttpFetcher` | `test_url_validation_blocks`, `test_redirect_to_*` |
| Disguised files | never trust extension/MIME; magic-byte sniffing; HTML-instead-of-file, executable-with-other-extension, type mismatch rejected; executables blocked by default | `downloader/validators.py`, `media/processor.py` | `test_security.py`, `test_fake_image_and_disguised_executable_are_blocked` |
| Zip Slip / bombs | archives are only *inspected* (never extracted); `../`, absolute and drive paths or extreme ratio → rejected | `media/analyzer.py::inspect_zip` | `test_zip_slip_and_bomb_detection` |
| Path traversal / collisions | `sanitize_filename` (separators, reserved Windows names, control chars, length), `safe_join` guard, per-job folder with UUID name, unique names | `validators.py` | `test_sanitize_filename_is_safe`, `test_content_disposition_path_traversal…` |
| Unbounded downloads | size cap checked up-front and while streaming (also with unknown length), timeouts, redirect limit, free-disk guard | `direct.py` | `test_size_limits_declared_and_undeclared`, `test_disk_space_guard` |
| Command injection | no `shell=True`, `os.system`, `eval/exec`, `pickle` (checked by an AST test); subprocess always with argument lists; downloaded files are never executed/opened | whole code base | `test_no_shell_execution_or_dangerous_calls_in_source` |
| Token leakage | OS credential vault (`keyring`) or Fernet-encrypted file; token never in DB/settings/exports/backups; regex + exact-value masking in logs, DB error log, reports, exceptions; httpx URL logging silenced | `security/secret_store.py`, `core/logger.py` | `test_token_absent_from_every_persisted_artifact`, `test_no_token_in_logs…` |
| Unauthorised use | default-deny allow-list; RBAC (Super Admin / Admin / Operator / Read Only); blocked users; per-user rate limit and daily quota; strangers get one rate-limited reply with their ID; all denials logged under *security* | `security/access_control.py`, `services/bot_service.py` | `test_bot.py` |
| Local API abuse | off by default; 127.0.0.1 only; key in constant time; limits; failures logged | `services/local_api.py` | `test_local_api.py` |
| Prohibited content | DRM / live / login-or-paywall content is refused, never bypassed | `media_extractor.py`, `direct.py` | `test_server_denials_are_not_bypassed` |
| Data retention | job folder deleted after success/failure/cancel; orphan sweep; privacy mode scrubs URL/name/hash; DB has no BLOB columns | `cleanup/*` | `test_pipeline.py`, `test_cleanup_publish_backup.py` |
| Backups | optional password (PBKDF2-SHA256 300k + Fernet); verify before restore; safety copy; export never contains tokens | `services/backup_service.py` | backup tests |
| Antivirus | optional Defender/ClamAV; **"unavailable" is never reported as clean** | `security/scanner.py` | scanner tests |

## Known limits (please read)
* **DNS rebinding (TOCTOU):** validation resolves the host, then the HTTP library resolves again to connect. A malicious DNS server could answer differently the second time. Mitigation would require pinning the validated IP in the transport; not implemented. Run the app on a network where internal services are not reachable from the PC if this matters.
* **yt-dlp** performs its own requests (and follows its own redirects). Only the entry URL is validated by this app.
* **Fallback secret file** (when no OS vault exists) is protected by a key derived from machine/user identifiers: it stops casual reading and accidental leaks through copies, **not** malware running as the same user.
* **File deletion is not secure erase.** Contents may be recoverable with forensic tools until overwritten. Use full-disk encryption if that matters.
* Anyone who can use the desktop app is a Super Admin by design.
* No automatic code signing / update verification: updates are never installed by the app.

## Reporting
Please report vulnerabilities privately to the maintainer of your distribution.
