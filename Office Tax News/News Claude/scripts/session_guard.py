#!/usr/bin/env python3
"""Локальная межпроцессная блокировка существующей Telethon-session."""

from __future__ import annotations

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

# Try importing fcntl (Unix) or msvcrt (Windows)
try:
    import fcntl
    _has_fcntl = True
except ImportError:
    _has_fcntl = False

try:
    import msvcrt
    _has_msvcrt = True
except ImportError:
    _has_msvcrt = False


def require_private_session(session_path: Path) -> Path:
    """Fail closed unless an existing session is private to its owner."""
    path = Path(session_path).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("Существующая Telethon-session не найдена; новая не создаётся")
    
    # Permission checks are only applicable to POSIX/Unix environments
    if sys.platform != "win32":
        metadata = path.stat()
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise RuntimeError("Telethon-session не принадлежит текущему OS-пользователю")
        mode = stat.S_IMODE(metadata.st_mode)
        if mode & 0o077:
            raise RuntimeError(
                f"Telethon-session имеет небезопасные права {mode:04o}; требуется 0600 или строже"
            )
    return path


@contextmanager
def exclusive_session_lock(session_path: Path):
    """Сериализовать клиентов проекта без блокировки sqlite-файла session."""
    session = require_private_session(session_path)
    lock_path = session.with_name(session.name + ".codex.lock")
    handle = lock_path.open("a+b")
    try:
        if _has_fcntl:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Telethon-session уже зарезервирована другим процессом") from exc
        elif _has_msvcrt:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except (OSError, IOError) as exc:
                raise RuntimeError("Telethon-session уже зарезервирована другим процессом") from exc
        yield
    finally:
        try:
            if _has_fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif _has_msvcrt:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
        finally:
            handle.close()
