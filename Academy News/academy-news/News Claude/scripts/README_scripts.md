# scripts/ — детерминированное ядро новостного конвейера

Python 3 (stdlib) + PyYAML. `collect_sources.py` выполняет прямой HTTP-сбор;
Chrome нужен только источникам с `method: chrome`. Остальные скрипты обрабатывают
сырьё детерминированно и ведут состояние в SQLite.

Установка зависимостей в выделенное окружение:

```
python -m pip install -r requirements-runtime.txt
```

Во всех скриптах `import yaml` обёрнут в try/except: при отсутствии PyYAML
печатается команда установки и код выходит с ошибкой.

---

## Поток файлов

```
collect_sources.py --date Д
        │
pipeline/raw/{дата}/{source_id}_{n}.txt        ← сырой HTTP/Atom/HTML
        │
        ▼  parse_feeds.py --date Д
pipeline/inbox/{дата}_items.jsonl              ← {source,url,ecli,title,summary,published_at,lang}
        │
        ▼  select_news.py --date Д --top 15    (+ state/news_state.sqlite: скоринг, дедуп)
pipeline/shortlist/{дата}_shortlist.json       ← {date, items:[{n,item_id,...,score,topics,suggested_channels}]}
        │
        ▼  make_digest.py --date Д
pipeline/digest/{дата}_digest.md               ← скелет; «Суть» дописывает Claude из источника
        │
        ▼  mark.py assign/published/skip       (ручные пометки по номеру n в шортлисте)
state/news_state.sqlite (published, статусы)
```

Все пути относительны `--root` (по умолчанию `.`). Кириллица/UTF-8 везде.

---

## Скрипты

### collect_sources.py `--date YYYY-MM-DD [--only SID] [--root PATH]`
Единый транспорт: браузерный UA, таймауты, ретраи с backoff, RSS-first и
HTML-fallback по `config/sources.yaml`. Специализированные `collector`-скрипты
запускаются автоматически. Сырой ответ сохраняется байт-в-байт, покрытие — в
`pipeline/raw/{date}/collection_manifest.json` и `runs.sources_ok/failed`.
`method: chrome` означает видимый ручной добор (`manual`), а не сетевой сбой.
Каждый `collector` вызывается один раз и завершается; код 3 означает
`manual`, а не аварию. `_summary` записывается в сам JSON-манифест.
Точечный `--only SID` атомарно обновляет только свой источник в общем
манифесте и пишет отдельный `collection_manifest_{SID}.json`; покрытие других
источников дня не стирается.

### Специализированные коллекторы Фазы 2

- `collect_vs.py` — официальные XHR JSON ВС РФ; обзоры и налоговые новости.
- `collect_ru_ras.js` — метаданные РАС через открытый CDP-Chrome; не качает PDF,
  дожидается JS-формы, ограничивает число и темп запросов. Production URL
  берётся из `config/sources.yaml → ru_ras.collector_args` (сейчас `9223`),
  а не из документного хардкода. Явно датированные результаты за пределами
  семидневного окна отсекаются повторно после UI-выдачи.
- `fetch_ras_fulltext.js` — скачивает ВСЕ PDF RAS текущего дня через CDP-Chrome
  в `../court_analysis/extracted_text/ras/{date}/` с паузами 15–25 секунд.
- `fetch_rechtspraak_fulltext.py` — последовательно тянет XML ECLI одной
  сессией; хранит raw XML, txt и накопительный manifest, не теряя предыдущие
  ECLI при точечном вызове.
- `court_protocol.py` — утренний протокол суда: заносит ВСЕ дела в реестр,
  скачивает полные тексты, отбрасывает процедурный шум и оставляет в
  `../court_analysis/ras|rechtspraak` только substantive дела по международному
  налогообложению.
- `court_morning_run.py` — отдельный запуск только для RAS + Rechtspraak;
  пишет court-only receipt и обновляет общий manifest без потери web-источников.
  Receipt пересчитывает для каждого судебного источника число дел в
  реестре, полные тексты и завершённый анализ; любой пропуск даёт
  `complete=false`. Предварительный receipt со `state=not_run` сохраняется,
  если после сбора упал parse/full-text этап.
  Плановое время 07:00 пока не обеспечено загруженным scheduler (см.
  `launchd/README.md`).
- `collect_telegram.py` — одноразовые Telegram-лиды. Первый API-вызов
  `get_me`, username должен быть `academy_of_beps`; занятая session блокирует
  запуск. Локальные клиенты дополнительно сериализуются advisory-lock на самом
  session-файле; владельцем должен быть текущий OS-user, права — `0600` или
  строже, а отсутствие `lsof`
  блокирует запуск. Новая session и
  авторизация не создаются; фонового listener нет.

### newsdb.py
Слой состояния SQLite. Обычно вызывается как модуль другими скриптами; как CLI
(`python3 newsdb.py --root .`) создаёт/проверяет схему и печатает счётчики.

Важно про хранилище: рабочая БД живёт на локальном `/tmp` (там SQLite надёжен),
а после каждой записи копируется в `state/news_state.sqlite`. Это обходит
`disk I/O error`, которым FUSE/облачные папки отвечают на журналирование и
блокировки SQLite при прямой работе с файлом на монтировании. При старте
существующее состояние подтягивается из `state/` в рабочую копию; повреждённый
целевой файл пересоздаётся только после успешного бэкапа; нечитаемый файл не
затирается. Синхронизация в `state/` идёт через временный файл и `os.replace`;
ошибка становится явной и пишется в `log/newsdb_sync.log`.

Ключевые функции: `connect(root)`, `upsert_item`, `is_duplicate(url, ecli,
title_norm)` (точный URL/ECLI + `difflib.SequenceMatcher ≥ 0.9` по заголовкам за
30 дней + индекс корневого каталога публикаций), `ingest_published_catalog`,
`set_status`, `add_published`, `upsert_run`, `get_run`, `normalize_title`,
`sync(conn)`, `close(conn)`. Каждое соединение нужно закрыть через
`newsdb.close`, чтобы перед закрытием проверить финальный sync зеркала.

### parse_feeds.py `--date YYYY-MM-DD [--root PATH]`
Читает `pipeline/raw/{дата}/*.txt`, по имени файла определяет `source_id`, по
`config/sources.yaml` — парсер, и пишет `pipeline/inbox/{дата}_items.jsonl`.
Для судебных источников `ru_ras` и `nl_rechtspraak` одновременно обновляет
корневой реестр `../court_analysis/court_decisions.csv`.
Парсеры:
- `rss`/`atom`/`auto` — общий XML-парсер RSS 2.0 и Atom; `pubDate`/published,
  description/content, канонизация tracking URL; URL-гейты источника действуют
  и для RSS.
- `rechtspraak_atom` — Atom 1.0: из `<entry>` берёт ECLI(`id`), `title`,
  `summary`, `updated`→дата, deeplink (`link rel="alternate"`).
- `html_links` — живой HTML разбирает stdlib `HTMLParser`, markdown оставляет
  fallback-веткой. Все per-source правила (`html.base/include/exclude/path_hint`
  и дата из названия) находятся в `sources.yaml`. Отсекает
  навигацию/сервис (заголовки < 20 символов, катег| ~login/search/tag/feed URL,
  обрывки прозы). Относительные ссылки абсолютизируются к базе источника.
  Даты: ISO `YYYY-MM-DD`, а также `09 June, 2026` / `17 juni 2026` / `2 juli
  2026` (nl/en месяцы).

Стратегии html_links (по порядку): A markdown-ссылки `[title](url)`;
B «"заголовок" … (дата|URL)»; C markdown-заголовки `## Title` + дата рядом;
D URL-якорь → ближайший заголовок в кавычках слева (устойчиво к «съезжающей»
парности кавычек). Печатает статистику по источникам. Пустой/`[binary data]`/
сломанный файл даёт 0 элементов и НЕ роняет прогон; неизвестный источник —
пропуск.

Язык берётся из поля `lang` в `sources.yaml`.

### select_news.py `--date YYYY-MM-DD --top 15 [--root PATH]`
Грузит inbox + `config/topics.yaml`; перед отбором идемпотентно индексирует
`../ОПУБЛИКОВАННЫЕ_НОВОСТИ.md`. Для каждого элемента: матч ключевых слов
(casefold-substring) из `keywords_ru/nl/en/keywords` по `title+summary`;
вес приоритета темы P1=3, P2=2, P3=1 (берём лучшую тему, собираем все id).
`base = вес_темы × вес_источника` (из sources.yaml) + `0.5` за свежесть
(пубикация ≤ 24 ч). Telegram lead получает ограниченный engagement-бонус не более 1.5,
но всегда остаётся вторичным сигналом. Нет матча темы → элемент отбрасывается (судебные источники
Источники `prefiltered: true` проходят без словарного матча с дефолтным P2;
судебные P1 не выкидываются капом. `require_topics_any` не позволяет широкому
служебному тегу заменить целевую тему. Дедуп выполняется по SQLite/каталогу и
внутри текущей пачки между источниками (URL/ECLI/fuzzy title).
Ранжирование, кап `--top`, запись `pipeline/shortlist/{дата}_shortlist.json`
(включая `item_id` для mark.py и `suggested_channels`), статусы →
`shortlisted`, обновление строки `runs`. Печатает таблицу-сводку.

`suggested_channels`: суды → `["telegram_channel"]`; RU-новости (`ru_garant`) →
`["telegram_channel","vk"]`; NL/EN-медиа → `["telegram_channel"]`.

### make_digest.py `--date YYYY-MM-DD [--root PATH]`
`shortlist.json` → `pipeline/digest/{дата}_digest.md`: шапка (дата + статус
источников из `runs`) и нумерованные блоки:

```
## {n}. {title}
- Источник: {source} | {published_at} | {url}
- Темы: … | Скоринг: …
- Предложенные каналы: …
- Суть: [ЗАПОЛНИТ CLAUDE: 2–3 предложения строго из источника]
```

Идемпотентно (перезапись). «Суть» дописывает Claude строго из источника.
Telegram-лид получает явную строку «первоисточник ОБЯЗАТЕЛЬНО подтвердить».

### cards.py + publish_batch.py

`publish_batch.py` читает ровно 10 постов из `pipeline/approved/*.json`
(`config/approved.schema.json`). Default — безопасный dry-run: валидация,
проверка media-caption ≤1024, обоих постоянных хэштегов, прямого
первоисточника, медиаправ и сборка карточек. Execute допускается только
при `approval.status/by/evidence` в каждом item.

```
python scripts/publish_batch.py pipeline/approved/2026-07-18_0900.json
python scripts/publish_batch.py pipeline/approved/2026-07-18_0900.json --execute-editorial
python scripts/publish_batch.py pipeline/approved/2026-07-18_0900.json --execute-non-telegram
```

`--execute-editorial` не знает id главного Telegram-канала и умеет писать
только в редчат. `--execute-non-telegram` никогда не шлёт TG через Postiz.
Каждая доставка сразу пишет `pipeline/published/{date}.jsonl`; повторный
запуск не шлёт дубль и может починить каталог по сайдкару.

Перед сборкой и любой доставкой `publish_batch.py` блокирует заголовки и подписи
с непереведёнными английскими словами. Допускаются официальные аббревиатуры и
обозначения из явного списка (`BEPS`, `OECD`, `HMRC`, `ECLI`, `MLI`, `GloBE` и
аналогичные), но не английские фразы внутри русского предложения.

После execute создаётся `pipeline/run_records/{date}/{run_id}/run_record.json`:
approved, release-only sidecar и доступные shortlist/digest/manifests имеют
SHA-256 и размер; `run_id` повторно не записывается. В schema v3 только approved
и release-only sidecar являются доказательством состава релиза;
изменяемые дневные outputs помечаются `context_only` и не доказывают
lineage. Исторический ремонт без
сети выполняется `--backfill-run-record`: он фиксирует только доказуемые
approved + sidecar + coverage каталога, а утраченные volatile-артефакты честно
помечает `not_backfilled`.

Независимая локальная проверка receipt без сети:

```
python scripts/publish_batch.py --verify-run-record pipeline/run_records/{date}/{run_id}/run_record.json
```

Перед открытием Telethon session движок fail-closed требует права
`0600` или строже, успешную межпроцессную блокировку и чистый
`lsof`; `get_me()` вызывается первым API-действием и повторно
непосредственно перед каждым `send_file`.

### postiz_discover.py `--write`

Прямой discovery `localhost:4007` с мака. Секрет берётся только из
`.env.postiz`; в вывод не печатается. `--write` записывает только однозначные
VK/LinkedIn id; Telegram игнорируется.

### mark.py `[--root PATH] <подкоманда>`
Ручные пометки по номеру `n` из шортлиста (маппинг `n↔item_id` берётся из
`shortlist.json`).
- `assign --date Д --map "3:telegram_channel,vk;5:vk"` — статус `assigned`,
  каналы пишутся в колонку `items.channels`.
- `published --date Д --item N --channel C [--post-id X] [--post-url U]` —
  запись в `published`, статус `published`.
- `skip --date Д --item N` — статус `skipped`.

### tests/test_offline.py
Оффлайн-прогон без сети и pytest: копирует `pipeline/raw/probe/*.txt` во
временный `--root` как `{source_id}_1.txt` + копии реальных конфигов, гоняет
parse → select → digest и проверяет: каждый пригодный фикстур даёт >0 элементов
(`nl_fd`/`ru_ras` — 0, без падения); дедуп (второй select = 0 новых); дайджест
создан с нумерованными блоками; `is_duplicate` работает. Ненулевой код при
провале.

```
python3 tests/test_offline.py
```

### tests/test_phase1.py
Регрессии Фазы 1: защита существующей/битой БД, атомарная замена, ротационный
бэкап, идемпотентный ингест каталога, RSS и URL-гейты, RSS-first/HTML-fallback,
тематический гейт широких источников и внутрипачечный дедуп.

```
python3 tests/test_phase1.py
```

### tests/test_phase2.py

Регрессии парсеров ВС/Минфина, fixture РАС, full text Rechtspraak,
Telegram-лида, проверки занятой session и маркировки `manual` для CDP.

```
python3 tests/test_phase2.py
```

### tests/test_phase3.py

Офлайн-проверки validation/approval, account gate, mandatory disconnect,
идемпотентного sidecar+каталога, Postiz discovery и media upload.

```
python tests/test_phase3.py
```

### tests/test_phase4_acceptance.py

Сквозная офлайн-приёмка: Rechtspraak/РАС/ВС/Минфин/Telegram →
14 parsed → ровно 10 shortlist/digest/cards → 10 sidecar+каталог →
нулевой повтор. Внешние клиенты заменены фейками.

```
python -W error::ResourceWarning tests/test_phase4_acceptance.py
```

---

## Схема SQLite (`state/news_state.sqlite`)

```sql
items(
  id INTEGER PK, url TEXT UNIQUE, ecli TEXT, act TEXT, source TEXT,
  title TEXT, title_norm TEXT, summary TEXT, published_at TEXT,
  first_seen TEXT, run_date TEXT, score REAL, topics TEXT,
  status TEXT,          -- collected|shortlisted|digested|assigned|published|skipped
  channels TEXT         -- назначенные каналы (mark.py assign)
)

published(
  id INTEGER PK, item_id INTEGER, channel TEXT,
  posted_at TEXT, post_id TEXT, post_url TEXT
)

runs(
  run_date TEXT, started TEXT, finished TEXT,
  sources_ok TEXT, sources_failed TEXT,
  n_collected INTEGER, n_shortlisted INTEGER
)

catalog_entries(
  id INTEGER PK, row_key TEXT UNIQUE, catalog_date TEXT, chat_id TEXT,
  status TEXT, title TEXT, title_norm TEXT, topic_norm TEXT, act_norm TEXT
)

catalog_keys(
  entry_id INTEGER, kind TEXT, value TEXT,
  UNIQUE(kind, value)
)
```

Дедуп (`is_duplicate`): точное совпадение `url` или `ecli` за всё время,
ключи корневого каталога и нечёткое совпадение `title_norm` (ratio ≥ 0.9)
среди элементов за 30 дней и заголовков/нормализованных тем каталога.

---

## Типовой дневной прогон

```
pip install pyyaml --break-system-packages -q
python3 scripts/collect_sources.py --date 2026-07-02 --root .
python3 scripts/parse_feeds.py  --date 2026-07-02 --root .
python3 scripts/select_news.py  --date 2026-07-02 --top 15 --root .
python3 scripts/make_digest.py  --date 2026-07-02 --root .
# Claude дописывает «Суть», показывает список; после ответа Роустама:
python3 scripts/mark.py --root . assign    --date 2026-07-02 --map "1:telegram_channel,vk;3:vk"
python3 scripts/mark.py --root . published --date 2026-07-02 --item 1 --channel telegram_channel --post-id 123
python3 scripts/mark.py --root . skip      --date 2026-07-02 --item 2
```

Резервная сборка скелета одной командой:

```
python3 scripts/daily_run.py --date 2026-07-02 --root .
```
