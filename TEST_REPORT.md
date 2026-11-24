# TEST_REPORT – BALE DOWNLOAD HUB

Generated automatically from the pytest JUnit result on 2026-11-22 14:51.  
Environment: Python 3.12.3 on Linux 6.18.44-fc-v726 (headless Qt `offscreen`).

## Summary

| Result | Count |
|---|---|
| passed | 183 |
| failed | 0 |
| skipped | 0 |
| **total** | **183** |

Total test time: 68.8 s. No test was skipped, xfail-ed, or loosened to turn green.

## Results by module

| Module | passed | failed |
|---|---|---|
| `tests.integration.test_bale` | 15 | 0 |
| `tests.integration.test_bot` | 12 | 0 |
| `tests.integration.test_cleanup_publish_backup` | 21 | 0 |
| `tests.integration.test_downloader` | 18 | 0 |
| `tests.integration.test_local_api` | 5 | 0 |
| `tests.integration.test_pipeline` | 17 | 0 |
| `tests.security.test_security` | 13 | 0 |
| `tests.ui.test_ui` | 18 | 0 |
| `tests.unit.test_core` | 54 | 0 |
| `tests.unit.test_i18n` | 10 | 0 |

## The 18 mandatory scenarios

Each scenario is covered by the listed automated tests (all executed in this run).

| # | Scenario | Tests | Status |
|---|---|---|---|
| 1 | اتصال صحیح با توکن معتبر / Valid token connects | `test_valid_token_connects_and_returns_bot_info`<br>`test_settings_token_test_and_secure_save` | ✅ passed |
| 2 | خطا با توکن نامعتبر / Invalid token rejected (token not leaked) | `test_invalid_token_is_rejected_without_leaking_it`<br>`test_empty_token_refused` | ✅ passed |
| 3 | اتصال به کانال معتبر / Valid channel | `test_valid_channel_and_probe_message_is_deleted`<br>`test_channel_dialog_requires_confirmation_and_verifies` | ✅ passed |
| 4 | شکست ارسال به کانال بدون مجوز / No-permission channel | `test_unknown_channel_and_no_permission`<br>`test_channel_without_permission_fails_cleanly` | ✅ passed |
| 5 | دانلود موفق فایل کوچک / Small download succeeds | `test_successful_download_publish_and_cleanup`<br>`test_pdf_and_image_use_matching_methods` | ✅ passed |
| 6 | فایل بزرگ‌تر از سقف / File over the limit | `test_file_larger_than_limit_is_rejected_before_download`<br>`test_size_limits_declared_and_undeclared` | ✅ passed |
| 7 | لینک نامعتبر / Invalid link | `test_invalid_and_private_links`<br>`test_url_validation_blocks` | ✅ passed |
| 8 | قطع اینترنت حین دانلود / Connection lost mid-download | `test_connection_drop_is_retried_and_resumed`<br>`test_permanent_connection_loss_fails_after_retries`<br>`test_internet_cut_mid_download_leaves_no_files_after_job_failure` | ✅ passed |
| 9 | شکست ارسال فایل / Upload failure | `test_publish_failure_cleans_everything`<br>`test_multi_channel_results_are_reported_per_channel` | ✅ passed |
| 10 | آدرس خصوصی / Private address (SSRF) | `test_url_validation_blocks`<br>`test_redirect_to_private_address_is_blocked`<br>`test_redirect_to_localhost_and_metadata_blocked` | ✅ passed |
| 11 | کاربر غیرمجاز / Unauthorised user | `test_unauthorised_user_gets_id_and_cannot_queue`<br>`test_roles_are_enforced` | ✅ passed |
| 12 | لینک تکراری / Duplicate link | `test_duplicate_link_is_not_queued_twice`<br>`test_completed_duplicate_requires_force`<br>`test_same_content_not_published_twice_to_same_channel` | ✅ passed |
| 13 | بسته‌شدن ناگهانی / Abrupt termination | `test_crash_recovery_requeues_interrupted_jobs` | ✅ passed |
| 14 | بازیابی صف / Queue recovery | `test_crash_recovery_requeues_interrupted_jobs`<br>`test_pause_keeps_state_and_resume_finishes` | ✅ passed |
| 15 | پاک‌شدن فایل پس از ارسال موفق / Cleanup after success | `test_successful_download_publish_and_cleanup`<br>`test_cleanup_removes_everything_and_reports` | ✅ passed |
| 16 | پاک‌شدن فایل ناقص پس از شکست / Partial file removed after failure | `test_internet_cut_mid_download_leaves_no_files_after_job_failure`<br>`test_publish_failure_cleans_everything`<br>`test_cancel_running_download_removes_partial_data` | ✅ passed |
| 17 | عدم حذف فایل کار دیگر / Other jobs' files untouched | `test_cleanup_never_touches_other_jobs_or_foreign_files`<br>`test_idle_old_job_folder_of_unfinished_job_is_swept_but_live_job_is_not` | ✅ passed |
| 18 | عدم ثبت توکن در لاگ‌ها / No token in logs | `test_no_token_in_logs_database_or_errors`<br>`test_token_absent_from_every_persisted_artifact`<br>`test_logging_filter_masks_exception_text` | ✅ passed |

## What the tests use

* **Local HTTP test server** (Range, ETag, redirects, loops, throttling, dropped connections, fake/disguised files, unknown length, 403/404/503).
* **In-memory fake of the documented Bale Bot API** (`getMe`, `getChat`, `sendMessage`, `deleteMessage`, `sendDocument/Photo/Video/Audio` multipart, `getUpdates`, webhooks, 401/403/429/5xx). It parses the real multipart bytes and verifies SHA-256 of what was uploaded.
* Real SQLite + Alembic migrations, real files on disk, real threads, real Qt widgets (offscreen), real ffmpeg/ffprobe, real Pillow.

## Real bugs the tests found (and that were fixed)

1. Event payloads containing a `name` key collided with the Qt bridge's parameter name, silently dropping UI notifications for download start/finish (fixed: positional-only event parameter).
2. When one download segment failed, the internal abort of sibling segments could replace the real error with a fake *cancelled* status (fixed: private `_SegmentAborted`, user pause/cancel still wins).
3. A toast payload field called `event` collided with `EventBus.publish(event, …)`.
4. Settings page raised `KeyError` for a critical-setting check on a field not shown in the UI.
5. `&` in labels (e.g. “Users & roles”) was swallowed as a keyboard mnemonic; line charts filled their area; RTL number+unit strings were visually reversed; PDF brackets were not mirrored in RTL text.
6. The test fake's multipart parser could mis-split random binary payloads (test-tool bug, not product bug) – now uses the exact boundary.

## NOT verified here (please test on your side)

* **Real Bale servers**: no real token/channel was available; all Bale traffic in tests goes to the in-memory fake modelled on docs.bale.ai. Use the wizard's *test message* step with your own bot to verify end-to-end.
* **Windows**: the suite ran on Linux. Windows-specific code (Credential Manager through `keyring`, Windows Defender scan, `run.bat`/`run.ps1`, long-path and file-locking behaviour) is written carefully but not executed here.
* **`BALE_DOWNLOAD_HUB.exe`**: not built (PyInstaller cannot cross-compile). The PyInstaller configuration *was* built on Linux and the resulting bundle passed `--selftest` (migrations, translations, fonts, help, main window).
* **Real-world yt-dlp sites**: only unsupported-page handling is tested offline; extraction from live sites depends on the yt-dlp version and the site.
* Visual polish on a real Windows 11 display (fonts, DPI scaling, system tray) – screenshots in `docs/img` come from the offscreen renderer.

## All test cases

<details><summary>Show list</summary>

| Test | Result | s |
|---|---|---|
| `integration::test_choose_method_rules` | passed | 0.00 |
| `integration::test_empty_token_refused` | passed | 0.00 |
| `integration::test_invalid_token_is_rejected_without_leaking_it` | passed | 0.00 |
| `integration::test_network_errors_are_masked_and_uploads_not_blindly_retried` | passed | 0.00 |
| `integration::test_normalize_chat_id` | passed | 0.00 |
| `integration::test_poller_reports_disconnect_after_repeated_network_failures` | passed | 0.13 |
| `integration::test_poller_stops_on_invalid_token_and_reports_disconnect` | passed | 0.08 |
| `integration::test_polling_handles_updates_once_and_persists_offset` | passed | 0.31 |
| `integration::test_publisher_falls_back_to_document_and_enforces_50mb` | passed | 0.00 |
| `integration::test_retry_on_429_then_success_and_no_retry_on_auth` | passed | 0.00 |
| `integration::test_send_methods_and_caption_limit` | passed | 0.01 |
| `integration::test_unknown_channel_and_no_permission` | passed | 0.00 |
| `integration::test_upload_retried_when_connection_could_not_be_established` | passed | 0.00 |
| `integration::test_valid_channel_and_probe_message_is_deleted` | passed | 0.00 |
| `integration::test_valid_token_connects_and_returns_bot_info` | passed | 0.00 |
| `integration::test_batch_with_duplicate_and_unknown_command` | passed | 0.15 |
| `integration::test_cancel_own_job_only` | passed | 0.15 |
| `integration::test_confirmation_mode` | passed | 0.15 |
| `integration::test_default_is_admin_only_blocked_and_removed_users_denied` | passed | 0.14 |
| `integration::test_group_and_channel_messages_are_ignored` | passed | 0.23 |
| `integration::test_invalid_and_private_links_rejected_in_chat` | passed | 0.13 |
| `integration::test_language_follows_settings` | passed | 0.13 |
| `integration::test_operator_link_is_downloaded_and_published` | passed | 0.19 |
| `integration::test_rate_limit_per_user` | passed | 0.13 |
| `integration::test_roles_are_enforced` | passed | 0.12 |
| `integration::test_unauthorised_user_gets_id_and_cannot_queue` | passed | 0.12 |
| `integration::test_user_management_commands_respect_hierarchy` | passed | 0.12 |
| `integration::test_approval_flow_holds_file_until_approved` | passed | 0.19 |
| `integration::test_archive_retention_writes_archive_before_delete` | passed | 0.08 |
| `integration::test_backup_roundtrip_plain_and_encrypted` | passed | 0.38 |
| `integration::test_caption_templates_per_type_and_override` | passed | 0.19 |
| `integration::test_category_routing` | passed | 0.30 |
| `integration::test_cleanup_removes_everything_and_reports` | passed | 0.10 |
| `integration::test_discarding_an_unapproved_job_deletes_its_file` | passed | 0.14 |
| `integration::test_disk_low_pauses_queue_and_notifies` | passed | 0.07 |
| `integration::test_idle_old_job_folder_of_unfinished_job_is_swept_but_live_job_is_not` | passed | 0.09 |
| `integration::test_invalid_job_id_cannot_escape` | passed | 0.07 |
| `integration::test_job_waits_instead_of_failing_when_disk_is_full` | passed | 0.65 |
| `integration::test_locked_files_are_reported_and_retried_later` | passed | 0.10 |
| `integration::test_multi_channel_results_are_reported_per_channel` | passed | 0.24 |
| `integration::test_queue_priority_order_and_concurrency_limit` | passed | 1.81 |
| `integration::test_reports_are_masked_and_well_formed` | passed | 0.00 |
| `integration::test_restore_rejects_garbage_and_missing_password` | passed | 0.15 |
| `integration::test_scheduled_job_waits_for_its_time` | passed | 2.27 |
| `integration::test_scheduler_sweeps_orphans_and_purges` | passed | 0.08 |
| `integration::test_settings_export_import_roundtrip_via_service` | passed | 0.08 |
| `integration::test_split_file_parts` | passed | 0.00 |
| `integration::test_user_quota_enforced_for_bot_users_not_desktop` | passed | 0.08 |
| `integration::test_bandwidth_limit_is_applied` | passed | 2.08 |
| `integration::test_cancel_raises` | passed | 0.33 |
| `integration::test_connection_drop_is_retried_and_resumed` | passed | 0.13 |
| `integration::test_content_disposition_path_traversal_stays_inside_job_dir` | passed | 0.31 |
| `integration::test_disk_space_guard` | passed | 0.02 |
| `integration::test_engine_probe_reports_unsupported_without_raising` | passed | 0.03 |
| `integration::test_html_page_without_media_is_not_downloadable` | passed | 0.01 |
| `integration::test_internet_cut_mid_download_leaves_no_files_after_job_failure` | passed | 0.14 |
| `integration::test_pause_keeps_state_and_resume_finishes` | passed | 0.81 |
| `integration::test_permanent_connection_loss_fails_after_retries` | passed | 0.13 |
| `integration::test_redirect_to_localhost_and_metadata_blocked` | passed | 0.00 |
| `integration::test_redirect_to_private_address_is_blocked` | passed | 0.00 |
| `integration::test_redirects_are_followed_and_loops_stopped` | passed | 0.02 |
| `integration::test_resume_is_refused_when_source_changed` | passed | 0.98 |
| `integration::test_segmented_download_matches_hash` | passed | 0.03 |
| `integration::test_server_denials_are_not_bypassed` | passed | 0.02 |
| `integration::test_single_segment_when_server_has_no_range` | passed | 0.02 |
| `integration::test_size_limits_declared_and_undeclared` | passed | 0.03 |
| `integration::test_disabled_by_default_and_binds_loopback_only` | passed | 0.66 |
| `integration::test_input_validation_and_limits` | passed | 0.85 |
| `integration::test_key_is_secret_and_regenerable` | passed | 0.75 |
| `integration::test_links_are_queued_and_published` | passed | 0.71 |
| `integration::test_requires_key` | passed | 0.86 |
| `integration::test_cancel_running_download_removes_partial_data` | passed | 0.73 |
| `integration::test_channel_without_permission_fails_cleanly` | passed | 0.14 |
| `integration::test_cleanup_never_touches_other_jobs_or_foreign_files` | passed | 0.09 |
| `integration::test_completed_duplicate_requires_force` | passed | 0.14 |
| `integration::test_crash_recovery_requeues_interrupted_jobs` | passed | 0.94 |
| `integration::test_download_failure_leaves_no_partial_file` | passed | 0.20 |
| `integration::test_duplicate_link_is_not_queued_twice` | passed | 0.08 |
| `integration::test_fake_image_and_disguised_executable_are_blocked` | passed | 0.18 |
| `integration::test_file_larger_than_limit_is_rejected_before_download` | passed | 0.07 |
| `integration::test_invalid_and_private_links` | passed | 0.07 |
| `integration::test_no_token_in_logs_database_or_errors` | passed | 0.13 |
| `integration::test_pause_then_resume_completes_with_correct_hash` | passed | 0.76 |
| `integration::test_pdf_and_image_use_matching_methods` | passed | 0.19 |
| `integration::test_privacy_mode_scrubs_url_and_filename` | passed | 0.35 |
| `integration::test_publish_failure_cleans_everything` | passed | 0.26 |
| `integration::test_same_content_not_published_twice_to_same_channel` | passed | 0.18 |
| `integration::test_successful_download_publish_and_cleanup` | passed | 0.18 |
| `security::test_downloaded_files_are_never_executed_or_opened_with_shell` | passed | 0.00 |
| `security::test_executables_blocked_even_when_allowed_type_is_other` | passed | 0.00 |
| `security::test_infected_file_is_rejected_and_cleaned` | passed | 0.13 |
| `security::test_no_hardcoded_secrets_in_project` | passed | 0.02 |
| `security::test_no_shell_execution_or_dangerous_calls_in_source` | passed | 0.20 |
| `security::test_rename_features_cannot_write_outside_directory` | passed | 0.00 |
| `security::test_scan_engine_result_mapping` | passed | 0.00 |
| `security::test_signature_check_can_be_trusted_over_extension` | passed | 0.00 |
| `security::test_subprocess_always_uses_argument_lists` | passed | 0.10 |
| `security::test_token_absent_from_every_persisted_artifact` | passed | 0.18 |
| `security::test_update_check_only_https_public_and_never_installs` | passed | 0.00 |
| `security::test_virus_scan_never_reports_clean_without_engine` | passed | 0.00 |
| `security::test_zip_slip_and_bomb_detection` | passed | 0.27 |
| `ui::test_add_links_dialog_analyse_then_confirm` | passed | 3.29 |
| `ui::test_admins_get_bale_message_on_selected_events` | passed | 0.11 |
| `ui::test_channel_dialog_requires_confirmation_and_verifies` | passed | 1.36 |
| `ui::test_dashboard_numbers_are_real` | passed | 3.01 |
| `ui::test_downloads_page_lists_jobs_and_controls_them` | passed | 3.27 |
| `ui::test_every_page_renders_in_every_language_and_theme` | passed | 9.14 |
| `ui::test_every_settings_input_has_help_widgets` | passed | 2.10 |
| `ui::test_fieldrow_validation_secret_toggle_and_help` | passed | 0.07 |
| `ui::test_full_setup_wizard_flow` | passed | 2.42 |
| `ui::test_help_center_search` | passed | 1.54 |
| `ui::test_language_can_be_switched_at_any_time` | passed | 5.79 |
| `ui::test_logs_page_filters_and_exports` | passed | 2.10 |
| `ui::test_settings_save_valid_invalid_and_critical` | passed | 1.94 |
| `ui::test_settings_token_test_and_secure_save` | passed | 2.69 |
| `ui::test_seven_distinct_themes_and_accent` | passed | 0.00 |
| `ui::test_toast_notifications_and_per_event_switch` | passed | 2.04 |
| `ui::test_users_page_protects_last_super_admin` | passed | 1.36 |
| `ui::test_wizard_keeps_entered_values_after_exit` | passed | 2.16 |
| `unit::test_caption_engine` | passed | 0.00 |
| `unit::test_classify_and_sniff` | passed | 0.00 |
| `unit::test_dns_resolving_to_private_is_blocked_and_public_allowed` | passed | 0.00 |
| `unit::test_expected_tables_exist` | passed | 0.02 |
| `unit::test_extract_and_dedupe_links` | passed | 0.00 |
| `unit::test_filename_from_headers` | passed | 0.00 |
| `unit::test_is_public_ip` | passed | 0.00 |
| `unit::test_logging_filter_masks_exception_text` | passed | 0.00 |
| `unit::test_mask_obj_masks_sensitive_keys` | passed | 0.00 |
| `unit::test_mask_text_covers_token_headers_urls` | passed | 0.00 |
| `unit::test_migration_matches_models` | passed | 0.02 |
| `unit::test_normalize_url_for_dedupe` | passed | 0.00 |
| `unit::test_rate_limiter_window` | passed | 0.00 |
| `unit::test_rbac_matrix` | passed | 0.02 |
| `unit::test_read_links_file_txt_csv` | passed | 0.01 |
| `unit::test_registered_secret_is_masked_even_without_pattern` | passed | 0.00 |
| `unit::test_repository_stats_retention_and_queue_order` | passed | 0.04 |
| `unit::test_safe_join_blocks_traversal` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[   ]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[....]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[../../etc/passwd]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[..\\..\\windows\\system32\\cmd.exe]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[CON]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[a/b/c.txt]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[bad<>:"|?*name.pdf]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[evil\x00.exe]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[nul.txt]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[raw8]` | passed | 0.00 |
| `unit::test_sanitize_filename_is_safe[trailing. ]` | passed | 0.00 |
| `unit::test_secret_store_encrypted_fallback` | passed | 0.15 |
| `unit::test_settings_export_has_no_token` | passed | 0.02 |
| `unit::test_settings_validation_and_persistence` | passed | 0.02 |
| `unit::test_unique_name_avoids_collisions` | passed | 0.00 |
| `unit::test_url_validation_blocks[-url_empty]` | passed | 0.00 |
| `unit::test_url_validation_blocks[file:///etc/passwd-url_scheme]` | passed | 0.00 |
| `unit::test_url_validation_blocks[ftp://example.com/x-url_scheme]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http:///nohost-url_invalid]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://0.0.0.0/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://0x7f.1/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://10.1.2.3/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://100.64.0.1/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://127.0.0.1/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://169.254.169.254/latest/meta-data-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://172.16.0.1/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://192.168.1.1/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://2130706433/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://[::1]/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://[::ffff:127.0.0.1]/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://exa mple.com-url_invalid]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://localhost/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://metadata.google.internal/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://printer.local/x-url_private]` | passed | 0.00 |
| `unit::test_url_validation_blocks[http://user:pw@example.com/x-url_credentials]` | passed | 0.00 |
| `unit::test_url_validation_blocks[javascript:alert(1)-url_scheme]` | passed | 0.00 |
| `unit::test_all_languages_have_identical_key_sets` | passed | 0.00 |
| `unit::test_every_error_code_in_source_has_a_message` | passed | 0.00 |
| `unit::test_every_input_has_title_description_howto_and_example` | passed | 0.00 |
| `unit::test_every_static_key_used_in_code_exists` | passed | 0.05 |
| `unit::test_every_theme_and_status_and_role_is_translated` | passed | 0.00 |
| `unit::test_help_center_content` | passed | 0.16 |
| `unit::test_no_empty_translations_except_optional_howto` | passed | 0.00 |
| `unit::test_placeholders_consistent_across_languages` | passed | 0.00 |
| `unit::test_scripts_are_what_they_claim` | passed | 0.00 |
| `unit::test_translator_fallback_and_rtl` | passed | 0.00 |

</details>
