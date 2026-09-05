# Аналитика

Сервер сам пишет бизнес-события: `onboarding_completed`, `profile_updated`, `activity_created`, `activity_cancelled`, `response_sent`, `response_accepted`, `response_rejected`, `telegram_contact_clicked`, `meeting_result_confirmed`, `activity_completed`, `rating_submitted`, `report_submitted`, `user_blocked`.

Клиент может отправить только белый список UI-событий: `app_opened`, `onboarding_started`, `feed_viewed`, `activity_viewed`, `filter_applied`, `activity_create_started`. Серверные бизнес-события через client endpoint отклоняются. Свойства фильтруются; тексты отзывов/жалоб, контакты и секреты не сохраняются.

`GET /internal/metrics` закрыт `X-Internal-Key`, принимает `period_start` и `period_end` и возвращает числители. В production dev-пользователи исключаются.

## Определения MVP

- Registrations — новые уникальные реальные пользователи периода.
- Onboarding completion — завершившие профиль из регистрационной когорты.
- Activation — уникальные пользователи, создавшие активность или отклик.
- Activities with response — активности периода хотя бы с одним уникальным откликом.
- Acceptance rate — когда-либо вручную принятые отклики / все отклики.
- Completion rate — технически completed / активности с прошедшим стартом.
- Successful Matches / Week — уникальная активность недели старта с accepted-участником и хотя бы одним положительным подтверждением после старта.
- Отсутствие подтверждения — неизвестно, не no-show. Противоречивые ответы анализируются отдельно.
- Retention D1/D7/D30 — регистрационная когорта с `app_opened` в соответствующий календарный день; незрелые когорты не входят.
- No-show rate — уникальные активности с жалобой `no_show` / прошедшие активности с accepted; это сигнал жалоб, не доказанный факт.

Endpoint возвращает числители и знаменатели, доли воронки, медиану первого отклика, D1/D7/D30 retention, активности по локальным календарным дням и Successful Matches / Week. Экран поддерживает срезы по спорту, району, уровню и источнику. При нулевом знаменателе API возвращает `null`, а UI показывает «Недостаточно данных».
