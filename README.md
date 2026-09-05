# SPORTS MATE

Telegram Mini App для поиска партнёров по спорту рядом. MVP поддерживает реальный серверный цикл: вход через Telegram → профиль → активность → отклик → решение → контакт → подтверждение встречи → оценка.

## Быстрый запуск через Docker Compose

Нужны Docker Engine с Compose v2 и свободные порты 5173, 8000, 5432.

```bash
cp .env.example .env
# заполните SESSION_SECRET, INTERNAL_API_KEY и при необходимости TELEGRAM_BOT_TOKEN
docker compose up --build
```

- Web: <http://localhost:5173>
- API/OpenAPI: <http://localhost:8000/docs>
- Healthcheck: <http://localhost:8000/health>

В `.env.example` dev-вход включён для локального запуска. Конфигурация не позволит включить его в `staging` или `production`.

Остановка: `docker compose down`. Данные PostgreSQL остаются в volume. Для удаления только локальных dev-данных: `docker compose down -v` — эта команда необратима.

## Запуск без Docker

Нужны Python 3.12+, Node.js 22+ и PostgreSQL 16+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'apps/api[dev]'
cp .env.example .env
# укажите локальный DATABASE_URL
cd apps/api && ../../.venv/bin/alembic upgrade head
cd ../.. && .venv/bin/uvicorn app.main:app --app-dir apps/api --reload
```

В другом терминале:

```bash
.venv/bin/python -m app.worker  # запускать из apps/api
pnpm --dir apps/web install
VITE_API_URL=http://localhost:8000 pnpm --dir apps/web dev
```

## Проверки

```bash
cd apps/api && ../../.venv/bin/pytest -q && ../../.venv/bin/ruff check app tests migrations
cd ../web && pnpm run lint && pnpm run build
```

SQLite используется только быстрыми API-тестами. Конкурентное принятие последнего места необходимо дополнительно прогнать на чистой PostgreSQL через Compose:

```bash
docker compose up -d db
docker compose run --rm migrate
docker compose run --rm api pytest -q
```

## Конфигурация и безопасность

Токен бота читается только backend/worker. Frontend получает `VITE_API_URL` и при необходимости `VITE_BOT_USERNAME`; переменные `VITE_*` публичны и не должны содержать секреты. Сессионный bearer-токен хранится в `sessionStorage` вкладки. Идентичность, роли и доступ к контакту всегда проверяются сервером.

Рабочие решения и ограничения: [docs/decisions.md](docs/decisions.md). Настройка Telegram: [docs/telegram-setup.md](docs/telegram-setup.md). Текущий статус: [docs/implementation-status.md](docs/implementation-status.md).

Развёртывание frontend на GitHub Pages и backend через Render Blueprint: [docs/deployment.md](docs/deployment.md).
