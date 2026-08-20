#!/usr/bin/env python3
"""Собрать staging-вариант systemd-юнита из прод-образца.

Зачем скрипт вместо `sed`: правка «в уме» трижды давала юнит, который
назывался staging, а смотрел в ПРОД — то есть читал `/opt/signaris-hub/.env`.
Ловушки настоящие: BSD-sed на macOS не знает `\\b`; `WorkingDirectory` идёт без
слеша на конце и не попадает под замену `/opt/signaris-hub/`; номер порта
встречается в комментарии-инструкции.

Поэтому здесь один проход и ЖЁСТКАЯ проверка: ни одной некомментарной строки
с прод-путём или прод-портом в результате остаться не может.

    python3 ops/systemd/make-staging-unit.py signaris-hub-stt.service 5071 5072
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROD = "/opt/signaris-hub"
STAGING = "/opt/signaris-hub-staging"


def build(text: str, prod_port: str, staging_port: str) -> str:
    out = text.replace(PROD, STAGING).replace(
        f"--port {prod_port}", f"--port {staging_port}"
    )
    bad = [
        ln
        for ln in out.splitlines()
        if not ln.strip().startswith("#")
        and (re.search(rf"{re.escape(PROD)}(?!-staging)", ln) or prod_port in ln)
    ]
    if bad:
        raise SystemExit(f"остались прод-значения: {bad}")
    return out


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    name, prod_port, staging_port = sys.argv[1], sys.argv[2], sys.argv[3]
    src = Path(__file__).parent / name
    result = build(src.read_text(encoding="utf-8"), prod_port, staging_port)
    sys.stdout.write(result)


if __name__ == "__main__":
    main()
