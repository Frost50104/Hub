"""Файлы конвейера: tmp под attachments_root, уборка сирот, публикация,
свободное место, host-wide замок."""

from __future__ import annotations

import os
import time
import uuid

import pytest

from app.config import get_settings
from app.services.media import storage


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "attachments_root", tmp_path)
    monkeypatch.setattr(s, "media_min_free_bytes", 0)
    monkeypatch.setattr(s, "media_tmp_max_age_hours", 1)
    return s


def test_tmp_dir_lives_under_tenant_media_folder(settings, tmp_path):
    tenant, job = uuid.uuid4(), uuid.uuid4()
    path = storage.make_tmp_dir(settings, tenant, job)
    assert path == tmp_path / str(tenant) / "learn" / "media" / ".tmp" / str(job)
    assert path.is_dir()
    storage.remove_tmp_dir(path)
    assert not path.exists()


def test_sweep_removes_only_old_job_dirs(settings, tmp_path):
    tenant = uuid.uuid4()
    old = storage.make_tmp_dir(settings, tenant, uuid.uuid4())
    fresh = storage.make_tmp_dir(settings, tenant, uuid.uuid4())
    stale = time.time() - 2 * 3600
    os.utime(old, (stale, stale))
    assert storage.sweep_orphan_tmp(settings) == 1
    assert not old.exists() and fresh.exists()
    assert storage.sweep_orphan_tmp(settings) == 0


def test_publish_moves_file_under_storage_key(settings, tmp_path):
    tenant, media = uuid.uuid4(), uuid.uuid4()
    src = tmp_path / "out.mp4"
    src.write_bytes(b"x" * 10)
    key = storage.derived_storage_key(tenant, media, "video.mp4")
    assert key == f"{tenant}/learn/media/{media}-video.mp4"
    dest = storage.publish(src, key)
    assert dest == tmp_path / key
    assert dest.read_bytes() == b"x" * 10 and not src.exists()


def test_stem_of_storage_key():
    media = uuid.uuid4()
    assert storage.stem_of_storage_key(f"t/learn/media/{media}-Zapis_1.mov", media) == "Zapis_1"
    assert storage.stem_of_storage_key(f"t/learn/media/{media}-.mov", media) == "video"
    # «Запись.mov» после ASCII-санитайзера — просто `mov`.
    assert storage.stem_of_storage_key(f"t/learn/media/{media}-mov", media) == "video"
    assert storage.stem_of_storage_key("weird.mp4", media) == "weird"


def test_ensure_free_space_raises_with_numbers(settings, monkeypatch):
    monkeypatch.setattr(storage, "check_free_space", lambda: 10 * 2**20)
    storage.ensure_free_space(settings, 5 * 2**20)
    with pytest.raises(storage.NoSpace) as exc:
        storage.ensure_free_space(settings, 20 * 2**20)
    assert exc.value.free == 10 * 2**20
    assert "мало места" in str(exc.value)


def test_host_lock_is_exclusive_per_file(tmp_path):
    path = tmp_path / "media.lock"
    first, second = storage.HostLock(path), storage.HostLock(path)
    assert first.acquire() and first.held
    assert first.acquire()  # повторный захват тем же замком — идемпотентен
    assert not second.acquire()
    first.release()
    assert not first.held
    assert second.acquire()
    second.release()
