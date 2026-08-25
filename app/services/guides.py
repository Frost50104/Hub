"""Инструкции по работе в Hub: какая кому и как отдаётся.

Две готовые автономные HTML-страницы лежат в `guides/` в корне проекта и
уезжают на сервер обычным rsync'ом деплоя (`/opt/signaris-hub[-staging]/guides/`).

**Почему подписанная ссылка, а не статика в бандле.** Внутри инструкции —
реальные экраны продукта: список рейтинга с ФИО коллег, должностями и адресами
точек. Публичный `/guides/employee.html` означал бы ПДн сотрудников по
угадываемому адресу. Bearer в новой вкладке не работает (навигация не несёт
заголовков) — тот же довод, по которому существуют подписанные URL медиа
уроков; переиспользуем ту же подпись (`learn_media.issue_token`), но с другим
ключом сообщения, чтобы подпись на медиа нельзя было предъявить инструкции.

Ссылка — capability: кто угодно с URL откроет её до конца TTL, и админ может
переслать сотруднику админскую инструкцию. Для документа это принято
сознательно; чтобы URL не оседал в логах, `/api/guides/` исключён из
access_log (`map $request_uri $hub_log_request` в nginx).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.services.learn_media import issue_token, verify_token

__all__ = [
    "GUIDE_FILES",
    "GuideLink",
    "guide_file_path",
    "guides_for_role",
    "verify_guide_signature",
]

# Имена файлов фиксированы: backend-rsync идёт БЕЗ `--delete`, и переименование
# оставило бы на сервере мусор старого имени.
GUIDE_FILES: dict[str, str] = {
    "employee": "employee.html",
    "admin": "admin.html",
}

_TITLES: dict[str, str] = {
    "employee": "Инструкция сотрудника",
    "admin": "Инструкция администратора",
}

# Ключ подписи. Префикс обязателен: без него подпись, выданную на медиа с
# id «employee», можно было бы предъявить инструкции.
def _sign_key(kind: str) -> str:
    return f"guide:{kind}"


class GuideLink(BaseModel):
    kind: str
    title: str
    url: str


def guides_for_role(hub_role: str | None) -> list[GuideLink]:
    """Что показывать в «Учётной записи».

    Решение владельца 25.08: hub-admin видит СВОЮ инструкцию первой и рядом
    сотрудницкую (он объясняет её людям), остальные — только сотрудницкую.
    У principal без hub-роли инструкций нет: он и Hub не видит.
    """
    if hub_role is None:
        return []
    kinds = ("admin", "employee") if hub_role == "admin" else ("employee",)
    return [
        GuideLink(kind=kind, title=_TITLES[kind], url=_signed_url(kind))
        for kind in kinds
    ]


def _signed_url(kind: str) -> str:
    exp, sig = issue_token(_sign_key(kind), get_settings().media_url_ttl_sec)
    return f"/api/guides/{kind}?e={exp}&s={sig}"


def verify_guide_signature(kind: str, exp: int, sig: str) -> bool:
    return kind in GUIDE_FILES and verify_token(_sign_key(kind), exp, sig)


def guide_file_path(kind: str) -> Path:
    """Абсолютный путь к файлу инструкции на диске."""
    return Path(get_settings().guides_root) / GUIDE_FILES[kind]
