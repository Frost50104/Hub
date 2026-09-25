"""Ответы сервисных ручек auth: машиночитаемый код рубильника в теле 404.

auth отличает «выгрузка выключена» от «ручки нет» кодом в теле 404. FastAPI
кладёт его в `detail` — фактическая форма `{"detail": {"code": "…"}}`
(ANSWER auth 25.09 §3.12: так отвечают и кадровые справочники 16d, и реестр
объектов 16c). Ранние контракты описывали плоское `{"code": "…"}`, и
`sites_sync` читал именно его — выключенный реестр уходил в журнал WARNING'ом
как «голый 404». Понимаем обе формы.

Голый 404 (ручки нет, опечатка в `base_url`, страница nginx) кода не несёт —
вызывающий обязан логировать его WARNING'ом с полным URL: иначе неверный адрес
неотличим от выключенного фида, и снимок молча не приезжает никогда.
"""

from __future__ import annotations

import httpx


def disabled_code(resp: httpx.Response) -> str | None:
    """Код рубильника из тела ответа auth или None, если кода нет.

    Не бросает ни на каком теле: не-JSON (страница nginx), JSON не-объект,
    строковый `detail` (`{"detail": "Not Found"}` — дефолтный 404 FastAPI).
    """
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    source = detail if isinstance(detail, dict) else body
    code = source.get("code")
    return code if isinstance(code, str) and code else None
