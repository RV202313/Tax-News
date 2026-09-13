#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слой состояния SQLite: элементы, публикации, прогоны, дедуп. Только stdlib."""

import difflib
import glob
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

# Относительный путь БД внутри --root (state/news_state.sqlite).
DB_RELPATH = os.path.join("state", "news_state.sqlite")

# Порог похожести заголовков для дедупликации (difflib.SequenceMatcher).
DUP_RATIO = 0.9
# Окно дедупликации по заголовкам, дней.
DUP_WINDOW_DAYS = 30

# Реестр «зеркал»: id(conn) -> (локальный рабочий путь, целевой путь на FUSE).
# Рабочая БД живёт на локальном /tmp (надёжный SQLite), после каждой записи
# копируется на целевую (возможно FUSE) папку state/. Это обходит 'disk I/O
# error', которым FUSE/сетевые ФС отвечают на журналирование/локи SQLite.
_MIRRORS = {}


class PersistenceError(RuntimeError):
    """Состояние нельзя безопасно прочитать или зафиксировать на целевой ФС."""


def db_path(root):
    """Абсолютный путь к целевому файлу БД (в state/ проекта)."""
    return os.path.join(root, DB_RELPATH)


def _local_work_path(dest_path):
    """Стабильный локальный путь рабочей копии БД для данного целевого пути."""
    h = hashlib.sha1(os.path.abspath(dest_path).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"newsflow_{h}.sqlite")


def now_iso():
    """Текущее время UTC в ISO8601 (для служебных таймстампов)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_title(title):
    """Нормализованный заголовок: casefold, схлопнуть пробелы, убрать пунктуацию по краям."""
    if not title:
        return ""
    t = title.casefold().strip()
    t = re.sub(r"\s+", " ", t)
    # Убрать невидимые/типографские кавычки и лишние знаки, оставить буквенно-цифровое ядро.
    t = re.sub(r"[\"'«»„“”«»]", "", t)
    return t.strip()


def connect(root):
    """Открыть БД (через локальное зеркало) и гарантировать схему.

    Рабочая копия БД создаётся на локальном /tmp — там SQLite надёжен.
    Существующее состояние из state/ (возможно FUSE) при старте копируется
    в рабочую копию; после каждой записи рабочая копия копируется обратно
    (см. _sync). Это устраняет 'disk I/O error', которым FUSE отвечает на
    журналирование/локи SQLite при прямой работе с файлом на монтировании.
    """
    dest = db_path(root)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    work = _local_work_path(dest)

    # Подтянуть существующее состояние из целевого файла в рабочую копию.
    if os.path.exists(dest):
        try:
            shutil.copyfile(dest, work)
        except OSError as exc:
            # Нечитаемую цель НЕЛЬЗЯ заменять пустой БД: это как раз сценарий
            # потери истории, ради которого существует локальное зеркало.
            _safe_remove(work)
            _log_sync_error(dest, exc)
            raise PersistenceError(
                f"Не удалось прочитать существующую БД {dest}; цель не изменена"
            ) from exc
    else:
        # Свежий старт: убрать возможный устаревший локальный файл.
        _safe_remove(work)

    def _open(fresh=False):
        if fresh:
            _safe_remove(work)
        c = sqlite3.connect(work)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=MEMORY")
            c.execute("PRAGMA synchronous=OFF")
            c.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.Error:
            pass
        _MIRRORS[id(c)] = (work, dest)
        try:
            _ensure_schema(c)
        except Exception:
            _MIRRORS.pop(id(c), None)
            c.close()
            raise
        return c

    try:
        conn = _open(fresh=False)
    except sqlite3.DatabaseError:
        # Целевой файл повреждён (частичная запись предыдущего прогона).
        # СНАЧАЛА бэкапим цель (не теряем историю дедупа), только потом
        # пересоздаём рабочую копию с нуля; следующий _sync перезапишет цель,
        # но восстановимая копия уже сохранена в state/*.bak-*.
        backup = _backup_dest(dest)
        if not backup:
            _safe_remove(work)
            raise PersistenceError(
                f"БД {dest} повреждена, а безопасный бэкап создать не удалось; "
                "пересоздание запрещено"
            )
        conn = _open(fresh=True)
    if not _sync(conn):
        _MIRRORS.pop(id(conn), None)
        conn.close()
        raise PersistenceError(f"Не удалось атомарно зафиксировать БД в {dest}")
    return conn


def _safe_remove(path):
    """Удалить файл, игнорируя ошибки ФС (FUSE может отказать)."""
    for ext in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(path + ext)
        except OSError:
            pass


def _log_sync_error(dest, exc):
    """Записать сбой синка в log/newsdb_sync.log (best-effort, прогон не роняем)."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(dest)))
        log_dir = os.path.join(root, "log")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "newsdb_sync.log"), "a", encoding="utf-8") as f:
            f.write(f"{now_iso()}\t{dest}\t{type(exc).__name__}: {exc}\n")
    except OSError:
        pass


def _backup_dest(dest, keep=5):
    """Создать бэкап цели и вернуть путь; при невозможности вернуть None."""
    try:
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            return None
    except OSError:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = f"{dest}.bak-{ts}"
    try:
        shutil.copyfile(dest, backup)
    except OSError as exc:
        _log_sync_error(dest, exc)
        return None
    # Ротация: оставить последние `keep` бэкапов.
    try:
        for old in sorted(glob.glob(f"{dest}.bak-*"))[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
    except OSError:
        pass
    return backup


def _sync(conn):
    """Атомарно зафиксировать рабочую БД на целевом пути (state/).

    Пишем во временный файл рядом с целью и меняем через os.replace — цель никогда
    не бывает «полузаписанной» (устраняет потерю истории при обрыве копирования).
    Сбой логируется, но прогон не роняется: данные целы в рабочей копии, стадии
    идемпотентны.
    """
    pair = _MIRRORS.get(id(conn))
    if not pair:
        return True
    work, dest = pair
    tmp = f"{dest}.tmp-{os.getpid()}"
    try:
        shutil.copyfile(work, tmp)
        os.replace(tmp, dest)  # атомарная замена на той же ФС
        return True
    except OSError as exc:
        _log_sync_error(dest, exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def sync(conn):
    """Публичная синхронизация; True при успехе, False при сохранённой ошибке."""
    return _sync(conn)


def close(conn):
    """Синхронизировать зеркало, закрыть SQLite и очистить реестр.

    Все мутации newsdb сами делают commit; close не коммитит
    незавершённую транзакцию, но проверяет персистентность уже
    зафиксированного состояния.
    """
    pair = _MIRRORS.get(id(conn))
    try:
        if not _sync(conn):
            dest = pair[1] if pair else "целевой файл"
            raise PersistenceError(f"Не удалось зафиксировать изменения БД в {dest}")
    finally:
        _MIRRORS.pop(id(conn), None)
        conn.close()


def _commit_and_sync(conn):
    """Commit с обязательным подтверждением персистентности целевого файла."""
    conn.commit()
    if not _sync(conn):
        pair = _MIRRORS.get(id(conn))
        dest = pair[1] if pair else "целевой файл"
        raise PersistenceError(f"Не удалось зафиксировать изменения БД в {dest}")


def _ensure_schema(conn):
    """Создать таблицы/индексы, если их ещё нет (идемпотентно).

    Намеренно НЕ используем executescript(): на FUSE его неявный commit
    может пересоздать журнал и упасть с 'disk I/O error'. Выполняем
    отдельные execute() — они устойчивы при journal_mode=MEMORY.
    """
    cur = conn.cursor()
    stmts = [
        """CREATE TABLE IF NOT EXISTS items (
            id           INTEGER PRIMARY KEY,
            url          TEXT UNIQUE,
            ecli         TEXT,
            act          TEXT,
            source       TEXT,
            title        TEXT,
            title_norm   TEXT,
            summary      TEXT,
            published_at TEXT,
            first_seen   TEXT,
            run_date     TEXT,
            score        REAL,
            topics       TEXT,
            status       TEXT,
            channels     TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS published (
            id       INTEGER PRIMARY KEY,
            item_id  INTEGER,
            channel  TEXT,
            posted_at TEXT,
            post_id  TEXT,
            post_url TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS runs (
            run_date       TEXT,
            started        TEXT,
            finished       TEXT,
            sources_ok     TEXT,
            sources_failed TEXT,
            n_collected    INTEGER,
            n_shortlisted  INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS catalog_entries (
            id           INTEGER PRIMARY KEY,
            row_key      TEXT UNIQUE,
            catalog_date TEXT,
            chat_id      TEXT,
            status       TEXT,
            title        TEXT,
            title_norm   TEXT,
            topic_norm   TEXT,
            act_norm     TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS catalog_keys (
            id       INTEGER PRIMARY KEY,
            entry_id INTEGER,
            kind     TEXT,
            value    TEXT,
            UNIQUE(kind, value)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_items_ecli ON items(ecli)",
        "CREATE INDEX IF NOT EXISTS idx_items_ecli_nocase ON items(ecli COLLATE NOCASE)",
        "CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen)",
        "CREATE INDEX IF NOT EXISTS idx_catalog_title ON catalog_entries(title_norm)",
        "CREATE INDEX IF NOT EXISTS idx_catalog_keys ON catalog_keys(kind, value)",
    ]
    for s in stmts:
        cur.execute(s)
    # Мягкая миграция: добавить channels, если БД была создана ранней версией схемы.
    cols = {r[1] for r in cur.execute("PRAGMA table_info(items)").fetchall()}
    if "channels" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN channels TEXT")
    if "act" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN act TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_act ON items(act)")
    conn.commit()


def get_item_by_url(conn, url):
    """Вернуть строку items по точному URL или None."""
    if not url:
        return None
    row = conn.execute("SELECT * FROM items WHERE url = ?", (url,)).fetchone()
    return row


def normalize_ecli(ecli):
    """Канонический ECLI для хранения и дедупликации."""
    return str(ecli or "").strip().upper()


def get_item_by_ecli(conn, ecli):
    """Вернуть items по ECLI без зависимости от регистра."""
    ecli = normalize_ecli(ecli)
    if not ecli:
        return None
    row = conn.execute(
        "SELECT * FROM items WHERE ecli = ? COLLATE NOCASE AND ecli != '' LIMIT 1",
        (ecli,),
    ).fetchone()
    return row


def get_item_by_act(conn, act_norm):
    """Вернуть строку items по нормализованному номеру акта/дела или None."""
    if not act_norm:
        return None
    return conn.execute(
        "SELECT * FROM items WHERE act = ? AND act != '' LIMIT 1", (act_norm,)
    ).fetchone()


def _recent_titles(conn, days=DUP_WINDOW_DAYS):
    """Заголовки (title_norm) элементов за последние `days` дней для нечёткого дедупа."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    rows = conn.execute(
        "SELECT title_norm FROM items WHERE first_seen >= ? AND title_norm != ''",
        (cutoff,),
    ).fetchall()
    return [r["title_norm"] for r in rows]


def is_duplicate(conn, url, ecli, title_norm, act_norm=""):
    """Дубликат: состояние кандидатов + каталог уже использованных материалов."""
    if url and get_item_by_url(conn, url) is not None:
        return True
    if url and conn.execute(
        "SELECT 1 FROM catalog_keys WHERE kind='url' AND value=? LIMIT 1", (url,)
    ).fetchone() is not None:
        return True
    if ecli and get_item_by_ecli(conn, ecli) is not None:
        return True
    if ecli and conn.execute(
        "SELECT 1 FROM catalog_keys WHERE kind='ecli' AND value=? LIMIT 1",
        (ecli.casefold(),),
    ).fetchone() is not None:
        return True
    if act_norm and get_item_by_act(conn, act_norm) is not None:
        return True
    if act_norm and conn.execute(
        "SELECT 1 FROM catalog_keys WHERE kind='act' AND value=? LIMIT 1",
        (act_norm,),
    ).fetchone() is not None:
        return True
    if title_norm:
        for existing in _recent_titles(conn):
            if not existing:
                continue
            ratio = difflib.SequenceMatcher(None, title_norm, existing).ratio()
            if ratio >= DUP_RATIO:
                return True
        rows = conn.execute(
            "SELECT title_norm, topic_norm FROM catalog_entries"
        ).fetchall()
        for row in rows:
            for existing in (row["title_norm"], row["topic_norm"]):
                if existing and difflib.SequenceMatcher(
                    None, title_norm, existing
                ).ratio() >= DUP_RATIO:
                    return True
    return False


_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)", re.IGNORECASE)
_ECLI_RE = re.compile(r"\bECLI:[A-Z]{2}:[A-Z0-9.]+:\d{4}:[A-Z0-9.]+\b", re.IGNORECASE)


def _catalog_cells(line):
    """Разобрать строку markdown-таблицы каталога на девять ячеек."""
    if not line.startswith("|") or not line.rstrip().endswith("|"):
        return []
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def ingest_published_catalog(conn, catalog_path):
    """Идемпотентно загрузить URL/акты/темы каталога публикаций в SQLite.

    Каталог остаётся источником правды. Таблицы catalog_* — производный индекс,
    который полностью перестраивается при каждом вызове.
    """
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return 0

    entries = []
    for line in text.splitlines():
        cells = _catalog_cells(line)
        if len(cells) != 9 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        date, _channel_id, chat_id, status, title, topic, _jur, act, sources = cells
        title_norm = normalize_title(title)
        topic_norm = normalize_title(topic)
        act_norm = normalize_title(act)
        seed = "\x1f".join((date, chat_id, title_norm, topic_norm, act_norm))
        row_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        urls = [u.rstrip(".,; ") for u in _MD_LINK_RE.findall(sources)]
        eclis = {e.casefold() for e in _ECLI_RE.findall(" ".join((title, act, sources)))}
        entries.append((row_key, date, chat_id, status, title, title_norm,
                        topic_norm, act_norm, urls, sorted(eclis)))

    conn.execute("DELETE FROM catalog_keys")
    conn.execute("DELETE FROM catalog_entries")
    for row_key, date, chat_id, status, title, title_norm, topic_norm, act_norm, urls, eclis in entries:
        cur = conn.execute(
            """INSERT INTO catalog_entries(row_key, catalog_date, chat_id, status,
                    title, title_norm, topic_norm, act_norm)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row_key, date, chat_id, status, title, title_norm, topic_norm, act_norm),
        )
        entry_id = cur.lastrowid
        for url in urls:
            conn.execute(
                "INSERT OR IGNORE INTO catalog_keys(entry_id, kind, value) VALUES (?,?,?)",
                (entry_id, "url", url),
            )
        for ecli in eclis:
            conn.execute(
                "INSERT OR IGNORE INTO catalog_keys(entry_id, kind, value) VALUES (?,?,?)",
                (entry_id, "ecli", ecli),
            )
        if act_norm and act_norm != "—":
            conn.execute(
                "INSERT OR IGNORE INTO catalog_keys(entry_id, kind, value) VALUES (?,?,?)",
                (entry_id, "act", act_norm),
            )
    _commit_and_sync(conn)
    return len(entries)


def upsert_item(conn, item):
    """Вставить/обновить элемент по URL. Возвращает (item_id, is_new)."""
    url = item.get("url") or ""
    ecli = normalize_ecli(item.get("ecli"))
    act_norm = normalize_title(item.get("act") or "")
    title = item.get("title") or ""
    title_norm = item.get("title_norm") or normalize_title(title)
    summary = item.get("summary") or ""
    published_at = item.get("published_at") or ""
    run_date = item.get("run_date") or ""
    score = item.get("score")
    topics = item.get("topics") or ""
    status = item.get("status") or "collected"
    first_seen = item.get("first_seen") or now_iso()

    existing = get_item_by_url(conn, url) if url else None
    if existing is None and ecli:
        existing = get_item_by_ecli(conn, ecli)
    if existing is None and act_norm:
        existing = get_item_by_act(conn, act_norm)

    if existing is not None:
        item_id = existing["id"]
        # Обновляем изменяемые поля, сохраняя first_seen первого появления.
        conn.execute(
            """UPDATE items SET ecli=?, act=?, source=?, title=?, title_norm=?, summary=?,
                    published_at=?, run_date=?, score=?, topics=?, status=?
               WHERE id=?""",
            (
                ecli,
                act_norm,
                item.get("source") or existing["source"],
                title,
                title_norm,
                summary,
                published_at,
                run_date,
                score,
                topics,
                status,
                item_id,
            ),
        )
        _commit_and_sync(conn)
        return item_id, False

    cur = conn.execute(
        """INSERT INTO items(url, ecli, act, source, title, title_norm, summary,
                published_at, first_seen, run_date, score, topics, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            url or None,
            ecli,
            act_norm,
            item.get("source") or "",
            title,
            title_norm,
            summary,
            published_at,
            first_seen,
            run_date,
            score,
            topics,
            status,
        ),
    )
    _commit_and_sync(conn)
    return cur.lastrowid, True


def set_status(conn, item_id, status, channels=None):
    """Обновить статус (и опц. каналы) элемента по id."""
    if channels is not None:
        conn.execute(
            "UPDATE items SET status=?, channels=? WHERE id=?",
            (status, channels, item_id),
        )
    else:
        conn.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))
    _commit_and_sync(conn)


def set_score_topics(conn, item_id, score, topics):
    """Записать скоринг и темы элемента по id."""
    conn.execute(
        "UPDATE items SET score=?, topics=? WHERE id=?", (score, topics, item_id)
    )
    _commit_and_sync(conn)


def add_published(conn, item_id, channel, post_id="", post_url=""):
    """Зафиксировать факт публикации элемента в канал."""
    conn.execute(
        """INSERT INTO published(item_id, channel, posted_at, post_id, post_url)
           VALUES (?,?,?,?,?)""",
        (item_id, channel, now_iso(), post_id, post_url),
    )
    _commit_and_sync(conn)


def upsert_run(conn, run_date, started=None, finished=None, sources_ok=None,
               sources_failed=None, n_collected=None, n_shortlisted=None):
    """Создать/обновить строку прогона за дату (частичное обновление непустых полей)."""
    row = conn.execute(
        "SELECT rowid, * FROM runs WHERE run_date = ?", (run_date,)
    ).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO runs(run_date, started, finished, sources_ok,
                    sources_failed, n_collected, n_shortlisted)
               VALUES (?,?,?,?,?,?,?)""",
            (
                run_date,
                started or now_iso(),
                finished or "",
                sources_ok or "",
                sources_failed or "",
                n_collected if n_collected is not None else 0,
                n_shortlisted if n_shortlisted is not None else 0,
            ),
        )
        _commit_and_sync(conn)
        return

    updates = {}
    if started is not None:
        updates["started"] = started
    if finished is not None:
        updates["finished"] = finished
    if sources_ok is not None:
        updates["sources_ok"] = sources_ok
    if sources_failed is not None:
        updates["sources_failed"] = sources_failed
    if n_collected is not None:
        updates["n_collected"] = n_collected
    if n_shortlisted is not None:
        updates["n_shortlisted"] = n_shortlisted
    if not updates:
        return
    sets = ", ".join(f"{k}=?" for k in updates)
    params = list(updates.values()) + [row["rowid"]]
    conn.execute(f"UPDATE runs SET {sets} WHERE rowid=?", params)
    _commit_and_sync(conn)


def get_run(conn, run_date):
    """Вернуть строку runs за дату или None."""
    return conn.execute(
        "SELECT * FROM runs WHERE run_date = ? ORDER BY rowid DESC LIMIT 1",
        (run_date,),
    ).fetchone()


if __name__ == "__main__":
    # Утилита: `python3 newsdb.py --root PATH` создаёт/проверяет схему и печатает счётчики.
    import argparse

    ap = argparse.ArgumentParser(description="Инициализация/проверка БД состояния.")
    ap.add_argument("--root", default=".", help="Корень проекта (где лежит state/).")
    args = ap.parse_args()
    c = connect(args.root)
    n_items = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_pub = c.execute("SELECT COUNT(*) FROM published").fetchone()[0]
    n_runs = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    print(f"БД: {db_path(args.root)}")
    print(f"items={n_items} published={n_pub} runs={n_runs}")
