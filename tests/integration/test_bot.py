import time

import pytest

from app.integrations.bale.adapter import IncomingMessage
from tests.conftest import make_ctx, wait_status
from tests.helpers import FakeBale


def msg(uid, text, chat_type="private", cid=None):
    return IncomingMessage(update_id=1, message_id=1, chat_id=cid or uid, chat_type=chat_type, user_id=uid,
                           username="u", first_name="F", text=text)


def replies(fake):
    return [m["text"] for m in fake.sent_messages]


def wait_replies(fake, n, timeout=15):
    end = time.time() + timeout
    while time.time() < end and len(fake.sent_messages) < n:
        time.sleep(0.05)
    return replies(fake)


@pytest.fixture
def bot_ctx(ctx):
    ctx.sm.update({"general": {"language": "en"}})
    ctx.repo.add_user(10, "Boss", "SUPER_ADMIN")
    ctx.repo.add_user(11, "Op", "OPERATOR")
    ctx.repo.add_user(12, "Viewer", "READ_ONLY")
    ctx.repo.add_user(13, "Adm", "ADMIN")
    return ctx


def test_unauthorised_user_gets_id_and_cannot_queue(bot_ctx, fake_bale, server):
    bot_ctx.bot.handle(msg(999, server.url("/small.pdf")))
    assert "999" in replies(fake_bale)[0] and "not authorised" in replies(fake_bale)[0]
    assert bot_ctx.repo.list_jobs() == []
    assert any(a["category"] == "security" and a["actor_id"] == 999 for a in bot_ctx.repo.list_activity())
    for _ in range(5):                                  # strangers are rate-limited: no spam replies
        bot_ctx.bot.handle(msg(999, "hi"))
    assert len(fake_bale.sent_messages) <= 2


def test_default_is_admin_only_blocked_and_removed_users_denied(bot_ctx, fake_bale):
    bot_ctx.repo.update_user(11, blocked=True)
    bot_ctx.bot.handle(msg(11, "/status"))
    assert "not authorised" in replies(fake_bale)[0]
    bot_ctx.repo.remove_user(12)
    bot_ctx.bot.handle(msg(12, "/status"))
    assert "not authorised" in replies(fake_bale)[1]


def test_operator_link_is_downloaded_and_published(bot_ctx, fake_bale, server):
    bot_ctx.bot.handle(msg(11, f"please get {server.url('/small.pdf')}"))
    out = wait_replies(fake_bale, 1)
    assert "Queued" in out[0] or "queued" in out[0].lower()
    job = bot_ctx.repo.list_jobs()[0]
    assert job["source"] == "bot" and job["requester_id"] == 11
    wait_status(bot_ctx, job["id"], ("completed",))
    assert fake_bale.sent and fake_bale.sent[0]["filename"] == "doc.pdf"


def test_invalid_and_private_links_rejected_in_chat(tmp_path):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake, allow_private=False, resolver=lambda h, p: ["93.184.216.34"])
    c.sm.update({"general": {"language": "en"}})
    c.repo.add_user(11, "Op", "OPERATOR")
    try:
        c.bot.handle(msg(11, "http://127.0.0.1/admin http://192.168.0.1/x"))
        out = wait_replies(fake, 1)[0]
        assert out.count("❌") == 2 and c.repo.list_jobs() == []
    finally:
        c.shutdown()


def test_roles_are_enforced(bot_ctx, fake_bale, server):
    bot_ctx.bot.handle(msg(12, "/status"))
    assert "Active" in replies(fake_bale)[-1]
    bot_ctx.bot.handle(msg(12, "/pause"))
    assert "role does not allow" in replies(fake_bale)[-1]
    bot_ctx.bot.handle(msg(12, server.url("/small.pdf")))
    wait_replies(fake_bale, 3)
    assert bot_ctx.repo.list_jobs() == []
    bot_ctx.bot.handle(msg(11, "/users"))
    assert "role does not allow" in replies(fake_bale)[-1]
    bot_ctx.bot.handle(msg(11, "/pause"))
    assert "role does not allow" in replies(fake_bale)[-1]            # whole-queue control is an admin action
    bot_ctx.bot.handle(msg(13, "/pause"))
    assert bot_ctx.downloads.queue.paused
    bot_ctx.bot.handle(msg(13, "/resume"))
    assert not bot_ctx.downloads.queue.paused
    assert any(a["action"] == "access_denied" for a in bot_ctx.repo.list_activity(category="security"))


def test_user_management_commands_respect_hierarchy(bot_ctx, fake_bale):
    bot_ctx.bot.handle(msg(13, "/adduser 500 operator"))
    assert bot_ctx.repo.get_user(500)["role"] == "OPERATOR"
    bot_ctx.bot.handle(msg(13, "/adduser 501 admin"))                  # an Admin cannot create admins
    assert bot_ctx.repo.get_user(501) is None
    bot_ctx.bot.handle(msg(13, "/block 10"))                           # nor touch a Super Admin
    assert not bot_ctx.repo.get_user(10)["blocked"]
    bot_ctx.bot.handle(msg(10, "/adduser 501 admin"))
    assert bot_ctx.repo.get_user(501)["role"] == "ADMIN"
    bot_ctx.bot.handle(msg(10, "/block 500"))
    assert bot_ctx.repo.get_user(500)["blocked"]
    bot_ctx.bot.handle(msg(500, "/status"))
    assert "not authorised" in replies(fake_bale)[-1]
    bot_ctx.bot.handle(msg(10, "/users"))
    assert "500" in replies(fake_bale)[-1] and "BLOCKED" in replies(fake_bale)[-1]


def test_rate_limit_per_user(bot_ctx, fake_bale):
    bot_ctx.sm.update({"security": {"rate_limit_per_min": 2}})
    for _ in range(4):
        bot_ctx.bot.handle(msg(11, "/status"))
    assert sum("Too many requests" in r for r in replies(fake_bale)) == 2


def test_group_and_channel_messages_are_ignored(bot_ctx, fake_bale):
    bot_ctx.bot.handle(msg(11, "/status", chat_type="group", cid=-5))
    bot_ctx.bot.handle(msg(11, "/status", chat_type="channel", cid=-6))
    assert fake_bale.sent_messages == []


def test_cancel_own_job_only(bot_ctx, fake_bale, server):
    bot_ctx.downloads.queue.pause_queue("t")
    j = bot_ctx.downloads.add_job(server.url("/small.pdf"), "bot", 11).job
    bot_ctx.repo.add_user(14, "Op2", "OPERATOR")
    bot_ctx.bot.handle(msg(14, f"/cancel {j['id'][:8]}"))
    assert "role does not allow" in replies(fake_bale)[-1]
    assert bot_ctx.repo.get_job(j["id"])["status"] == "waiting"
    bot_ctx.bot.handle(msg(11, f"/cancel {j['id'][:8]}"))
    assert bot_ctx.repo.get_job(j["id"])["status"] == "cancelled"
    bot_ctx.bot.handle(msg(11, "/queue"))
    assert "empty" in replies(fake_bale)[-1].lower()


def test_confirmation_mode(bot_ctx, fake_bale, server):
    bot_ctx.sm.update({"bale": {"require_confirmation": True}})
    bot_ctx.downloads.queue.pause_queue("t")
    bot_ctx.bot.handle(msg(11, server.url("/small.pdf")))
    out = wait_replies(fake_bale, 1)[0]
    assert "/confirm" in out and bot_ctx.repo.list_jobs() == []
    token = out.split("/confirm ")[1].split()[0]
    bot_ctx.bot.handle(msg(12, f"/confirm {token}"))                   # a different user cannot confirm it
    assert bot_ctx.repo.list_jobs() == []
    bot_ctx.bot.handle(msg(11, f"/confirm {token}"))
    assert len(bot_ctx.repo.list_jobs()) == 1


def test_batch_with_duplicate_and_unknown_command(bot_ctx, fake_bale, server):
    bot_ctx.downloads.queue.pause_queue("t")
    u = server.url("/small.pdf")
    bot_ctx.bot.handle(msg(11, f"{u} {u}#x {server.url('/pic.jpg')}"))
    out = wait_replies(fake_bale, 1)[0]
    assert out.count("✅") == 2 and "duplicate" in out
    bot_ctx.bot.handle(msg(11, "/nonsense"))
    assert "Unknown command" in replies(fake_bale)[-1]


def test_language_follows_settings(bot_ctx, fake_bale):
    bot_ctx.sm.update({"general": {"language": "fa"}})
    bot_ctx.bot.handle(msg(11, "/start"))
    assert "نقش" in replies(fake_bale)[-1]
