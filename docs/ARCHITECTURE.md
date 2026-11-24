# Architecture

## Principles
1. **UI is separate from logic.** `app/ui/*` talks only to `AppContext` services and the `EventBus`; services never import Qt.
2. **One door to Bale.** Only `integrations/bale/adapter.py::BaleAPIAdapter` knows endpoint names. If Bale changes its API, only that package changes.
3. **Everything can be driven by tests.** Every external effect (HTTP, Bale, DNS, disk size, keyring) is injectable through `AppContext(...)` parameters.
4. **Files live only in per-job folders** and are deleted by `CleanupManager` – never in the database.

## Component map
```
                     ┌────────────── UI (PySide6) ──────────────┐
                     │ MainWindow · Wizard · Pages · Toasts      │
                     └───────────────┬──────────────▲────────────┘
                         calls       │              │ Qt signals via EventBridge
                                     ▼              │
 Bale  ◄──► BotRuntime ◄► BotService ─► DownloadService ◄─ LocalApi (127.0.0.1)
 API        (token,poll)   (commands)    │  intake, pipeline          ▲
   ▲                                     │                            │ desktop / import
   │                    ┌────────────────┼───────────────┬────────────┘
   │                    ▼                ▼               ▼
   │             DownloadEngine     MediaProcessor   PublishingService ─► BalePublisher
   │             (direct / yt-dlp)  (sniff, analyse) (routing, caption,
   │                    │                              dedupe, split)
   │             QueueManager ◄──────── Repository (SQLite/SQLAlchemy) ───► CleanupManager + Scheduler
   └──── NotificationService ◄── EventBus                     SettingsManager · SecretStore · AccessController
```

## Job life-cycle
`WAITING → VALIDATING → DOWNLOADING → PROCESSING → [PAUSED(awaiting approval)] → UPLOADING → CLEANUP → COMPLETED | FAILED | CANCELLED`

* `QueueManager` dispatches by `(priority desc, created asc)`, respects `scheduled_at`, the concurrency limit and "no two identical URLs at once".
* Stage markers are kept in `download_jobs.meta` (`stage`, `file`) so a restarted job skips what is already done (e.g. re-upload without re-download).
* Failures: transient errors → `WAITING` with exponential back-off while `attempts ≤ retry_count`; final failures → `CLEANUP` → `FAILED`.
* `JobControl` is a cooperative pause/cancel flag checked per chunk; pause keeps `data.part` + `data.state.json` for resume.
* Crash recovery: `QueueManager.recover()` re-queues jobs found in an active state; the scheduler sweeps orphan folders.

## Download engine
`HttpFetcher` validates **every redirect hop** (`validate_url`) with manual redirect handling. `DirectDownloader` plans `[start,end,pos]` segments, writes into one preallocated `data.part` (one file handle per segment thread), persists segment positions to `data.state.json` (bound to URL+size+ETag+Last-Modified), and falls back to a single stream if any ranged request is answered with 200. A shared token-bucket `BandwidthLimiter` implements the global speed cap. yt-dlp is used through its Python API (no subprocess) only for HTML pages.

## Persistence
Tables: `settings, application_preferences, bot_accounts, channels, authorized_users, download_jobs, download_queue, publish_history, content_fingerprints, activity_logs, error_logs, caption_templates, cleanup_history` (Alembic revision `0001`; a test asserts models == migrated schema and that no column is binary). WAL mode, foreign keys on. Retention purge archives to `.jsonl.gz` first.

## Settings
`pydantic` models (`core/config.py`) are validated *before* saving; `SettingsManager.update` deep-merges a patch, validates, persists and publishes `settings.changed`. `publish.delete_after_upload` is forced `True` by a validator (product guarantee).

## Concurrency model
Plain threads: queue dispatcher, one worker per active job, one thread per download segment, bot poller, scheduler, local API server. The GUI thread receives events through `EventBridge` (queued Qt signals) and blocking work from the UI goes through `run_async`.

## Localization
`app/localization/{fa,en,zh}.json` generated from `scripts/i18n/*` (each key defined once with three translations; build script fails on missing translation or placeholder mismatch). `Translator.missing` records unknown keys; a UI test renders every page in every language and asserts it is empty.
