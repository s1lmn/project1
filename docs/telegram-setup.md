# Настройка Telegram

1. В BotFather откройте `/mybots`, выберите бота и задайте username/описание.
2. В `Bot Settings → Configure Mini App → Enable Mini App` укажите публичный HTTPS URL frontend.
3. Настройте menu button для открытия Mini App и разрешите сообщения пользователю.
4. На backend задайте `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBAPP_URL`; на frontend — только публичный `VITE_BOT_USERNAME`.
5. После теста на staging включите `TELEGRAM_NOTIFICATIONS_ENABLED=true`. По умолчанию worker пишет dev-сообщения в журнал и не обращается к Telegram.
6. Укажите точные HTTPS origins в `ALLOWED_ORIGINS`; не используйте `*` в production.
7. Выполните миграции, запустите API и worker, затем откройте Mini App из личного чата с ботом.

Backend принимает только исходную строку `Telegram.WebApp.initData`, проверяет HMAC и свежесть `auth_date`. `initDataUnsafe` не используется как доказательство личности. Алгоритм соответствует [официальной документации Telegram Mini Apps](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

Проверка внутри Telegram: первый и повторный вход, истёкший initData, светлая/тёмная тема, safe area, сообщение нового отклика, accept/reject, напоминание, deep link, контакт с username и `tg://user?id=…` без username. Последний вариант зависит от privacy settings Telegram и должен быть проверен на реальных клиентах.

Никогда не коммитьте `.env`. Если токен попадал в чат, лог или историю Git, перевыпустите его через BotFather и обновите secret storage окружения.
