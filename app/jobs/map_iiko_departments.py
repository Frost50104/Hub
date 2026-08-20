"""Сопоставить точки Hub с «Торговыми предприятиями» iiko.

Зачем скрипт, а не UPDATE руками: сопоставление — это про ДЕНЬГИ. Ошибка
здесь показывает управляющему выручку и списания ЧУЖОЙ точки, и заметить это
почти невозможно. Поэтому правила консервативны, а результат по умолчанию
только печатается:

    python -m app.jobs.map_iiko_departments            # сухой прогон
    python -m app.jobs.map_iiko_departments --apply    # записать

Как матчим (по убыванию надёжности):

1. **Точное совпадение нормализованных имён.** Нормализация: нижний регистр,
   ё→е, выкидываются служебные «д.», «к.», «корп.», «кор.», «стр.», знаки
   препинания, лишние пробелы.
2. **Улица + номер дома, и в iiko такой ровно ОДИН.** Именно так «Ветеранов
   185» сходится с «Ветеранов д.185 к2», а «Кораблестроителей 32А» — с
   «Кораблестроителей 32/3А». Если кандидатов несколько — НЕ угадываем.

Всё остальное печатается как несопоставленное: пустое поле честнее неверного.
Уже заполненные значения не трогаются без `--force` — руками поставленное
соответствие важнее эвристики.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import bypass_session_factory
from app.models.org import Store
from app.services.iiko.client import IikoClient
from app.services.iiko.reports import F_AMOUNT, F_DEPARTMENT

# Служебные обозначения адреса: в Hub их пишут не так, как в iiko.
_NOISE = re.compile(
    r"\b(д|дом|к|кор|корп|корпус|стр|строение|литера|лит|ул|улица|пр|пер|наб|б)\b\.?",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[.,/\\\-—–()]+")


def normalize(name: str) -> str:
    s = name.lower().replace("ё", "е")
    s = _PUNCT.sub(" ", s)
    s = _NOISE.sub(" ", s)
    return " ".join(s.split())


def street_and_house(name: str) -> tuple[str, str] | None:
    """(улица, первый номер дома) — грубый, но устойчивый ключ адреса."""
    norm = normalize(name)
    match = re.search(r"\d+", norm)
    if not match:
        return None
    street = norm[: match.start()].strip()
    if not street:
        return None
    return street, match.group(0)


async def fetch_departments() -> list[str]:
    s = get_settings()
    if not (s.iiko_base_url and s.iiko_login and s.iiko_password):
        raise SystemExit("iiko не настроен: задайте SIGNARIS_HUB_IIKO_* в .env")
    today = date.today()
    async with IikoClient(
        base_url=s.iiko_base_url,
        login=s.iiko_login,
        password=s.iiko_password,
        verify_ssl=s.iiko_verify_ssl,
        timeout=90,
    ) as client:
        rows = await client.olap(
            report_type="SALES",
            date_from=today - timedelta(days=30),
            date_to=today,
            group_by=[F_DEPARTMENT],
            aggregate=[F_AMOUNT],
        )
    return sorted({str(r.get(F_DEPARTMENT) or "").strip() for r in rows if r.get(F_DEPARTMENT)})


def match(stores: list[Store], departments: list[str]) -> dict[str, list]:
    by_norm = {normalize(d): d for d in departments}
    by_address: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in departments:
        key = street_and_house(d)
        if key:
            by_address[key].append(d)

    result: dict[str, list] = {"exact": [], "address": [], "ambiguous": [], "none": []}
    for store in stores:
        exact = by_norm.get(normalize(store.name))
        if exact:
            result["exact"].append((store, exact))
            continue
        key = street_and_house(store.name)
        candidates = by_address.get(key, []) if key else []
        if len(candidates) == 1:
            result["address"].append((store, candidates[0]))
        elif len(candidates) > 1:
            result["ambiguous"].append((store, candidates))
        else:
            result["none"].append((store, None))
    return result


async def run(*, apply: bool, force: bool) -> int:
    departments = await fetch_departments()
    print(f"«Торговых предприятий» в iiko за 30 дней: {len(departments)}")

    async with bypass_session_factory()() as db:
        stores = list(
            (await db.execute(select(Store).where(Store.archived_at.is_(None)))).scalars().all()
        )
        print(f"активных точек в Hub: {len(stores)}\n")

        todo = [s for s in stores if force or not s.iiko_department]
        skipped = len(stores) - len(todo)
        if skipped:
            print(f"пропущено (уже заполнено): {skipped}\n")

        found = match(todo, departments)
        for store, dep in found["exact"]:
            print(f"  ТОЧНО     {store.name!r} → {dep!r}")
        for store, dep in found["address"]:
            print(f"  ПО АДРЕСУ {store.name!r} → {dep!r}")
        for store, cands in found["ambiguous"]:
            print(f"  НЕЯСНО    {store.name!r}: {cands} — заполните руками")
        for store, _ in found["none"]:
            print(f"  НЕТ ПАРЫ  {store.name!r}")

        pairs = found["exact"] + found["address"]
        print(f"\nитого сопоставимо: {len(pairs)}, требует рук: "
              f"{len(found['ambiguous']) + len(found['none'])}")
        if not apply:
            print("\nсухой прогон, ничего не записано — повторите с --apply")
            return 0
        for store, dep in pairs:
            store.iiko_department = dep
        await db.commit()
        print(f"\nзаписано: {len(pairs)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="записать в БД")
    parser.add_argument(
        "--force", action="store_true", help="перезаписать уже заполненные"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(apply=args.apply, force=args.force)))


if __name__ == "__main__":
    main()
