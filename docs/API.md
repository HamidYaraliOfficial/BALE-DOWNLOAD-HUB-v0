# API notes

## 1. Bale Bot API – what is used (verified against https://docs.bale.ai)
Base URL `https://tapi.bale.ai/bot<token>/<method>`; responses `{ok, result | description, error_code, parameters}`.

| Method | Used for | Notes |
|---|---|---|
| `getMe` | token test, bot name | |
| `getChat` | channel existence, numeric id, title | |
| `sendMessage` / `deleteMessage` | channel access probe, replies, admin alerts | text ≤ 4096 |
| `sendDocument` `sendPhoto` `sendVideo` `sendAudio` | publishing | multipart upload; ≤ 50 MB (photos ≤ 10 MB); caption ≤ 1024 (we cut at 1024) |
| `getUpdates` (`offset`,`limit`) | bot polling | no `timeout` parameter in the docs → short polling |
| `getWebhookInfo` / `setWebhook` (empty url) | disable a webhook so `getUpdates` works | |

**Not available / not used** (not in the documentation): scheduled posts, `getChatMember`/`getChatAdministrators` (so access is probed by sending and deleting a message), `answerCallbackQuery` (so confirmations are text commands), custom thumbnails for `sendDocument`/`sendVideo`, long-poll timeout.

Error handling: 401 → `BaleAuthError` (no retry); 429/5xx → retry with `Retry-After`/exponential back-off (calls without a body only); uploads are retried **only** if the connection could not be established (no duplicate posts). The token never appears in raised errors or logs (masked at the source).

## 2. Optional local link API (internal)
Disabled by default; Settings → Bot. Loopback only (`127.0.0.1`), port 1024–65535 (default 8765). Auth: `Authorization: Bearer <key>` or `X-API-Key: <key>` (key shown/copied/regenerated in the UI, stored in the secret store, compared in constant time). 60 requests/min, 64 KB body, 20 links per request.

```
POST /api/v1/links   {"urls": ["https://…"], "destinations": [1,2]?}
 → 200 {"results":[{"url":"…","ok":true,"job_id":"…","code":null}, {"url":"…","ok":false,"job_id":null,"code":"duplicate_active"}]}
GET  /api/v1/status  → {"active":0,"queued":2,"completed":10,"failed":1,"queue_paused":false}
Errors: 400 invalid_json/too_many_links · 401 unauthorized · 404 not_found · 413 body_size · 429 rate_limited
```
```bash
curl -X POST http://127.0.0.1:8765/api/v1/links -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{"urls":["https://example.com/a.pdf"]}'
```

## 3. Update feed (optional)
`GET <feed url>` (https, public host) → `{"version":"1.2.0","notes":"…","security":false,"url":"https://…"}`. The app only *reports* a newer version; nothing is installed automatically.
