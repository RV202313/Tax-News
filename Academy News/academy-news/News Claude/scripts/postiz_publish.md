# Публикация через Postiz (localhost:4007) из Claude in Chrome

> Степень верификации: **высокая**. Контракт извлечён из исходников
> `gitroomhq/postiz-app` (клон в песочнице, commit `6b2e77f` от 2026-07-02,
> файлы `apps/backend/src/public-api/routes/v1/public.integrations.controller.ts`,
> `apps/backend/src/services/auth/public.auth.middleware.ts`,
> `libraries/nestjs-libraries/src/dtos/posts/create.post.dto.ts`,
> `.../providers-settings/all.providers.settings.ts`, `var/docker/nginx.conf`)
> и независимо перепроверен по официальной документации docs.postiz.com
> (`/public-api`, `/public-api/posts/create`, `/public-api/integrations/list`).
> Оба источника совпали по всем полям ниже. Единственное, что НЕ проверено
> живым вызовом — это первый discovery-запрос (Шаг 1) на вашей реальной
> инсталляции: сделайте его один раз и считайте контракт окончательно
> подтверждённым после первого успешного ответа.

## Предусловия

- Postiz поднят через docker-compose (папка `postiz/`) и отвечает на
  `http://localhost:4007` — проверить открытием страницы в браузере.
- В самом Postiz (UI → Settings → Channels) подключены нужные каналы:
  Telegram-канал и VK. Для каждого канала там же можно увидеть его
  `integration id`, но проще получить все id разом через Шаг 1 (discovery).
- API-ключ создан и лежит в `News Claude/.env.postiz`:
  ```
  POSTIZ_API_KEY=<ваш ключ>
  ```
  Взять ключ: Postiz UI → Settings → Developers → Public API → **API Key**
  (кнопка Reveal/Copy). Это НЕ то же самое, что MCP-токен на той же
  странице — MCP использует `Authorization: Bearer <key>`, а REST Public
  API (то, что используем здесь) — **без** `Bearer`, см. Шаг 1.

## Шаг 1. Discovery (один раз)

Цель — получить список подключённых каналов и их `integration id`, а заодно
живьём подтвердить контракт на вашей инсталляции.

1. Открыть вкладку `http://localhost:4007` инструментом
   `mcp__claude-in-chrome__navigate`.
2. Выполнить `mcp__claude-in-chrome__javascript_tool` со следующим
   JS-шаблоном (same-origin fetch — вкладка уже открыта на localhost:4007,
   поэтому CORS не мешает). Заменить `__API_KEY__` на значение из
   `.env.postiz`:

```js
(async () => {
  try {
    const res = await fetch('/api/public/v1/integrations', {
      method: 'GET',
      headers: {
        'Authorization': '__API_KEY__'
      }
    });
    const status = res.status;
    let body;
    try {
      body = await res.json();
    } catch (e) {
      body = await res.text();
    }
    return JSON.stringify({ status, body });
  } catch (e) {
    return JSON.stringify({ error: String(e) });
  }
})();
```

3. Ожидаемый ответ (`status: 200`) — массив объектов вида:
   ```json
   [
     {
       "id": "cm4ean69r0003w8w1cdomox9n",
       "name": "Имя канала",
       "identifier": "telegram",
       "picture": "https://...",
       "disabled": false,
       "profile": "handle",
       "customer": { "id": "...", "name": "..." }
     }
   ]
   ```
   Найти в массиве объекты с `identifier: "telegram"` и `identifier: "vk"`
   (и, если ведём его через Postiz, `identifier: "linkedin"` или
   `"linkedin-page"`), взять их `id`.
4. Вписать найденные id в `config/postiz.yaml` → `channel_map`:
   - `telegram_channel.postiz_integration_id`
   - `vk.postiz_integration_id`
   - `linkedin.postiz_integration_id` (если применимо)

Discovery повторять только если каналы переподключались/меняли id.

## Шаг 2. Публикация поста

`mcp__claude-in-chrome__javascript_tool` со следующим JS-шаблоном (тот же
same-origin fetch на открытой вкладке `localhost:4007`). Плейсхолдеры:

- `__API_KEY__` — ключ из `.env.postiz`
- `__TYPE__` — `draft` | `schedule` | `now`
- `__DATE_ISO__` — ISO 8601 UTC, напр. `2026-07-03T09:00:00.000Z`
  (для `now` дата всё равно обязательна полем DTO, но публикация идёт
  немедленно и значение даты игнорируется; для `draft`/`schedule` — реальное
  время публикации/план)
- `__INTEGRATION_ID__` — id канала из Шага 1
- `__CONTENT__` — текст поста, **обязательно экранированный как JS-строка**
  (перевести переносы строк в `\n`, экранировать `"` и `\`, например через
  `JSON.stringify(text)` при генерации плейсхолдера — тогда просто вставить
  результат `JSON.stringify` вместо `"__CONTENT__"` целиком, включая кавычки)

Минимальный валидный payload для Telegram и VK (у обоих нет собственных
настроек — только `{"__type": "..."}`, подтверждено и в исходниках, и в
докс):

```js
(async () => {
  try {
    const payload = {
      type: '__TYPE__',
      date: '__DATE_ISO__',
      shortLink: false,
      tags: [],
      posts: [
        {
          integration: { id: '__INTEGRATION_ID__' },
          value: [
            {
              content: "__CONTENT__",
              image: []
            }
          ],
          settings: {
            __type: 'telegram'
          }
        }
      ]
    };

    const res = await fetch('/api/public/v1/posts', {
      method: 'POST',
      headers: {
        'Authorization': '__API_KEY__',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const status = res.status;
    let body;
    try {
      body = await res.json();
    } catch (e) {
      body = await res.text();
    }
    return JSON.stringify({ status, body });
  } catch (e) {
    return JSON.stringify({ error: String(e) });
  }
})();
```

Для VK заменить `settings.__type` на `'vk'`. Для LinkedIn — `'linkedin'`
(личный профиль) или `'linkedin-page'` (страница компании); у LinkedIn тоже
нет обязательных доп.настроек, но см. правило ниже — LinkedIn всегда
`draft`.

**Важные поля DTO (обязательны все, даже если кажутся неважными для
черновика):**
- `type` — обязателен, одно из `draft | schedule | now`.
- `date` — обязателен (ISO date-string) для ЛЮБОГО `type`, включая `now`.
- `shortLink` — обязателен, `boolean` (использовать `false`, если не нужны
  короткие ссылки).
- `tags` — обязателен как массив (можно `[]`).
- `posts[].integration.id` — обязателен.
- `posts[].value[]` — минимум 1 элемент; `content` обязателен (может быть
  пустой строкой, если пост состоит только из картинки), `image` — массив
  (можно `[]`).
- `posts[].settings.__type` — обязателен и валидируется, если `type !==
  'draft'`. Для черновика (`draft`) можно не передавать `settings` вовсе,
  но безопаснее передавать всегда с правильным `__type`.

**С картинкой:** сначала загрузить файл через `POST /api/public/v1/upload`
(multipart, поле `file`) или `POST /api/public/v1/upload-from-url` (body
`{"url": "https://..."}`, только публичные https-URL) — оба возвращают
`{"id": "...", "path": "https://...", "name": "...", ...}`. Затем вставить
`{"id": "<id>", "path": "<path>"}` в `posts[].value[].image[]`. Из
JS-контекста в браузере с уже загруженным файлом на диске multipart-upload
неудобен — практичнее использовать `upload-from-url`, если картинка уже
доступна по публичному https-адресу (например, уже лежит на сайте
академии), либо загружать файл через сам Postiz UI и брать готовый `path`.

## Шаг 3. Ответ и ошибки

**Успех:** `status: 200`, тело — массив вида
```json
[{ "postId": "cm...", "integration": "cm..." }]
```
(может быть несколько элементов, если пост уходил на несколько интеграций
за один вызов — здесь используем по одной интеграции на вызов, так что
элемент один).

**Куда записать post id:**
- Если в `scripts/` появится обёртка `mark.py` — использовать её
  (`python3 scripts/mark.py published --item <id> --channel <канал> --post-id
  <postId>`), она должна писать в таблицу `published` (`newsdb.py`:
  `item_id, channel, posted_at, post_id, post_url`).
- На сегодня (`mark.py` в репозитории ещё нет) — записывать через прямой
  вызов функций `newsdb.py` (таблица `published`) и обязательно обновить
  строку в `log/pipeline_log.md`, сменив статус на
  `опубликовано:<канал>` (формат журнала — см. шапку файла).

**Типовые ошибки:**

| Код | Причина | Что делать |
|-----|---------|------------|
| 401 | `Authorization` отсутствует или ключ не распознан (`{"msg": "No API Key found"}` / `{"msg": "Invalid API key"}`) | Проверить `.env.postiz`; убедиться, что заголовок отправлен БЕЗ `Bearer ` — только сырой ключ |
| 400 | Нет `date`, `shortLink`, `tags`, пустой `value[].content` без картинки, или settings не прошли валидацию (`type !== draft`) | Сверить payload с обязательными полями DTO выше; для `draft` можно упростить, для `schedule`/`now` — все поля провайдера обязательны |
| 400 | Несуществующий `integration id` (`{"msg": "Integration with id ... not found"}`) | Перезапустить Шаг 1 (discovery), id мог измениться при переподключении канала |
| 403 | Ключ валиден, но не принадлежит организации-владельцу ресурса | Обычно не актуально при одной организации; проверить, не создан ли второй ключ |
| 429 | Превышен лимит запросов на `/posts` (по докс — 30 или 90–100/час в зависимости от версии, см. примечание ниже) | Не публиковать пачками чаще; ждать и повторить |
| 5xx | Серверная ошибка Postiz | Проверить логи docker-compose (`docker logs postiz`), повторить с backoff |

*Примечание о лимите:* официальная документация внутренне противоречива —
на странице `/public-api` указано «90 запросов/час (100 для облака)», а во
встроенной OpenAPI-спеке на страницах `/posts/create` и `/integrations/list`
— «30 запросов/час». Для self-hosted лимит также настраивается через
переменную окружения `API_LIMIT`. Не полагаться на точное число — избегать
частых вызовов подряд.

## Правила

- Публиковать/планировать **только после явного «да» пользователя по
  каждому посту** (промт-4 из общего пайплайна). Discovery (Шаг 1) — не
  публикация, его можно выполнять свободно.
- **LinkedIn — всегда `draft`.** Никогда не отправлять `type: 'schedule'`
  или `type: 'now'` на LinkedIn-интеграцию без отдельного явного
  подтверждения — по умолчанию только черновик, ревью и отправка руками
  через Postiz UI.
- Дата (`date`) — обязательна для всех типов, в UTC ISO 8601
  (`YYYY-MM-DDTHH:mm:ss.sssZ`).
- Контент экранировать как JS-строку перед вставкой в шаблон (см. Шаг 2) —
  иначе кавычки/переносы строк сломают JSON.
- После публикации — обязательно зафиксировать `postId` (Шаг 3), иначе
  дедупликация и статус в `pipeline_log.md` разъедутся с реальностью.

## Как проверялось (детали для аудита)

**Источник 1 — клон исходников** (`git clone --depth 1
https://github.com/gitroomhq/postiz-app /tmp/postiz-app`, выполнен в
песочнице `mcp__workspace__bash`, сеть разрешена):

- Базовый путь контроллера: `@Controller('/public/v1')` в
  `public.integrations.controller.ts`.
- Авторизация (`public.auth.middleware.ts`): читает
  `req.headers.authorization`; если значение начинается с `pos_` —
  трактуется как OAuth2-токен (`getOrgByOAuthToken`), иначе передаётся
  **как есть** в `organizationService.getOrgByApiKey(auth)` — то есть без
  `Bearer `-префикса.
- Маршрутизация наружу: `docker-compose.yaml` внутри проекта задаёт
  `NEXT_PUBLIC_BACKEND_URL: 'http://localhost:4007/api'` и порт-маппинг
  `"4007:5000"`. Внутри контейнера `var/docker/nginx.conf` слушает `5000` и
  проксирует `location /api/ { proxy_pass http://localhost:3000/; }` —
  снимает префикс `/api/` и шлёт на backend (NestJS, без глобального
  префикса) на внутренний порт `3000`. Итог: внешний URL
  `http://localhost:4007/api/public/v1/...` → внутри контейнера
  `http://localhost:3000/public/v1/...`, что и обслуживает контроллер.
- DTO поста — `create.post.dto.ts` (`CreatePostDto`, класс `Post`, класс
  `PostContent`) и `providers-settings/all.providers.settings.ts`
  (подтверждает, что `telegram` и `vk` используют `EmptySettings`, то есть
  только `{"__type": "..."}`).
- `MediaDto` (`dtos/media/media.dto.ts`) требует `id` и `path`; ответ
  `MediaService.saveFile`/`MediaRepository.saveFile` возвращает именно эти
  поля (`{id, name, originalName, path, thumbnail, alt}`), то есть ответ
  upload-эндпоинта подставляется в `image[]` без трансформации.

**Источник 2 — официальная документация** (`mcp__workspace__web_fetch` на
`docs.postiz.com/public-api`, `.../public-api/posts/create`,
`.../public-api/integrations/list`):

- Явный пример: `curl -H "Authorization: your-api-key" ...` — без `Bearer`, <!-- gitleaks:allow; это плейсхолдер -->
  совпадает с кодом.
- Таблица self-hosted base URL: `https://{NEXT_PUBLIC_BACKEND_URL}/public/v1`
  — при `NEXT_PUBLIC_BACKEND_URL=http://localhost:4007/api` даёт
  `http://localhost:4007/api/public/v1`, совпадает с независимым выводом из
  nginx.conf.
- Полная встроенная OpenAPI-спека подтверждает `CreatePostRequest` (те же
  обязательные поля: `type, date, shortLink, tags`), `EmptySettings.__type`
  enum включает `telegram` и `vk`, и формат ответа `POST /posts` —
  `[{postId, integration}]`.

Оба источника независимо совпали по каждому проверяемому полю — конфликтов
не обнаружено (кроме отмеченного выше несоответствия лимита запросов внутри
самой докс-страницы, не влияющего на структуру запроса/ответа).
