# Самостоятельный профиль: checkpoint реализации

Статус: локальный UI/API/real PostgreSQL путь завершён, 2026-10-15. Владелец: root.
Worktree: `C:/Users/elkgo/.codex/worktrees/company-profile/vibe-seller`.
Ветка: `codex/company-profile`; baseline snapshot `5e842eb5bffffe8b47c3da566457d7b711585d9a`.
Принятый [контракт](07-company-profile-contract.md) сохранён в baseline;
исходный index/рабочее дерево не изменены. Snapshot содержит накопленные локальные
изменения других задач; это основа изоляции, не release этих изменений.

Уточнение на 2026-10-23: строки ниже о недоступной роли владельца и
заблокированных critical settings описывают установленный старый baseline
2026-10-15. Локальное расширение `COMPANY_PROFILE_OWNER` проверяется отдельно;
см. [ADR0115](../adr/0115-company-profile-owner-confirmation.md) и
[операционный remediation-отчёт](../operations/125-spec-remediation.md). Это
не означает, что расширение установлено в production.

Результат: форма → самостоятельная immutable версия → reload → edit/diff →
следующая версия → история → сохранённый exact выбор для будущего сравнения.
Алгоритм сравнения/ранжирования, production и загрузчики ЕИС вне задачи.
Фактический [API/DTO/права/ошибки/examples/handoff](09-company-profile-api.md).

Owned files: `domain/company_profile_snapshot.py`, `storage/company_profile*.py`,
`api/company_profile.py`, миграция `20261014_01_company_profile.py`,
`tests/test_company_profile_snapshot.py`, `tests/integration/test_company_profile_pg.py`,
`web/src/app/company-profile/`, `web/src/lib/company-profile*.ts`, тематические
web tests/config, синтетические fixtures профиля. Общий wiring только в
`migrations/env.py`, `api/app.py`, `api/runtime.py`; документация 07/08/09,
архитектурный индекс и одна строка live-плана. Другие owned files не меняются.

Уточнение пользователя: доверенной роли владельца нет. OPERATOR записывает
реквизиты/описание/поисковую географию как manual declaration, AUDITOR читает;
finance/platforms/methods/subcontracting/prohibitions заблокированы сервером.
Никакая существующая роль не выдаётся за OWNER, критическая политика не применяется.
География — заявленный интерес поиска, не доказательство исполнимости логистики.
В первом срезе источники — серверные записи ручного ввода; document-source UI
не добавляется. Вместо сравнения реализуется immutable выбор exact версии.

Acceptance: UI/API/real PG подтверждают неполное сохранение, reload, diff/edit,
старую версию, exact выбор, retry/concurrent conflict, tenant/RLS, UNKNOWN,
Decimal/source и неизменность existing cases/hash. Browser visual обязателен,
либо точная причина недоступности. Общие release checks перед итоговым коммитом.

## Где открыть и продолжить

UI: `http://127.0.0.1:3137/company-profile`, API: `http://127.0.0.1:8137`.
Запущены Next production build (Webpack) и Uvicorn, только loopback.
PostgreSQL16.15: WSL Ubuntu-24.04, cluster16/company-profile, localhost55437,
DB procurement_profile_test, owner/runtime роли; runtime без BYPASSRLS.
Миграция head20261014_01 применена только к этой изолированной БД.

Локальные параметры — ignored `.env.profile.local`, `web/.env.local`;
OPERATOR/foreign/AUDITOR synthetic credentials — ignored
`tmp/profile-local-credentials.json`. Вкладка оставлена с личным OPERATOR-доступом,
проверенным настоящим PostgresAuthenticator; сессия на час. Это не production IAM.
Повторный запуск: worktree — `uv run --env-file .env.profile.local uvicorn
--factory procurement.api.runtime:create_runtime_app --host 127.0.0.1 --port 8137`;
web — `npx next start --hostname 127.0.0.1 --port 3137`.
Сборка `npx next build --webpack`: Turbopack отказался работать с junction
node_modules за пределами worktree. Исходные node_modules не удалялись.
Docker API недоступен; использован штатный WSL/PostgreSQL/Alembic путь.

## Evidence и ограничения

Browser: неполный v1 → reload → diff → v2; второй tab получил409 и сохранил
правку; v1 открыт неизменным и выбран, выбор пережил reload/server restart.
Downloaded handoff JSON совпал с exact v1 API/PG. UNKNOWN/false/[]/Decimal
расстояния и источники сохранены, old case/profile/input_digest неизменны.
AUDITOR проверен в UI: поля отключены, save/select отсутствуют.
Исправлены текст после save и native form reset после отказа422;
повторная browser проверка сохранила select=false и checkbox=true.
Визуальное proof — ignored `tmp/profile-selected-version.png`.

13 DTO/examples PASS; 19 real PG/HTTP/environment PASS без skips
(`tmp/profile-real-pg-final.xml`); отдельный existing case roundtrip PASS;
157 Node wire/render PASS; TS/ESLint/production build PASS;
Ruff/mypy22modules/9doctests PASS. Общий pytest —
`tmp/company-profile-python-final.log`/JUnit XML: 3236 PASS, 650 explicit skips,
0 failures/errors; 3886 collected. Scoped real PG19 отдельно PASS без skips.
Пропуски общего набора не являются evidence PG/OCR: scoped real PG и browser
проверены отдельно. Docker/container provider gate не выполнялся.

Windows checkout изменил EOL в source pins и PDF offsets, вызвав четыре отказа.
Git restore пересмотрен после двух неудач: восстановлены exact bytes с SHA и
normalized-baseline guards. Исходный mixed EOL models.py сохранён; registry
профиля вынесен в свой модуль. EIS implementation/pins не менялись.
Исходная dev .venv восстановлена с прежними optional-пакетами/editable root;
API/проверки профиля используют отдельную .venv worktree.

Блокер production: доверенная owner-авторизация для critical policy.
Для выпуска: review/integration ветки, штатный release gate, HTTPS/персональные
credentials и согласованная миграция/backup. Production onboarding и hard-policy
changes не подтверждены локальным стендом. Сравнение/ранжирование не реализовано.
Следующее действие: интегрировать этот bounded slice после review; агент
сравнения получает контракт09 и exact selection/profile_ref, алгоритм не написан.
