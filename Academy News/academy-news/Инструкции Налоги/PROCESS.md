# Процесс «Новости Академии» — ежедневный конвейер (v2)

Операционный runbook. Главный документ процесса. Принцип: детерминированный код
(collect/parse/select/digest/state) выполняет прямой HTTP-сбор и обработку;
Claude добирает только браузерные источники и редактирует «Суть». Ошибка одного
источника не валит прогон. Факты только из источника. Публикация — только после
явного «да» по каждому посту.

Редакционный принцип отбора: тема важна только в связке со страной. Ключевые
страны: Россия, Беларусь, Казахстан, Узбекистан, Нидерланды, ОАЭ. Вторая линия: бывший СССР,
кроме Беларуси и Украины, с учётом того, что Россия/Казахстан/Узбекистан уже в
ядре. Третья линия: всё остальное, включая Китай, США, Европу, Иран. Главная
тема — трансфертное ценообразование; TP по ключевой стране
должно вытеснять общие Pillar 2 / VAT / treaty новости по третьей линии.

## 1. Схема

```
FETCH → PARSE → SELECT → DIGEST → [вы: каналы/правки] → DRAFT → PUBLISH (Postiz) → LOG
```

## 2. Ежедневный прогон (судебный блок 07:00; общий старт 08:00, готовность к 09:00)

**Scheduler-of-record:** одна владелец-управляемая desktop Cowork-задача
`academy-news-daily`, 08:00 Europe/Amsterdam. `launchd/*.plist` — только
неустановленные шаблоны: по проверке `launchctl` 2026-07-18 ни daily-, ни
court-agent не загружен. Их нельзя включать параллельно Cowork. Судебный шаг
07:00 сейчас запускается вручную или явно из Cowork; пока владелец не назначит
ему активный scheduler, это операционный blocker.

Фактическое расписание: в 07:00 выполняется отдельный судебный прогон
`court_morning_run.py` (только `ru_ras` + `nl_rechtspraak` + анализ full text);
затем Клод стартует в ~08:00 CEST и завершает дайджест к 09:00 — параллельно с
циклом Codex (мануал Codex §2). Прежние отметки «09:00»/«09:02» в этом документе
и журнале устарели и исправлены. Боевой сбор выполняет Cowork-задача (Claude), а
не launchd-агент `com.academy.news.daily` (он ни разу не сработал; см.
ДОРОЖНАЯ_КАРТА_v2 §0, п.3).

Что делает Claude по шагам. Дата прогона = сегодня (формат YYYY-MM-DD).

### a. FETCH — сбор сырья

Основной сбор с мака:

```
python3 scripts/collect_sources.py --date {дата}
```

Скрипт читает методы и endpoints только из `config/sources.yaml`, использует
браузерный UA, таймауты, ретраи/backoff и RSS-first с HTML-fallback. Сырьё пишет
байт-в-байт в `pipeline/raw/{дата}/{source_id}_{n}.txt`, покрытие — в
`collection_manifest.json` и `runs.sources_ok/sources_failed`. Источник с
`method: chrome` отмечается `manual`, но не создаёт ложную аварийную тревогу.
Для точечной диагностики: `--only source_id`.

- **nl_rechtspraak** — `collect_sources.py` автоматически вызывает
  `collect_rechtspraak.py`: два последовательных запроса (сегодня/вчера) с
  серверным subject-фильтром `bestuursrecht_belastingrecht`. Ручной web_fetch
  не использовать. Источник `prefiltered: true`; в отдельном утреннем судебном
  прогоне полный текст тянется для ВСЕХ судебных позиций дня в
  `../court_analysis/extracted_text/rechtspraak/{date}/`, а в итоговой папке
  `../court_analysis/rechtspraak` остаются только substantive решения по
  международному налогообложению. Реестр `../court_analysis/court_decisions.csv`
  хранит все дела дня.
- **nl_belastingdienst_rulings** — fetch официальных страниц Belastingdienst
  по ATR и APA из `sources.yaml`; сохранять HTML/markdown как есть. Это
  отдельный обязательный источник по advance tax rulings / advance pricing
  agreements, не заменяется Taxence/TaxLive.
- **ru_garant / ru_fns / ru_minfin / nl_taxlive** — прямой HTML-транспорт. Garant
  декодируется по charset (windows-1251); даты ФНС извлекаются из листинга.
- **ru_vs** — `collect_vs.py` забирает официальные XHR-листинги обзоров
  практики и налоговых новостей ВС РФ. Обзоры помечаются
  `item_type=court_review`.
- **intl_regfollower / nl_taxence** — RSS-first; tracking-параметры URL
  нормализуются, рекламные и agenda-ссылки отсекаются правилами источника.
- **nl_belastingdienst_rulings** — прямой HTML ATR/APA; компактная дата
  `YYYYMMDD` извлекается из названия документа, поэтому архив режется окном.
- **ru_ras** — `collect_ru_ras.js` подключается к уже открытому
  CDP-Chrome, дожидается JS-формы и выполняет ОДИН точный запрос
  `избежании двойного налогообложения` с паузами 15–25 секунд между сетевыми
  действиями. Затем `fetch_ras_fulltext.js` скачивает PDF всех найденных дел в
  `../court_analysis/extracted_text/ras/{date}/`, а `court_protocol.py`
  извлекает текст и оставляет в `../court_analysis/ras` только substantive
  решения по международному налогообложению. Реестр
  `../court_analysis/court_decisions.csv` хранит все дела дня. Прямые POST к
  `/Ras/Search` запрещены. Если CDP недоступен, source state=`manual` и
  неполнота видна в дайджесте.
- **telegram_leads** — одноразовый `collect_telegram.py`, не listener. Перед
  чтением каналов он fail-closed требует владельца session = текущий OS-user,
  права `0600` или
  строже, межпроцессный lock и чистый `lsof`, а первым
  Telegram-вызовом делает `get_me()==academy_of_beps`; после сбора всегда
  отключается. Лид — вторичный сигнал; первоисточник обязательно
  проверяется Codex перед публикацией.
- **nl_fd** — `web_fetch` не работает (пейволл): пропустить, пометить «добор
  через Chrome в сессии публикации».

### b. PARSE → SELECT → DIGEST (детерминированное ядро)

```
pip install pyyaml --break-system-packages -q
```

Затем из папки проекта:

```
python3 scripts/parse_feeds.py  --date {дата}
python3 scripts/select_news.py  --date {дата} --top 15
python3 scripts/make_digest.py  --date {дата}
```

Резервный ручной путь одной командой (без заполнения «Сути» Claude):

```
python3 scripts/daily_run.py --date {дата}
```

- `parse_feeds.py` → `pipeline/inbox/{дата}_items.jsonl`.
- `select_news.py` → `pipeline/shortlist/{дата}_shortlist.json` (скоринг по
  `config/topics.yaml` + `config/jurisdictions.yaml`, дедуп через
  `state/news_state.sqlite` и каталог публикаций, кап 15). Перед отбором
  идемпотентно индексируется `../ОПУБЛИКОВАННЫЕ_НОВОСТИ.md`; внутри текущей
  пачки повторы между источниками удаляются по URL/ECLI/нечёткому заголовку.
  Материалы без целевой страны — фон: максимум 1 в день; третья линия — максимум
  2 в день. Для широких лент Garant/ФНС одного тега `ru_tax_admin` недостаточно:
  обязательна целевая тема из `require_topics_any`.
- `make_digest.py` → скелет `pipeline/digest/{дата}_digest.md` с плейсхолдерами
  «Суть». Telegram-лиды видимо помечаются требованием проверки
  первоисточника; вовлечённость даёт только ограниченный бонус ранга.

### c. Заполнить «Суть»

В `pipeline/digest/{дата}_digest.md` заменить каждый
`- Суть: [ЗАПОЛНИТ CLAUDE: …]` на 1–3 предложения СТРОГО из содержимого
raw-файлов (факты, номера актов, суды, даты — ничего не додумывать). Естественный
русский язык, стиль практикующего налогового юриста, без канцелярита и
англо-русского суржика. Все слова и обороты с обычным русским эквивалентом
переводить. Английское написание оставлять только для официальных аббревиатур,
общепринятых обозначений и собственных названий без точного русского аналога
(`BEPS`, `OECD`, `HMRC`, `ECLI`, `MLI`, `GloBE` и подобные); при необходимости
кратко пояснять их по-русски. Заголовки и структуру блоков не менять — только
«Суть».
Частные правила:
- материалы без подтверждённой даты (например, кэш-снапшот regfollower) — в конце
  строки Суть пометка `(дата публикации не подтверждена — кэш-снапшот источника,
  сверить при подготовке поста)`;
- материалы nl_taxence — суть по-русски (перевести смысл тизера), в конце указать
  суд, если он назван (Rechtbank Gelderland; Hof 's-Hertogenbosch; Gerechtshof
  Amsterdam);
- данных не хватает — ставить `[ПРОВЕРИТЬ]`, не выдумывать.

### d. Отправить дайджест сообщением

Нумерованный список; у каждого пункта: заголовок, источник, ссылка, суть,
предложенные каналы. В конце напомнить формат ответа:
`3 → tg; 5 → vk; 7 → tg+vk, правка: …` — и напомнить про фразу
`режим публикации`.

## 3. Ответ Роустама и разметка каналов

После ответа Роустама — разметить назначения:

```
python3 scripts/mark.py assign --date {дата} --map "3:telegram_channel;5:vk;7:telegram_channel,vk"
```

(номера — это `n` из шортлиста; правки текста учитываются на этапе черновиков).

## 4. Режим публикации (только после явного «да» по каждому посту)

### a. Черновики
По `config/channels.yaml`: лимиты длины, тон, дисклеймер для судебных материалов,
ссылка на первоисточник. Каждый черновик проходит языковую проверку: заголовок,
текст и блок «Почему это важно» не должны содержать переводимые английские
слова или обороты внутри русского текста. По одному блоку на пост, каждый — на
подтверждение.

### b. Добор закрытых источников
`fd.nl` / полные тексты `garant` — через Claude in Chrome
(пользователь залогинен в открытом окне). `ras.arbitr.ru` должен быть добран
раньше, до SELECT, потому что это обязательный источник судебных решений.

### c. Approved JSON и сухая проверка

Ровно 10 постов сохраняются в `pipeline/approved/{выпуск}.json` по схеме
`config/approved.schema.json`. Для каждого нужны caption, первоисточник,
изображение/оригинальная карточка, channels и поля approval
`status/by/evidence`. Telegram lead требует `primary_source_verified: true`.

Первый шаг всегда без сети:

```
/Users/roustamvakhitov/Downloads/Academy\ Network/Телеграм/.venv-telethon/bin/python \
  scripts/publish_batch.py pipeline/approved/{выпуск}.json
```

Без execute-флага скрипт только валидирует выпуск и собирает карточки.

### d. Доставка единым движком

- `--execute-editorial` — только редакционный чат `-1004472011991`. Первый
  Telegram API-вызов — `get_me`; допускается только `academy_of_beps`.
  Та же account-проверка повторяется непосредственно перед каждым `send_file`;
  до открытия session также обязательны права `0600` или строже, lock и `lsof`.
  Главный Telegram-канал движок не трогает. `scheduled_at` поддерживается,
  но не подставляется по умолчанию.
- `--execute-non-telegram` — VK/LinkedIn через Postiz, site через
  WordPress, email как локальный draft. LinkedIn всегда draft. Telegram через
  Postiz явно отключён.
- Перед первым Postiz-запуском: создать `.env.postiz`, запустить
  localhost:4007 и выполнить `python3 scripts/postiz_discover.py --write`. В config
  записываются только однозначные VK/LinkedIn id; TG игнорируется.

После каждой успешной доставки движок сразу дописывает
`pipeline/published/{дата}.jsonl`. Для Telegram затем идемпотентно обновляется
корневой каталог. Если процесс упал между сайдкаром и каталогом, повторный
запуск чинит каталог без повторной отправки.
Также в execute-режиме сохраняется immutable run-of-record snapshot:
`pipeline/run_records/{date}/{run_id}/`. `run_id` содержит release, delivery
scope и первые 12 знаков SHA-256 approved-файла. `run_record.json` хранит
SHA-256/размер каждого слепка, release-only sidecar и coverage каталога;
существующий `run_id` не перезаписывается. Для выпусков до введения механизма
разрешён только честный `--backfill-run-record`: approved и release-sidecar
фиксируются, а изменяемые shortlist/digest/manifests помечаются
`not_backfilled`, без ретроспективной подмены.
В schema v3 состав релиза доказывают только `approved.json` и release-only
sidecar. Дневные shortlist/digest/manifests могут быть сняты рядом
только как `context_only` с `release_lineage=not_asserted`: их нельзя
выдавать за состав фактического выпуска. Проверка
`publish_batch.py --verify-run-record <.../run_record.json>` пересчитывает
SHA-256, размеры и delivery coverage из слепков.

### e. Локальная сквозная приёмка

`tests/test_phase4_acceptance.py` без сети собирает во временном root
пять типов источников (Rechtspraak, РАС, ВС, Минфин, Telegram-
лиды), отбирает ровно 10, собирает дайджест и карточки, записывает
доставку фейк-клиентом в sidecar/каталог и проверяет нулевой повтор.
Это не является разрешением на боевую публикацию.

```sh
/Users/roustamvakhitov/Downloads/Academy\ Network/Телеграм/.venv-telethon/bin/python \
  tests/test_phase4_acceptance.py
```

## 5. Состояние и дедупликация

- Источник правды опубликованных материалов — корневой каталог
  `ОПУБЛИКОВАННЫЕ_НОВОСТИ.md`; его ключи URL/ECLI/акт/заголовок/тема
  индексируются в SQLite перед каждым отбором.
- Источник правды кандидатов и статусов конвейера — `state/news_state.sqlite`
  (точный URL/ECLI + нечёткое совпадение заголовков ≥ 0.9 за 30 дней).
  `newsdb.py` работает через зеркало в `/tmp` из-за FUSE. Обратная синхронизация
  атомарна (`os.replace`); при ошибке цель не перезаписывается, сбой пишется в
  `log/newsdb_sync.log`; перед восстановлением битой БД создаётся один из пяти
  ротационных бэкапов.
- `log/pipeline_log.md` — человекочитаемый журнал изменений и прогонов.

## 6. Отказы и правила

- Ошибка одного источника не валит прогон (пустой/битый файл → 0 элементов, без
  падения).
- Chrome/manual-источник показывается как неполное покрытие, но не как ложный
  сетевой сбой; постоянный listener/polling новостной сессии не создаётся.
- Факты только из источника; при нехватке данных — пометка `[ПРОВЕРИТЬ]`.
- Окно свежести (`select_news.py`) режет датированное старьё — в т.ч.
  кэш-снапшоты regfollower / taxlive.
- Тюнинг качества отбора — это `config/topics.yaml` (ключевые слова, приоритеты
  тем), НЕ код.
- Публикация — только после явного «да» по каждому посту; ссылка на первоисточник
  обязательна; для судебных разборов — дисклеймер.

## 7. Файлы проекта (карта)

- `config/`
  - `sources.yaml` — единая точка правды: endpoints/RSS, метод (`http/chrome`),
    parser, lang, HTML include/exclude, тематические и текстовые гейты.
  - `topics.yaml` — темы, ключевые слова (ru/nl/en), приоритеты (тюнинг отбора).
  - `jurisdictions.yaml` — приоритет стран и лимиты: ядро, вторая линия, третья линия.
  - `channels.yaml` — каналы публикации: лимиты, тон, дисклеймеры.
  - `postiz.yaml` — id каналов Postiz (GET /integrations).
- `scripts/`
  - `collect_sources.py` — единый прямой HTTP-транспорт, манифест покрытия.
  - `collect_rechtspraak.py` — специализированный последовательный Atom-сбор.
  - `fetch_rechtspraak_fulltext.py` — полные XML-тексты Rechtspraak.
  - `collect_vs.py` / `collect_ru_ras.js` — ВС РФ по HTTP и РАС по CDP/UI.
  - `fetch_ras_fulltext.js` — скачивает все PDF RAS текущего дня через
    браузерный контекст.
  - `court_protocol.py` — анализирует полные тексты всех court-cases дня,
    пишет все дела в `../court_analysis/court_decisions.csv`, а в
    `../court_analysis/ras|rechtspraak` оставляет только substantive дела.
  - `court_morning_run.py` — отдельный court-only прогон в 07:00; после двух
    точечных `collect(..., only=...)` сохраняет объединённый
    `raw/{date}/collection_manifest.json` и court-only
    `raw/{date}/collection_manifest_court.json`; court-only receipt отдельно
    пересчитывает registry/full-text/analysis coverage по обоим
    источникам и ставит `complete=false` при любом gap.
  - `collect_telegram.py` — одноразовый сбор лидов без фонового клиента.
  - `parse_feeds.py` — raw → inbox (RSS/Atom, rechtspraak, HTML, markdown fallback).
  - `select_news.py` — скоринг, дедуп, кап → shortlist.
  - `make_digest.py` — shortlist → скелет дайджеста.
  - `mark.py` — ручные пометки (assign / published / skip).
  - `newsdb.py` — слой SQLite (зеркало /tmp ↔ state/).
  - `common.py` — единая загрузка env для CLI/portal.
  - `daily_run.py` — ручной резерв collect→parse→select→digest.
  - `postiz_publish.md` — рецепт публикации через Chrome → localhost:4007.
  - `cards.py` — единая генерация оригинальных редакционных карточек.
  - `publish_batch.py` — approved JSON → dry-run / редчат / не-TG каналы.
  - `postiz_discover.py` — discovery и запись id VK/LinkedIn.
  - `README_scripts.md` — подробное описание ядра.
- `pipeline/`
  - `raw/{дата}/{source_id}_{n}.txt` — сырьё от web_fetch.
  - `raw/{дата}/collection_manifest*.json` — покрытие источников (общий и court-only).
  - `raw/probe/*.txt` — фикстуры источников (для офлайн-тестов).
  - `inbox/{дата}_items.jsonl` — распарсенные элементы.
  - `shortlist/{дата}_shortlist.json` — отобранное (n, item_id, каналы).
  - `digest/{дата}_digest.md` — дайджест (Суть дописывает Claude).
  - `run_records/{date}/{run_id}/` — immutable хешированный слепок
    фактически выпущенного прогона.
- `state/news_state.sqlite` — источник правды кандидатов/статусов и
  производный дедуп-индекс каталога; факт размещения он не заменяет.
- `log/pipeline_log.md` — журнал прогонов.
- `tests/test_offline.py` — офлайн-прогон ядра без сети (parse→select→digest).
- `tests/test_phase1.py` — регрессии персистентности, RSS/HTML, транспорта,
  каталога и дедупликации.
- `tests/test_phase2.py` — ВС/РАС, полный текст Rechtspraak, Telegram-лиды,
  безопасность сессии и ручной CDP-статус.
- `tests/test_phase3.py` — валидация 10 постов, account gate, sidecar/каталог,
  защита от повторной отправки и медиа Postiz.
- `tests/test_phase4_acceptance.py` — сквозная офлайн-приёмка 5 типов
  источников → 10 постов → sidecar/каталог → нулевой повтор.
- `requirements-runtime.txt` — закреплённые runtime-зависимости движка.
- `ACCEPTANCE_REPORT_2026-07-18.md` — итог технической приёмки и внешние блокеры.
- `КОНЦЕПЦИЯ_v2.md` — концепция и поток данных.
- `ENDPOINTS_REPORT.md` — отчёт по проверке endpoints и квиркам web_fetch.
- `.env.postiz` / `.env.postiz.example` — ключ доступа к Postiz API.
