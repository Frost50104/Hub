"""Русское склонение числительных для текстов людям (уведомления, отчёты).

Зеркало клиентского `web/src/lib/typography.ts::plural`: число возвращается
ВМЕСТЕ со словом — не склеивать его с числом снаружи.
"""

from __future__ import annotations


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    """`ru_plural(5, "задача", "задачи", "задач")` → «5 задач»."""
    tail, hundred = abs(n) % 10, abs(n) % 100
    if tail == 1 and hundred != 11:
        word = one
    elif 2 <= tail <= 4 and not 12 <= hundred <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"
