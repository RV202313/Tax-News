# Веб-портал «Новости Академии»

Локальный редакционный портал: ежедневная матрица новостей, журнал покрытия
источников, выбор каналов, черновики и подтверждённая отправка в Postiz/CMS.

## Запуск

```bash
cd "/Users/roustamvakhitov/Downloads/Новости Академии/News Claude"
cp .env.portal.example .env.portal
python3 portal/server.py
```

Откройте `http://127.0.0.1:8765`. Если задан `PORTAL_TOKEN`, откройте один
раз `http://127.0.0.1:8765/?token=ВАШ_ТОКЕН`: он будет сохранён только в
localStorage этого браузера. Портал по умолчанию не открыт в сети.

## Ежедневный запуск

Проверьте конфигурацию, затем установите LaunchAgent:

```bash
cp launchd/com.academy.news.daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.academy.news.daily.plist
launchctl kickstart -k gui/$(id -u)/com.academy.news.daily
```

Он запускает в 09:00 `collect_sources.py`, затем существующие parse/select/
digest. Открытые HTTP-источники собираются автоматически. RAS и FD
намеренно помечаются `manual`: нужны разрешённая браузерная сессия и
подписка, а не обход антибот-защиты.

## Перед первой реальной отправкой

1. Скопируйте `.env.postiz.example` в `.env.postiz`, запустите Postiz и
   заполните integration ID Telegram/VK в `config/postiz.yaml`.
2. Для сайта задайте WordPress REST API и Application Password в
   `.env.portal`. Для другой CMS добавьте отдельный адаптер в
   `portal/publishers.py`.
3. Создайте Telegram-бота и заполните `TELEGRAM_BOT_TOKEN`/
   `TELEGRAM_DIGEST_CHAT_ID`, если нужно уведомление.

Портал не выполняет публикацию автоматически: внешняя отправка возможна
только после нажатия «Отправить» и второго подтверждения. Если доставка
возвращает ошибку, она попадает в `pipeline/published/*_delivery.jsonl`; тот
же материал остаётся в очереди со статусом `failed`, и редактор может
безопасно повторить отправку вручную после проверки причины.
