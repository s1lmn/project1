# Эксплуатация

## Release

Staging: CI выполняет lint/test/build; после merge в `main` владелец инфраструктуры применяет `alembic upgrade head`, разворачивает API/worker/web и проверяет `/health`. Production — отдельное ручное подтверждение и тот же порядок. Автоматический deploy не включён без выбранной площадки и credentials.

## Backup и восстановление

Ежедневно делать шифрованный `pg_dump --format=custom`. Не реже раза в месяц восстанавливать копию в изолированную БД через `pg_restore`, запускать `/health` и проверять количество пользователей/активностей. Сроки хранения и доступ к backup должны быть утверждены до alpha.

Перед миграцией: backup, проверка обратной совместимости, затем migration → API/worker → web. Rollback приложения допустим только пока предыдущая версия совместима со схемой; destructive migrations выполнять в несколько релизов (expand/migrate/contract).

Мониторинг: `/health`, 5xx rate, latency, подключение БД, количество `pending`/`failed` notification jobs, oldest pending age, ошибки worker и Sentry. Тела запросов и секреты не отправляются в диагностику.
