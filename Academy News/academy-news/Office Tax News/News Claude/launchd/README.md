# Статус launchd-шаблонов

Эти plist не являются scheduler-of-record и по проверке `launchctl` от
2026-07-18 не загружены.

- Scheduler-of-record общего конвейера: owner-managed desktop Cowork-задача
  `academy-news-daily`, 08:00 Europe/Amsterdam.
- `com.academy.news.daily.plist` — неактивный резервный шаблон; его расписание
  не считается production-настройкой.
- `com.academy.news.courts.plist` — неактивный шаблон судебного запуска. До
  решения владельца court-run 07:00 выполняется вручную или явным шагом Cowork.

Не загружать оба пути параллельно: это создаст конкурирующие записи в raw,
shortlist/digest и состояние SQLite. Установка или смена scheduler-of-record
требует отдельного решения владельца и обновления `PROCESS.md` и корневого
мануала.
