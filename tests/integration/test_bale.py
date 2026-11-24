import os

import httpx
import pytest

from app.core.exceptions import BaleApiError, BaleAuthError, BaleNetworkError, PublishError
from app.integrations.bale.adapter import BaleAPIAdapter, normalize_chat_id
from app.integrations.bale.client import BaleClient
from app.integrations.bale.polling import BalePoller
from app.integrations.bale.publisher import BalePublisher, choose_method
from app.core import events
from tests.helpers import FakeBale, TOKEN


def adapter(fake, token=TOKEN, **kw):
    return BaleAPIAdapter(BaleClient(token, transport=fake.transport(), sleep=lambda s: None, backoff=0, **kw))


def test_valid_token_connects_and_returns_bot_info():
    info = adapter(FakeBale()).get_me()
    assert info.username == "hub_bot" and info.id == 42


def test_invalid_token_is_rejected_without_leaking_it():
    bad = "999999:WRONGWRONGWRONGWRONGWRONGWRONG"
    with pytest.raises(BaleAuthError) as e:
        adapter(FakeBale(), token=bad).get_me()
    assert "WRONGWRONG" not in str(e.value)


def test_empty_token_refused():
    with pytest.raises(BaleAuthError):
        BaleClient("")


def test_valid_channel_and_probe_message_is_deleted():
    fake = FakeBale()
    res = adapter(fake).check_channel("@chan")
    assert res.ok and res.can_post and res.is_channel and res.title == "My Channel"
    assert fake.deleted and fake.sent_messages and "sendMessage" in fake.calls and "deleteMessage" in fake.calls


def test_unknown_channel_and_no_permission():
    assert not adapter(FakeBale(channel_ok=False)).check_channel("@nope").ok
    res = adapter(FakeBale(post_denied=True)).check_channel("@chan")
    assert not res.ok and res.can_post is False and "member" in res.detail.lower()
    # existence-only check does not post anything
    fake = FakeBale()
    adapter(fake).check_channel("@chan", probe_post=False)
    assert "sendMessage" not in fake.calls


def test_normalize_chat_id():
    assert normalize_chat_id("-1001") == -1001 and normalize_chat_id("chan") == "@chan" and normalize_chat_id("@c") == "@c"
    assert normalize_chat_id("https://ble.ir/mychan") == "@mychan"


def test_send_methods_and_caption_limit(tmp_path):
    fake = FakeBale()
    a = adapter(fake)
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc" * 100)
    a.send_document("@c", str(f), "c" * 3000)
    assert len(fake.sent[0]["caption"]) == 1024 and fake.sent[0]["filename"] == "x.bin" and fake.sent[0]["size"] == 300


def test_choose_method_rules():
    assert choose_method("a.jpg", "image", 1000) == "sendPhoto"
    assert choose_method("a.jpg", "image", 11 * 1024 * 1024) == "sendDocument"      # photos limited to 10 MB
    assert choose_method("a.webp", "image", 1000) == "sendDocument"
    assert choose_method("a.mp4", "video", 10_000) == "sendVideo" and choose_method("a.mkv", "video", 10) == "sendDocument"
    assert choose_method("a.mp3", "audio", 10) == "sendAudio" and choose_method("a.ogg", "audio", 10) == "sendDocument"
    assert choose_method("a.pdf", "document", 10) == "sendDocument"


def test_publisher_falls_back_to_document_and_enforces_50mb(tmp_path):
    fake = FakeBale()
    fake.reject_methods = {"sendPhoto"}
    pub = BalePublisher(adapter(fake))
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    r = pub.send("@c", str(img), "image", "cap")
    assert r.method == "sendDocument" and r.fell_back and fake.sent[0]["method"] == "sendDocument"
    big = tmp_path / "big.bin"
    with open(big, "wb") as f:
        f.truncate(51 * 1024 * 1024)
    with pytest.raises(PublishError) as e:
        pub.send("@c", str(big), "other", None)
    assert e.value.code == "too_large_for_bale"


def test_retry_on_429_then_success_and_no_retry_on_auth():
    fake = FakeBale()
    fake.fail_next = [(429, {"ok": False, "error_code": 429, "description": "slow down", "parameters": {"retry_after": 0}})]
    assert adapter(fake).get_me().username == "hub_bot"
    assert fake.calls.count("getMe") == 2
    fake2 = FakeBale()
    fake2.fail_next = [(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})]
    with pytest.raises(BaleAuthError):
        adapter(fake2).get_me()
    assert fake2.calls.count("getMe") == 1


def test_network_errors_are_masked_and_uploads_not_blindly_retried(tmp_path):
    calls = {"n": 0}

    def boom(req):
        calls["n"] += 1
        raise httpx.ReadError(f"connection reset while talking to {req.url}")

    a = BaleAPIAdapter(BaleClient(TOKEN, transport=httpx.MockTransport(boom), sleep=lambda s: None, backoff=0, retries=3))
    with pytest.raises(BaleNetworkError) as e:
        a.get_me()
    assert TOKEN not in str(e.value) and "ABC-DEF" not in str(e.value) and calls["n"] == 4      # idempotent call: retried
    f = tmp_path / "f.bin"
    f.write_bytes(b"x")
    calls["n"] = 0
    with pytest.raises(BaleNetworkError):
        a.send_document("@c", str(f))
    assert calls["n"] == 1                                                                         # upload: NOT retried


def test_upload_retried_when_connection_could_not_be_established(tmp_path):
    n = {"c": 0}
    fake = FakeBale()

    def h(req):
        n["c"] += 1
        if n["c"] == 1:
            raise httpx.ConnectError("refused")
        return fake.handle(req)
    a = BaleAPIAdapter(BaleClient(TOKEN, transport=httpx.MockTransport(h), sleep=lambda s: None, backoff=0, retries=2))
    f = tmp_path / "f.bin"
    f.write_bytes(b"data")
    assert a.send_document("@c", str(f)) > 0 and n["c"] == 2


def test_polling_handles_updates_once_and_persists_offset(ctx, fake_bale):
    got = []
    bus = events.EventBus()
    fake_bale.webhook_url = "https://old.example/hook"
    p = BalePoller(ctx.runtime.adapter(), got.append, ctx.repo, bus, lambda: 0.01)
    fake_bale.queue_message(5, "hello")
    fake_bale.queue_message(6, "again")
    assert p.poll_once() == 2 and [m.text for m in got] == ["hello", "again"]
    assert p.poll_once() == 0 and len(got) == 2                    # offset advanced -> no redelivery
    assert fake_bale.offsets[-1] == 3
    p.start()
    import time
    for _ in range(50):
        if p.status == "connected":
            break
        time.sleep(0.05)
    p.stop()
    assert p.status == "stopped" and fake_bale.webhook_url == ""     # webhook switched off for getUpdates


def test_poller_stops_on_invalid_token_and_reports_disconnect(ctx):
    seen = []
    bus = events.EventBus()
    bus.subscribe("*", lambda n, **k: seen.append(n))
    bad = adapter(FakeBale(token="1:other-token-other-token"))
    p = BalePoller(bad, lambda m: None, ctx.repo, bus, lambda: 0.01)
    p._run()
    assert p.status == "error" and events.CONNECTION_ERROR in seen


def test_poller_reports_disconnect_after_repeated_network_failures(ctx):
    seen = []
    bus = events.EventBus()
    bus.subscribe("*", lambda n, **k: seen.append(n))

    def boom(req):
        raise httpx.ConnectError("down")
    a = BaleAPIAdapter(BaleClient(TOKEN, transport=httpx.MockTransport(boom), sleep=lambda s: None, backoff=0, retries=0))
    p = BalePoller(a, lambda m: None, ctx.repo, bus, lambda: 0.01, fail_threshold=2)
    p.start()
    import time
    for _ in range(100):
        if events.BOT_DISCONNECTED in seen:
            break
        time.sleep(0.05)
    p.stop()
    assert seen.count(events.BOT_DISCONNECTED) == 1
