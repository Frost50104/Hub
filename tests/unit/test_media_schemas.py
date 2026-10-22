"""Конвейер видео (0066): флаги, схемы, зеркала и разбор размеров картинок —
то, что молча ломает деплой или открывает модуль там, где его не включали."""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.models.media import JOB_KINDS, JOB_PRIORITY
from app.schemas.media import (
    HEDRA_CENTS_PER_SEC,
    RESOLUTIONS,
    CleanupDefaults,
    MediaAdminSettingsPut,
)
from app.services.learn_settings import DEFAULTS
from app.services.media import gate
from app.services.media.images import aspect_ok, image_size

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED",
        "SIGNARIS_HUB_MEDIA_AVATAR_ENABLED",
        "SIGNARIS_HUB_HEDRA_API_KEY",
        "SIGNARIS_HUB_MEDIA_STT_URL",
        "SIGNARIS_HUB_MEDIA_STT_PROVIDER",
        "SIGNARIS_HUB_MEDIA_STT_API_KEY",
        "SIGNARIS_HUB_MEDIA_STT_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_module_is_off_by_default_on_both_levels(clean_env):
    s = get_settings()
    assert s.media_pipeline_enabled is False, "прод получает код с выключенным флагом"
    assert s.media_avatar_enabled is False
    assert s.media_stt_url is None, "дефолт указывал бы на ПРОД-STT из staging"
    assert DEFAULTS["media_pipeline_enabled"] is False
    assert gate.env_enabled() is False and gate.avatar_env_enabled() is False


def test_avatar_needs_flag_and_key(clean_env):
    clean_env.setenv("SIGNARIS_HUB_MEDIA_PIPELINE_ENABLED", "true")
    clean_env.setenv("SIGNARIS_HUB_MEDIA_AVATAR_ENABLED", "true")
    get_settings.cache_clear()
    assert gate.env_enabled() is True
    assert gate.avatar_env_enabled() is False, "без ключа Hedra гуся нет"
    clean_env.setenv("SIGNARIS_HUB_HEDRA_API_KEY", "key:secret")
    get_settings.cache_clear()
    assert gate.avatar_env_enabled() is True


def test_stt_is_configured_only_explicitly(clean_env):
    assert gate.stt_configured() is False
    clean_env.setenv("SIGNARIS_HUB_MEDIA_STT_URL", "http://127.0.0.1:5071")
    get_settings.cache_clear()
    assert gate.stt_configured() is True
    clean_env.setenv("SIGNARIS_HUB_MEDIA_STT_PROVIDER", "openai")
    get_settings.cache_clear()
    assert gate.stt_configured() is False, "удалённому провайдеру нужны ключ и адрес"
    clean_env.setenv("SIGNARIS_HUB_MEDIA_STT_API_KEY", "k")
    clean_env.setenv("SIGNARIS_HUB_MEDIA_STT_BASE_URL", "https://stt.example/v1")
    get_settings.cache_clear()
    assert gate.stt_configured() is True


def test_settings_put_forbids_extra_and_validates_values():
    assert MediaAdminSettingsPut().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        MediaAdminSettingsPut(foo=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MediaAdminSettingsPut(avatar_resolution="4k")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        MediaAdminSettingsPut(avatar_monthly_minutes_cap=-1)
    with pytest.raises(ValidationError):
        MediaAdminSettingsPut(cleanup_defaults=CleanupDefaults(min_pause_sec=0.1))
    with pytest.raises(ValidationError):
        CleanupDefaults(denoise="magic")  # type: ignore[arg-type]
    ok = MediaAdminSettingsPut(enabled=True, glossary="UPPETIT, iiko")
    assert ok.model_dump(exclude_unset=True) == {"enabled": True, "glossary": "UPPETIT, iiko"}


def test_defaults_in_learn_settings_pass_their_own_schemas():
    CleanupDefaults(**DEFAULTS["media_cleanup_defaults"])
    assert DEFAULTS["media_avatar_resolution"] in RESOLUTIONS
    assert set(HEDRA_CENTS_PER_SEC) == set(RESOLUTIONS)


def test_job_kinds_mirror_migration_and_priorities():
    assert set(JOB_PRIORITY) == set(JOB_KINDS)
    text = (ROOT / "migrations" / "versions" / "0066_media_pipeline.py").read_text("utf-8")
    block = text[
        text.index('name="ck_media_jobs_kind"') - 400 : text.index('name="ck_media_jobs_kind"')
    ]
    kinds_in_migration = set(re.findall(r"'([a-z_]+)'", block))
    assert kinds_in_migration == set(JOB_KINDS), "CHECK миграции и JOB_KINDS меняются парой"


def _png(w: int, h: int) -> bytes:
    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    return head + struct.pack(">II", w, h) + b"\x08\x06"


def _jpeg(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", h, w) + b"\x03"
    return b"\xff\xd8" + app0 + sof0 + b"\x00" * 16


def _webp_vp8x(w: int, h: int) -> bytes:
    body = b"WEBPVP8X" + struct.pack("<I", 10) + b"\x00" * 4
    body += (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_image_size_reads_png_jpeg_webp_headers():
    assert image_size(_png(1920, 1080)) == (1920, 1080)
    assert image_size(_jpeg(1280, 720)) == (1280, 720)
    assert image_size(_webp_vp8x(1600, 900)) == (1600, 900)
    assert image_size(b"not an image at all") is None
    assert image_size(b"\x89PNG\r\n\x1a\n") is None


def test_aspect_check_allows_five_percent():
    assert aspect_ok((1920, 1080))
    assert aspect_ok((1920, 1130)), "в пределах 5 % — принимаем"
    assert not aspect_ok((1920, 1200))
    assert not aspect_ok((1024, 1024))
    assert not aspect_ok((100, 0))
