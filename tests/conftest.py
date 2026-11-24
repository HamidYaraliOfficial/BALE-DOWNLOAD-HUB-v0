import os
import socket
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.application import AppContext
from tests.helpers import LocalServer, FakeBale, TOKEN


@pytest.fixture(autouse=True)
def _isolated_secret_registry():
    from app.core.logger import clear_secrets
    clear_secrets()
    yield
    clear_secrets()


@pytest.fixture(scope="session")
def server():
    with LocalServer() as s:
        yield s


@pytest.fixture
def fake_bale():
    return FakeBale()


def make_ctx(tmp_path, fake, allow_private=True, resolver=None, **settings):
    ctx = AppContext(home=tmp_path, bale_transport=fake.transport(), allow_private=allow_private,
                     resolver=resolver, use_keyring=False)
    patch = {"download": {"segment_min_mb": 1, "min_free_disk_mb": 1, "retry_backoff_s": 0.1, "retry_count": 1,
                          "directory": str(tmp_path / "dl")},
             "bale": {"retry_backoff_s": 0.1, "retry_count": 1, "polling_interval_s": 0.5},
             "cleanup": {"cleanup_on_startup": False}}
    for k, v in settings.items():
        patch.setdefault(k, {}).update(v)
    ctx.sm.update(patch)
    ctx.runtime.set_token(TOKEN)
    if not ctx.repo.list_channels():
        ctx.repo.add_channel("@testchan", "Test Channel", "testchan")
    return ctx


@pytest.fixture
def ctx(tmp_path, fake_bale):
    c = make_ctx(tmp_path, fake_bale)
    c.downloads.start()
    yield c
    c.shutdown()


def wait_status(ctx, job_id, statuses, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = ctx.repo.get_job(job_id)
        if j and j["status"] in statuses:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job stuck in {ctx.repo.get_job(job_id)['status']}, wanted {statuses}")
