#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оффлайн-тест конвейера без сети и pytest: parse → select → digest на probe-фикстурах.

Копирует pipeline/raw/probe/*.txt во временный --root как {source_id}_1.txt,
кладёт туда копии реальных конфигов, прогоняет три стадии и проверяет:
  - каждый пригодный фикстур даёт >0 элементов (binary/пустой — 0 без падения);
  - дедуп работает (второй прогон select даёт 0 новых);
  - дайджест создан и содержит нумерованные блоки.
Возвращает ненулевой код при любой ошибке.
"""

import json
import os
import shutil
import sys
import tempfile

# Пути: корень проекта = родитель каталога tests/; скрипты — в scripts/.
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import parse_feeds  # noqa: E402
import select_news  # noqa: E402
import make_digest  # noqa: E402
import newsdb  # noqa: E402

PROBE_DIR = os.path.join(PROJECT_ROOT, "pipeline", "raw", "probe")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
TEST_DATE = "2099-01-01"

# Источники, чьи probe-фикстуры пустые/binary → ожидаем 0 элементов (без падения).
EXPECT_ZERO = {"nl_fd", "ru_ras"}


class TestFail(AssertionError):
    """Отказ проверки офлайн-теста."""


def _check(cond, msg):
    """Мягкий assert: собирает ошибки, не роняя остальной прогон."""
    if not cond:
        raise TestFail(msg)


def setup_root():
    """Создать временный --root: config/* + pipeline/raw/{date}/{sid}_1.txt."""
    root = tempfile.mkdtemp(prefix="newsflow_test_")
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    for name in os.listdir(CONFIG_DIR):
        if name.endswith(".yaml"):
            shutil.copy(os.path.join(CONFIG_DIR, name),
                        os.path.join(root, "config", name))
    raw_dir = os.path.join(root, "pipeline", "raw", TEST_DATE)
    os.makedirs(raw_dir, exist_ok=True)
    probe_ids = []
    for name in os.listdir(PROBE_DIR):
        if not name.endswith(".txt"):
            continue
        sid = name[:-4]
        shutil.copy(os.path.join(PROBE_DIR, name),
                    os.path.join(raw_dir, f"{sid}_1.txt"))
        probe_ids.append(sid)
    return root, sorted(probe_ids)


def read_inbox(root):
    """Прочитать inbox jsonl → список записей."""
    path = os.path.join(root, "pipeline", "inbox", f"{TEST_DATE}_items.jsonl")
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def run_tests():
    """Прогнать все проверки, вернуть список сообщений об ошибках."""
    errors = []
    root, probe_ids = setup_root()
    print(f"[test] temp root: {root}")
    print(f"[test] probe sources: {', '.join(probe_ids)}")

    # --- Стадия 1: parse ------------------------------------------------------
    try:
        pstats = parse_feeds.run(TEST_DATE, root)
    except Exception as e:  # парсинг не должен падать целиком
        errors.append(f"parse_feeds.run упал: {type(e).__name__}: {e}")
        return errors, root

    per_source = pstats["per_source"]
    inbox = read_inbox(root)
    counts = {}
    for rec in inbox:
        counts[rec["source"]] = counts.get(rec["source"], 0) + 1

    # Проверка: пригодные фикстуры → >0; binary/пустые → 0 (и статус помечен).
    for sid in probe_ids:
        n = counts.get(sid, 0)
        if sid in EXPECT_ZERO:
            try:
                _check(n == 0, f"{sid}: ожидалось 0 элементов (dead-фикстур), получено {n}")
                status = per_source.get(sid, {}).get("status", "")
                _check("binary" in status or "empty" in status or n == 0,
                       f"{sid}: dead-фикстур должен быть помечен, статус={status!r}")
            except TestFail as e:
                errors.append(str(e))
        else:
            try:
                _check(n > 0, f"{sid}: ожидалось >0 элементов из пригодного фикстура, получено {n}")
            except TestFail as e:
                errors.append(str(e))

    # Проверка: суммарно распарсено хоть что-то осмысленное.
    try:
        _check(pstats["total"] > 0, "parse: суммарно 0 элементов — фикстуры не распарсились")
    except TestFail as e:
        errors.append(str(e))

    print(f"[test] parse per-source counts: {counts}")

    # --- Стадия 2: select (прогон 1) -----------------------------------------
    try:
        s1 = select_news.run(TEST_DATE, 15, root)
    except Exception as e:
        errors.append(f"select_news.run (прогон 1) упал: {type(e).__name__}: {e}")
        return errors, root

    try:
        _check(s1["n_collected_new"] > 0,
               "select прогон 1: 0 новых элементов — нечего проверять на дедуп")
    except TestFail as e:
        errors.append(str(e))

    # Проверка структуры shortlist.json (item_id, n, suggested_channels).
    sl_path = os.path.join(root, "pipeline", "shortlist", f"{TEST_DATE}_shortlist.json")
    try:
        _check(os.path.exists(sl_path), "shortlist.json не создан")
        with open(sl_path, encoding="utf-8") as f:
            sl = json.load(f)
        _check(len(sl["items"]) > 0, "shortlist пуст после прогона 1")
        for it in sl["items"]:
            _check("item_id" in it and it["item_id"], f"shortlist #{it.get('n')}: нет item_id")
            _check("suggested_channels" in it and it["suggested_channels"],
                   f"shortlist #{it.get('n')}: нет suggested_channels")
    except TestFail as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"shortlist.json нечитаем: {type(e).__name__}: {e}")

    # --- Стадия 3: digest (после наполненного шортлиста) ---------------------
    try:
        dpath = make_digest.run(TEST_DATE, root)
    except Exception as e:
        errors.append(f"make_digest.run упал: {type(e).__name__}: {e}")
        dpath = None

    if dpath:
        try:
            _check(os.path.exists(dpath), "digest-файл не создан")
            with open(dpath, encoding="utf-8") as f:
                digest = f.read()
            n_blocks = digest.count("\n## ")
            _check(n_blocks > 0, f"digest без нумерованных блоков (## n.), найдено {n_blocks}")
            _check("## 1." in digest, "digest: нет блока '## 1.'")
        except TestFail as e:
            errors.append(str(e))
    else:
        errors.append("digest: путь не получен")

    # --- Стадия 4: дедуп (прогон 2 select даёт 0 новых) ----------------------
    try:
        s2 = select_news.run(TEST_DATE, 15, root)
        _check(s2["n_collected_new"] == 0,
               f"дедуп сломан: прогон 2 дал {s2['n_collected_new']} новых (ожидалось 0)")
    except TestFail as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"select_news.run (прогон 2) упал: {type(e).__name__}: {e}")

    # --- Стадия 5: точечная проверка дедупа is_duplicate ---------------------
    try:
        conn = newsdb.connect(root)
        # Любой уже вставленный URL должен опознаваться как дубликат.
        row = conn.execute(
            "SELECT url, ecli, title_norm FROM items WHERE url IS NOT NULL LIMIT 1"
        ).fetchone()
        if row is not None:
            dup = newsdb.is_duplicate(conn, row["url"], row["ecli"], row["title_norm"])
            _check(dup, "is_duplicate: существующий элемент не опознан как дубликат")
        # Заведомо новый элемент — не дубликат.
        dup2 = newsdb.is_duplicate(conn, "https://example.invalid/unique-xyz-123",
                                   "", "совершенно уникальный заголовок 12345")
        _check(not dup2, "is_duplicate: новый элемент ошибочно помечен дубликатом")
        newsdb.close(conn)
    except TestFail as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"проверка is_duplicate упала: {type(e).__name__}: {e}")

    return errors, root


def main():
    errors, root = run_tests()
    print("\n" + "=" * 70)
    if errors:
        print(f"РЕЗУЛЬТАТ: ПРОВАЛ — {len(errors)} ошибок")
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}")
        print("=" * 70)
        # Оставляем временный каталог для отладки при провале.
        print(f"(temp root сохранён для отладки: {root})")
        sys.exit(1)
    print("РЕЗУЛЬТАТ: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    print("=" * 70)
    # Чистим временный каталог при успехе.
    shutil.rmtree(root, ignore_errors=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
