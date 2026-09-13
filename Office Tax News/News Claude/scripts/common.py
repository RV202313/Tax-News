#!/usr/bin/env python3
"""Общие безопасные утилиты скриптов конвейера."""

import os
from pathlib import Path


def load_env(path: Path) -> None:
    """Загрузить простой KEY=VALUE файл без перезаписи переменных окружения."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
