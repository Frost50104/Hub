"""Пять отчётов iiko из макета ассистента.

Имена полей OLAP собраны ЗДЕСЬ и больше нигде — с явной отметкой, что
проверено на живом API, а что нет. Непроверенные сверяются с
`/reports/olap/columns` перед выгрузкой: пресет обязан падать внятным «поле
DishName недоступно», а не пустым графиком, который на экране неотличим от
«продаж не было».

Дельта считается вторым запросом за предыдущий период равной длины — в той
же сессии, чтобы не занимать второй слот лицензии.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from app.services.iiko.client import IikoClient, IikoError

# ─── Поля OLAP ──────────────────────────────────────────────────────────────
# ПРОВЕРЕНО на живом API (uppetit-co.iiko.it, iiko 9.2, 2026-06-02 в проекте
# Listen: выгрузка за 29.05 совпала с ручным xlsx до рубля).
F_DEPARTMENT = "Department"  # «Торговое предприятие» — точка
F_OPEN_TIME = "OpenTime"
F_ORDER_NUM = "OrderNum"
F_AMOUNT = "DishDiscountSumInt"  # «Сумма со скидкой»
F_DATE_FILTER = "OpenDate.Typed"  # фильтр периода, `to` эксклюзивна

# НЕ ПРОВЕРЕНО — стандартные имена iiko OLAP. Сверяются `validate_fields`.
F_DATE = "OpenDate.Typed"
F_DISH = "DishName"
F_QTY = "DishAmountInt"
F_ORDERS = "UniqOrderId.OrdersCount"
F_HOUR = "HourOpen"
F_TX_TYPE = "TransactionType"
F_TX_PRODUCT_CAT = "Product.Category"
F_TX_SUM = "Sum.ResignedSum"
F_TX_DATE = "DateTime.Typed"

VERIFIED: frozenset[str] = frozenset(
    {F_DEPARTMENT, F_OPEN_TIME, F_ORDER_NUM, F_AMOUNT, F_DATE_FILTER}
)

ReportKind = Literal["revenue", "avg", "items", "peak", "writeoff"]


@dataclass
class ReportSpec:
    key: str
    title: str
    chart: Literal["bars", "hours", "lists"]
    report_type: str
    group_by: list[str]
    # Без этих полей отчёт бессмыслен — их отсутствие обязано падать внятно.
    aggregate: list[str]
    # Украшения: их отсутствие деградирует одну плашку в «—», а не роняет
    # весь отчёт. Полосы выручки считаются по проверенному DishDiscountSumInt,
    # и ронять их из-за неточного имени счётчика чеков было бы неправильно.
    optional_aggregate: list[str] = field(default_factory=list)
    date_field: str = F_DATE_FILTER
    extra_filters: dict[str, Any] = field(default_factory=dict)


SPECS: dict[str, ReportSpec] = {
    "revenue": ReportSpec(
        key="revenue",
        title="Выручка по точкам",
        chart="bars",
        report_type="SALES",
        group_by=[F_DEPARTMENT],
        aggregate=[F_AMOUNT],
        optional_aggregate=[F_ORDERS],
    ),
    "avg": ReportSpec(
        key="avg",
        title="Средний чек и динамика",
        chart="bars",
        report_type="SALES",
        group_by=[F_DATE],
        aggregate=[F_AMOUNT, F_ORDERS],
    ),
    "items": ReportSpec(
        key="items",
        title="Продажи по позициям меню",
        chart="lists",
        report_type="SALES",
        group_by=[F_DISH],
        aggregate=[F_QTY],
        optional_aggregate=[F_AMOUNT],
    ),
    "peak": ReportSpec(
        key="peak",
        title="Часы пик по чекам",
        chart="hours",
        report_type="SALES",
        group_by=[F_HOUR],
        aggregate=[F_ORDERS],
    ),
    "writeoff": ReportSpec(
        key="writeoff",
        title="Списания и себестоимость",
        chart="bars",
        report_type="TRANSACTIONS",
        group_by=[F_TX_PRODUCT_CAT],
        aggregate=[F_TX_SUM],
        date_field=F_TX_DATE,
        # Тип проводки «Списание»: без фильтра в выгрузку попадут все
        # движения склада, и «списания» показали бы приход.
        extra_filters={F_TX_TYPE: {"filterType": "IncludeValues", "values": ["Списание"]}},
    ),
}

REPORT_ORDER: list[str] = ["revenue", "avg", "items", "peak", "writeoff"]


# ─── Форматирование (единое место, чтобы клиент только рисовал) ─────────────

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_WEEKDAYS = (
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
)


def fmt_money(value: float) -> str:
    """«1 042 300 ₽» — неразрывные пробелы, чтобы сумма не рвалась по строкам."""
    return f"{round(value):,}".replace(",", " ") + " ₽"


def fmt_big_money(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}".replace(".", ",") + " млн ₽"
    return fmt_money(value)


def fmt_delta(current: float, previous: float) -> tuple[str, bool]:
    """(«+11%», рост?). Ноль и отсутствие базы — нейтрально, не «падение»."""
    if previous <= 0:
        return ("—", True)
    pct = (current - previous) / previous * 100
    if abs(pct) < 0.5:
        return ("0%", True)
    sign = "+" if pct > 0 else "−"
    return (f"{sign}{abs(pct):.0f}%", pct > 0)


def fmt_period(date_from: date, date_to: date) -> str:
    if date_from == date_to:
        return f"{date_from.day} {_MONTHS[date_from.month - 1]}"
    if date_from.month == date_to.month:
        return f"{date_from.day}–{date_to.day} {_MONTHS[date_to.month - 1]}"
    return (
        f"{date_from.day} {_MONTHS[date_from.month - 1]} — "
        f"{date_to.day} {_MONTHS[date_to.month - 1]}"
    )


# ─── Разбор строк OLAP ──────────────────────────────────────────────────────


def _num(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _label(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return str(value).strip() if value not in (None, "") else "—"


def validate_fields(spec: ReportSpec, available: set[str]) -> None:
    """Сверить непроверенные поля пресета с живым списком колонок."""
    if not available:  # список не получили — не мешаем работать
        return
    missing = [
        f
        for f in (*spec.group_by, *spec.aggregate, spec.date_field)
        if f not in VERIFIED and f not in available
    ]
    if missing:
        raise IikoError(
            "iiko не знает поля " + ", ".join(missing) + " — отчёт «"
            + spec.title
            + "» нужно перенастроить (app/services/iiko/reports.py)"
        )


def _sum_by(rows: list[dict[str, Any]], key_field: str, value_field: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        out[_label(row, key_field)] = out.get(_label(row, key_field), 0.0) + _num(row, value_field)
    return out


# ─── Сборка отчётов ─────────────────────────────────────────────────────────


def _bars(
    current: dict[str, float],
    previous: dict[str, float],
    *,
    limit: int = 6,
    money: bool = True,
) -> list[dict[str, Any]]:
    """Полосы по убыванию. Рост — амбер, падение — нейтральный `--text2`:
    красный в дизайн-системе занят просрочкой и ошибками, и плохая неделя
    не должна выглядеть как сбой системы."""
    top = sorted(current.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    peak = max((v for _, v in top), default=0.0) or 1.0
    bars = []
    for name, value in top:
        delta, up = fmt_delta(value, previous.get(name, 0.0))
        bars.append(
            {
                "name": name,
                "sum": fmt_money(value) if money else f"{round(value)}",
                "pct": round(value / peak * 100),
                "delta": delta,
                "up": up,
            }
        )
    return bars


def _stat(label: str, value: str, positive: bool = False) -> dict[str, Any]:
    return {"label": label, "value": value, "positive": positive}


def build_payload(
    kind: str,
    rows: list[dict[str, Any]],
    prev_rows: list[dict[str, Any]],
    *,
    date_from: date,
    date_to: date,
    store_filter: str | None,
) -> dict[str, Any]:
    spec = SPECS[kind]
    period = fmt_period(date_from, date_to)
    scope = f" · {store_filter}" if store_filter else ""
    payload: dict[str, Any] = {
        "kind": kind,
        "title": spec.title,
        "chart": spec.chart,
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "subtitle": "",
        "stats": [],
        "bars": [],
        "hours": [],
        "top": [],
        "anti": [],
        "note": None,
    }

    if kind == "revenue":
        cur = _sum_by(rows, F_DEPARTMENT, F_AMOUNT)
        prev = _sum_by(prev_rows, F_DEPARTMENT, F_AMOUNT)
        total, total_prev = sum(cur.values()), sum(prev.values())
        checks = sum(_num(r, F_ORDERS) for r in rows)
        delta, up = fmt_delta(total, total_prev)
        payload["subtitle"] = f"{period}{scope} · точки с наибольшей выручкой"
        payload["stats"] = [
            _stat("Итог", fmt_big_money(total)),
            _stat("К прошлому периоду", delta, up),
            _stat("Средний чек", fmt_money(total / checks) if checks else "—"),
            _stat("Чеков", f"{round(checks):,}".replace(",", " ") if checks else "—"),
        ]
        payload["bars"] = _bars(cur, prev)
        losing = [b["name"] for b in payload["bars"] if not b["up"] and b["delta"] != "—"]
        if losing:
            payload["note"] = "Просадка: " + ", ".join(losing)

    elif kind == "avg":
        # Средний чек по дням недели: выручка дня / чеки дня.
        by_day: dict[str, float] = {}
        for row in rows:
            raw = str(row.get(F_DATE) or "")[:10]
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            checks = _num(row, F_ORDERS)
            if checks:
                by_day[_WEEKDAYS[day.weekday()]] = _num(row, F_AMOUNT) / checks
        prev_by_day: dict[str, float] = {}
        for row in prev_rows:
            raw = str(row.get(F_DATE) or "")[:10]
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            checks = _num(row, F_ORDERS)
            if checks:
                prev_by_day[_WEEKDAYS[day.weekday()]] = _num(row, F_AMOUNT) / checks
        total = sum(_num(r, F_AMOUNT) for r in rows)
        checks_total = sum(_num(r, F_ORDERS) for r in rows)
        prev_total = sum(_num(r, F_AMOUNT) for r in prev_rows)
        prev_checks = sum(_num(r, F_ORDERS) for r in prev_rows)
        avg = total / checks_total if checks_total else 0.0
        prev_avg = prev_total / prev_checks if prev_checks else 0.0
        delta, up = fmt_delta(avg, prev_avg)
        best = max(by_day.items(), key=lambda kv: kv[1], default=("—", 0.0))[0]
        payload["subtitle"] = f"{period}{scope} · по дням недели"
        payload["stats"] = [
            _stat("Средний чек", fmt_money(avg) if avg else "—"),
            _stat("К прошлому периоду", delta, up),
            _stat("Лучший день", best.lower()),
            _stat("Чеков", f"{round(checks_total):,}".replace(",", " ") if checks_total else "—"),
        ]
        ordered = {d: by_day[d] for d in _WEEKDAYS if d in by_day}
        payload["bars"] = _bars(ordered, prev_by_day, limit=7)

    elif kind == "items":
        qty = _sum_by(rows, F_DISH, F_QTY)
        total_qty = sum(qty.values()) or 1.0
        ranked = sorted(qty.items(), key=lambda kv: kv[1], reverse=True)
        payload["subtitle"] = f"{period}{scope} · {len(qty)} позиций, показаны крайние"
        payload["top"] = [
            {"name": n, "qty": f"{round(v):,}".replace(",", " ") + " шт",
             "share": f"{v / total_qty * 100:.1f}%".replace(".", ",")}
            for n, v in ranked[:5]
        ]
        payload["anti"] = [
            {"name": n, "qty": f"{round(v):,}".replace(",", " ") + " шт",
             "share": f"{v / total_qty * 100:.1f}%".replace(".", ",")}
            for n, v in ranked[-3:][::-1]
        ]
        top5 = sum(v for _, v in ranked[:5])
        weak = [n for n, v in ranked if v / total_qty * 100 < 0.4]
        payload["stats"] = [
            _stat("Позиций в продаже", str(len(qty))),
            _stat("Топ-5 дают", f"{top5 / total_qty * 100:.0f}% продаж"),
            _stat("Ниже 0,4%", f"{len(weak)}"),
            _stat("Продано", f"{round(total_qty):,}".replace(",", " ") + " шт"),
        ]
        if weak:
            payload["note"] = (
                f"{len(weak)} позиций дают меньше 0,4% продаж каждая — "
                "кандидаты на вывод из меню."
            )

    elif kind == "peak":
        by_hour: dict[int, float] = {}
        for row in rows:
            raw = row.get(F_HOUR)
            try:
                hour = int(str(raw).split(":")[0])
            except (TypeError, ValueError):
                continue
            by_hour[hour] = by_hour.get(hour, 0.0) + _num(row, F_ORDERS)
        if by_hour:
            lo, hi = min(by_hour), max(by_hour)
            peak_value = max(by_hour.values()) or 1.0
            payload["hours"] = [
                {
                    "label": str(h),
                    "pct": round(by_hour.get(h, 0.0) / peak_value * 100),
                }
                for h in range(lo, hi + 1)
            ]
            total_checks = sum(by_hour.values()) or 1.0
            busiest = sorted(by_hour.items(), key=lambda kv: kv[1], reverse=True)[:2]
            late = sum(v for h, v in by_hour.items() if h >= 19)
            payload["stats"] = [
                _stat("Главный пик", f"{busiest[0][0]:02d}:00"),
                _stat(
                    "Второй пик",
                    f"{busiest[1][0]:02d}:00" if len(busiest) > 1 else "—",
                ),
                _stat("Доля после 19:00", f"{late / total_checks * 100:.1f}%".replace(".", ",")),
                _stat("Чеков в пик/час", f"{round(peak_value)}"),
            ]
            if late / total_checks < 0.08:
                payload["note"] = (
                    "После 19:00 меньше 8% чеков — там имеет смысл сокращать смену, "
                    "а не усиливать."
                )
        payload["subtitle"] = f"{period}{scope} · распределение чеков по часам"

    elif kind == "writeoff":
        cur = _sum_by(rows, F_TX_PRODUCT_CAT, F_TX_SUM)
        prev = _sum_by(prev_rows, F_TX_PRODUCT_CAT, F_TX_SUM)
        cur = {k: abs(v) for k, v in cur.items()}
        prev = {k: abs(v) for k, v in prev.items()}
        total, prev_total = sum(cur.values()), sum(prev.values())
        delta, up = fmt_delta(total, prev_total)
        main = max(cur.items(), key=lambda kv: kv[1], default=("—", 0.0))[0]
        payload["subtitle"] = f"{period}{scope} · по категориям"
        payload["stats"] = [
            _stat("Списано", fmt_big_money(total)),
            _stat("К прошлому периоду", delta, not up),
            _stat("Категорий", str(len(cur))),
            _stat("Главная категория", main.lower()),
        ]
        payload["bars"] = _bars(cur, prev)

    return payload


async def fetch_report(
    client: IikoClient,
    kind: str,
    *,
    date_from: date,
    date_to: date,
    departments: list[str] | None = None,
    scope_label: str | None = None,
    check_columns: bool = True,
) -> dict[str, Any]:
    """Собрать отчёт: текущий период + предыдущий равной длины для дельты."""
    if kind not in SPECS:
        raise IikoError(f"Нет отчёта «{kind}»")
    spec = SPECS[kind]

    available: set[str] = set()
    if check_columns:
        try:
            available = set((await client.columns(spec.report_type)).keys())
        except IikoError:
            available = set()  # список колонок не обязателен для работы
        validate_fields(spec, available)

    # Необязательные поля просим, только если iiko их знает: иначе весь
    # запрос отвергается целиком из-за одной плашки.
    aggregate = list(spec.aggregate) + [
        f for f in spec.optional_aggregate if not available or f in available
    ]

    filters = dict(spec.extra_filters)
    if departments:
        # Один фильтр со списком, а не запрос на точку: у ТУ их до десятка,
        # и каждый лишний вызов — это время внутри одного слота лицензии.
        filters[F_DEPARTMENT] = {"filterType": "IncludeValues", "values": departments}

    rows = await client.olap(
        report_type=spec.report_type,
        date_from=date_from,
        date_to=date_to,
        group_by=spec.group_by,
        aggregate=aggregate,
        date_field=spec.date_field,
        extra_filters=filters,
    )
    span = (date_to - date_from).days + 1
    prev_rows = await client.olap(
        report_type=spec.report_type,
        date_from=date_from - timedelta(days=span),
        date_to=date_from - timedelta(days=1),
        group_by=spec.group_by,
        aggregate=aggregate,
        date_field=spec.date_field,
        extra_filters=filters,
    )
    return build_payload(
        kind,
        rows,
        prev_rows,
        date_from=date_from,
        date_to=date_to,
        store_filter=scope_label,
    )
