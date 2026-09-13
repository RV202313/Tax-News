# Контракт Antigravity и контроль выпусков

Это единственный рабочий контур для налоговых новостей Академии BEPS на Windows.
Antigravity готовит редакционный пакет, Windows доставляет только уже
проверенный пакет, а watchdog подтверждает факт доставки по журналу Telegram.

## Слоты и hand-off

| Слот | Antigravity завершает подготовку не позднее | Файл hand-off |
|---|---:|---|
| 09:00 | 08:50 Europe/Amsterdam | `News Claude/pipeline/approved/YYYY-MM-DD_0900_editorial.json` |
| 13:00 | 12:50 Europe/Amsterdam | `News Claude/pipeline/approved/YYYY-MM-DD_1300_editorial.json` |
| 17:00 | 16:50 Europe/Amsterdam | `News Claude/pipeline/approved/YYYY-MM-DD_1700_editorial.json` |

Antigravity обязан собрать и проверить ровно 10 уникальных материалов по
`Инструкции Налоги/МАНУАЛ_ПОДГОТОВКИ_НОВОСТЕЙ_CODEX.md`, выполнить dry-run
`publish_batch.py` и создать только валидный approved JSON. Он не запускает
`--execute-editorial`: это делает единственная Windows-задача
`Academy BEPS - Auto Publisher` ровно в дедлайн.

Если к дедлайну нет десяти проверенных материалов, Antigravity не создаёт
фиктивный пакет и фиксирует дефицит. Автопубликатор завершится ошибкой, а
watchdog создаст инцидент; это честный сигнал вместо ложной публикации.

## Источник истины о результате

Успешный выпуск существует только если одновременно есть:

1. `runtime-logs/auto-publisher-status.json` со `status: success` и `delivered_count: 10`;
2. 10 соответствующих записей `telegram_editorial` в `News Claude/pipeline/published/YYYY-MM-DD.jsonl`;
3. `News Claude/pipeline/run_records/.../run_record.json` с `delivered_slugs: 10` и без `missing_slugs`.

Код завершения задачи, наличие TCP-порта и сам факт создания approved-файла не
являются доказательством доставки.

## Проверка и эскалация

- `verify-release-sla.py` выполняет локальную проверку без Telegram-клиента.
- `Academy BEPS - Watchdog` запускает её каждые 15 минут и завершается с
  ненулевым кодом при критическом нарушении SLA.
- Для внешнего уведомления можно задать защищённую системную переменную
  `NEWS_ALERT_WEBHOOK_URL`; адрес не хранится в проекте. Повтор одинакового
  инцидента не отправляется.
- `runtime-logs/health-status.json` — единый снимок состояния для портала и
  ручной проверки.

## НейроЮрист

Для НейроЮриста в этой рабочей копии нет установленного фонового исполнителя:
старый `send_neuro_yurist_news.py` содержит статический массив и не должен
автоматически переотправляться. `verify-release-sla.py` явно сигнализирует,
если сегодняшний выпуск не зафиксирован в журнале. Перед включением
автодоставки НейроЮриста нужен отдельный сборщик первичных источников и такой
же approved/delivery/run-record контракт; нельзя подменять его текстовой
инструкцией агенту.
