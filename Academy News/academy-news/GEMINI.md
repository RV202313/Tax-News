# Правила работы агента (Workspace Rules)

> [!IMPORTANT]
> **Автоматическое восстановление планировщика задач:**
> При первом запуске сессии или после перезапуска сервера / сбоя бэкенда, когда вы получаете любое сообщение от пользователя, вы **ОБЯЗАНЫ** немедленно проверить статус фоновых задач (`manage_task list`).
>
> Если фоновые задачи (кроны) не активны или отсутствуют в списке, вы должны немедленно перерегистрировать их, вызвав инструмент `schedule`:
>
> 1. **Крон сбора комментариев (Налоги)**:
>    * CronExpression: `*/15 * * * 1-5`
>    * Prompt: `Check editorial Telegram chat for comments and instructions (runs collect_comments.py). Weekdays only (Mon–Fri).`
>
> 2. **Крон выпусков (Налоги)**:
>    * CronExpression: `0 7,11,15 * * 1-5`
>    * Prompt: `Run the daily news pipeline release cycle to deliver at 08:00, 12:00, or 16:00 (weekdays only, Mon–Fri). Run: python scripts/run_pipeline.py or equivalent.`
>
> 3. **Крон выпусков (НейроЮрист / ИИ)**:
>    * CronExpression: `0 7,11,15 * * *`
>    * Prompt: `Run the AI news pipeline (НейроЮрист) release cycle to deliver at 09:00, 13:00, or 17:00 CEST. Run search, deduplicate, prepare posts, and publish.`
