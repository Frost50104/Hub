"""Send a Web Push to one employee's subscriptions via pywebpush.

Subscriptions returning 404/410 from the push transport are deleted from
`push_subscriptions` (standard sanitization — the browser dropped them).

**Ключ уходит в pywebpush ОБЪЕКТОМ `Vapid`, а не текстом и не путём.** Так
библиотека разбирает этот аргумент (`pywebpush/__init__.py`): объект `Vapid01`
берётся как есть, путь читается через `Vapid.from_file`, а ЛЮБАЯ другая строка
уходит в `Vapid.from_string` — а он PEM с заголовками не понимает вовсе и
падает с «ASN.1 parsing error». Именно на этом web push в Hub молча не
доставлялся с 29 июля по 26 августа: сюда передавали содержимое PEM-файла.
Путь тоже сработал бы, но заставлял бы читать файл с диска на каждую отправку;
объект вдобавок проверяется один раз при старте (`app/main.py::lifespan`).
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid, Vapid01
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.push_subscription import PushSubscription

log = structlog.get_logger("push_sender")

_DEAD_STATUSES = {404, 410}
# Транспорт без таймаута держал бы поток из общего executor'а `asyncio.to_thread`
# — того самого, где чистятся блобы вложений. Зависший push-хост блокировал бы
# не только уведомления.
_SEND_TIMEOUT_SEC = 10.0

_vapid_cache: Vapid01 | None = None
_vapid_loaded = False
# Почему пуш выключен — для `/api/health/push`. Одного `None` мало: «ключ не
# настроен» и «ключ не от того публичного» лечатся по-разному.
_vapid_status = "absent"


def reset_vapid_cache() -> None:
    """Сбросить кеш ключа. Нужен тестам и после ротации ключа."""
    global _vapid_cache, _vapid_loaded, _vapid_status
    _vapid_cache = None
    _vapid_loaded = False
    _vapid_status = "absent"


def vapid_status() -> str:
    """`ok` | `absent` | `invalid` | `mismatch` — состояние ключа."""
    load_vapid()
    return _vapid_status


def _public_b64(vapid: Vapid01) -> str:
    """Публичный ключ пары в том же виде, в каком его получает браузер."""
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_vapid() -> Vapid01 | None:
    """Загрузить ключ ОДИН раз и отдать объект `Vapid` (не текст, не путь).

    `None` — ключа нет, он не читается или не совпадает с публичным ключом,
    который раздаётся браузерам: пуш выключается, всё остальное (включая
    in-app уведомления) продолжает работать.
    """
    global _vapid_cache, _vapid_loaded, _vapid_status
    if _vapid_loaded:
        return _vapid_cache
    _vapid_loaded = True
    settings = get_settings()
    path = settings.vapid_private_key_path
    if path is None:
        log.warning("vapid.not_configured")
        _vapid_status = "absent"
        return None
    # Существование файла проверяем САМИ. `Vapid.from_file` при отсутствии
    # файла молча генерирует НОВУЮ пару и пишет её на диск — а публичный ключ
    # в env остаётся прежним, и все выданные подписки становятся мусором.
    # Пропавший ключ обязан быть громкой ошибкой, а не тихой ротацией.
    if not Path(path).is_file():
        log.error("vapid.key_file_missing", path=str(path))
        _vapid_status = "absent"
        return None
    try:
        vapid = Vapid.from_file(private_key_file=str(Path(path)))
    except Exception as e:  # noqa: BLE001 — битый ключ не повод падать
        log.error("vapid.invalid", path=str(path), err=str(e))
        _vapid_status = "invalid"
        return None
    # Приватный ключ обязан быть парой к публичному из env: иначе браузер
    # отвергнет подпись, а мы будем считать отправку успешной.
    expected = settings.vapid_public_key
    if expected and _public_b64(vapid) != expected.rstrip("="):
        log.error("vapid.public_key_mismatch", path=str(path))
        _vapid_status = "mismatch"
        return None
    _vapid_cache = vapid
    _vapid_status = "ok"
    return _vapid_cache


def _send_blocking(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, Any],
    vapid: Vapid01,
    vapid_subject: str,
) -> int:
    """Returns HTTP status from the push transport. Raises on transport errors."""
    response = webpush(
        subscription_info={
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        },
        data=json.dumps(payload),
        vapid_private_key=vapid,
        # Словарь claims собирается ЗДЕСЬ, на каждую подписку заново, и это не
        # стилистика: pywebpush дописывает в переданный словарь `aud` (домен
        # endpoint'а) и `exp`. Один общий словарь подписал бы вторую подписку
        # адресом первой — Apple и FCM живут на разных доменах.
        vapid_claims={"sub": vapid_subject},
        timeout=_SEND_TIMEOUT_SEC,
    )
    return int(getattr(response, "status_code", 0))


@dataclass(frozen=True)
class PushResult:
    """Что стало с отправкой — для `/api/push/test` и для логов.

    `subscriptions` считается ДО гейта свежести: человеку, у которого подписка
    протухла, важно услышать «устройство давно не подтверждалось», а не
    «подписок нет».
    """

    subscriptions: int
    sent: int
    removed: int
    failed: int
    skipped_stale: int = 0
    no_vapid: bool = False


def describe_push_result(result: PushResult) -> str:
    """Объяснить итог отправки человеку.

    Пять разных причин «уведомление не пришло» выглядят для человека одинаково,
    поэтому каждая обязана называть себя: не настроен сервер, нет подписки,
    подписка протухла, устройство её отозвало, транспорт отказал. Текст —
    чистая функция, чтобы формулировки были под тестом, а не собирались
    тернарником в разметке.
    """
    if result.no_vapid:
        return "Уведомления не настроены на сервере — сообщите администратору."
    if result.subscriptions == 0:
        return "Это устройство не подписано на уведомления — включите их выше."
    if result.sent > 0:
        tail = ""
        if result.removed:
            tail = f" Ещё {result.removed} устройство больше не принимает уведомления."
        return f"Отправлено: {result.sent} — проверьте экран устройства.{tail}"
    if result.removed:
        return (
            "Устройство больше не принимает уведомления — подпишитесь заново "
            "на этом устройстве."
        )
    if result.skipped_stale:
        return (
            "Подписка давно не подтверждалась — откройте приложение на том "
            "устройстве и вернитесь сюда."
        )
    return "Не удалось отправить — попробуйте позже или сообщите администратору."


async def send_to_employee(
    session: AsyncSession,
    *,
    employee_id: UUID,
    payload: dict[str, Any],
) -> PushResult:
    """Fan-out push to every subscription this employee has, in parallel.

    Updates `last_seen_at` on success; deletes the row on 404/410.
    Silent no-op if VAPID isn't configured (no key file / no subject) —
    in-app notification still works via dispatcher's INSERT.
    """
    settings = get_settings()
    vapid = load_vapid()
    if vapid is None or not settings.vapid_subject:
        log.debug("push.skip_no_vapid", employee_id=str(employee_id))
        return PushResult(subscriptions=0, sent=0, removed=0, failed=0, no_vapid=True)

    all_subs = (
        await session.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
                PushSubscription.last_seen_at,
            ).where(PushSubscription.employee_id == employee_id)
        )
    ).all()
    # Гейт свежести (паттерн Desk): подписка живёт ровно столько, сколько её
    # подтверждают запуском PWA. Без гейта в таблице копятся endpoint'ы
    # удалённых приложений, на которые транспорт отвечает вечными отказами.
    cutoff = datetime.now(UTC) - timedelta(days=settings.push_freshness_days)
    subs = [row for row in all_subs if row.last_seen_at > cutoff]
    stale = len(all_subs) - len(subs)
    if not subs:
        return PushResult(
            subscriptions=len(all_subs),
            sent=0,
            removed=0,
            failed=0,
            skipped_stale=stale,
        )

    async def _one(row: Any) -> tuple[int, int]:
        try:
            status = await asyncio.to_thread(
                _send_blocking,
                endpoint=row.endpoint,
                p256dh=row.p256dh,
                auth=row.auth,
                payload=payload,
                vapid=vapid,
                vapid_subject=settings.vapid_subject,
            )
            return row.id, status
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else 0
            log.warning(
                "push.webpush_error",
                sub_id=row.id,
                status=status,
                err=str(e),
            )
            return row.id, status
        except Exception as e:  # noqa: BLE001 — transport/network failure
            log.warning("push.send_failed", sub_id=row.id, err=str(e))
            return row.id, 0

    results = await asyncio.gather(*(_one(s) for s in subs))
    dead_ids = [sub_id for sub_id, status in results if status in _DEAD_STATUSES]
    alive_ids = [
        sub_id
        for sub_id, status in results
        if 200 <= status < 300 and sub_id not in dead_ids
    ]
    if dead_ids:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.id.in_(dead_ids))
        )
    if alive_ids:
        await session.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(alive_ids))
            .values(last_seen_at=func.now())
        )
    await session.commit()
    # Успех логируется НАРАВНЕ с отказом. Прежде писался только `warning`, и
    # пустой журнал читался как «всё хорошо» — ровно так поломка транспорта
    # прожила месяц.
    log.info(
        "push.sent",
        employee_id=str(employee_id),
        sent=len(alive_ids),
        removed=len(dead_ids),
        stale=stale,
    )
    return PushResult(
        subscriptions=len(all_subs),
        sent=len(alive_ids),
        removed=len(dead_ids),
        failed=len(results) - len(alive_ids) - len(dead_ids),
        skipped_stale=stale,
    )
