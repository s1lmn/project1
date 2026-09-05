# Развёртывание

## Frontend: GitHub Pages

Workflow `.github/workflows/pages.yml` собирает `apps/web` и публикует его по адресу `https://s1lmn.github.io/project1/`. Для SPA используется hash-routing, поэтому deep link активности имеет вид `https://s1lmn.github.io/project1/#/activities/<id>`.

В настройках репозитория нужно выбрать **Settings → Pages → Source: GitHub Actions** и добавить Actions variables:

- `VITE_API_URL` — HTTPS URL развёрнутого API без завершающего `/`;
- `VITE_BOT_USERNAME` — `sportssmatebot`.

GitHub Pages обслуживает только статический frontend. API, PostgreSQL и постоянно работающий worker требуют отдельного runtime.

## Backend: Render Blueprint

`render.yaml` описывает PostgreSQL, FastAPI и worker. После подключения репозитория в Render Blueprint необходимо указать секрет `TELEGRAM_BOT_TOKEN` для API и worker и проверить `/health`. API выполняет `alembic upgrade head` перед запуском. Затем запишите фактический URL API в GitHub variable `VITE_API_URL` и перезапустите Pages workflow.

Предложенное имя API: `sports-mate-api-s1lmn`. Если Render его примет, URL будет `https://sports-mate-api-s1lmn.onrender.com`; фактический URL нужно взять из панели Render, не угадывать.

Бесплатный web runtime может засыпать, а background worker в Blueprint указан на платном `0.5c-512mb`, поскольку непрерывный worker на free-плане недоступен. Бесплатная PostgreSQL Render истекает через 30 дней и не имеет резервных копий. Перед расходами и beta-запуском тариф следует подтвердить вручную.

## Telegram

После успешных healthcheck и Pages deployment укажите в BotFather URL `https://s1lmn.github.io/project1/`. Проверяйте вход только после того, как `VITE_API_URL` ведёт на доступный HTTPS API и CORS содержит Pages origin.
