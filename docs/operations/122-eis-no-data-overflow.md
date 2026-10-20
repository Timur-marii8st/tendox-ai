# Восстановление bounded NO_DATA retention

Владелец root. Статус: READY_PENDING_EXACT_APPROVAL; активация NOT_PERFORMED.
Контракт: [ADR0110](../adr/0110-bounded-no-data-overflow.md), исходная причина —
[диагностика19Oct](121-eis-production-readiness.md).
Owned files: `src/procurement/sources/eis_no_data_evidence.py`,
`scripts/server-eis-no-data-store-report.py`, соответствующие два test modules,
этот документ, ADR и индексы/live-план. Работа одним агентом.

## Acceptance

- На изолированной копии полного рабочего store новый ответ сохраняется во втором
  сегменте; source/database production writes0. Данные fixture обозначены synthetic.
- Первый файл сохраняет hash, старые ссылки raw/manifest и replay работают;
  новый receipt проходит audit/journal/offline verification.
- После перехода первый файл больше не получает записи; оба файла сохраняют
  per-store лимиты, после заполнения второго — явный QUOTA_REACHED.
- Concurrent writers не создают дубли; busy/unsafe/IO не становятся RETAINED.
- Report показывает headroom второго файла и оба независимых snapshots.
- Полный обязательный release gate без ослабления stages/skips; installed runtime
  сохраняет все прочие файлы и настройки, схема и cron не меняются.
- Активация требует exact payload и audit; после неё нужен обычный cron с
  RETAINED/raw reparse/journal match. До этого live recovery не объявляется.

## Порядок выпуска

За основу берётся sealed source установленного speed-v2, а не всё текущее
рабочее дерево. В него добавляются только owned изменения. Provider и policy
находятся вне candidate; меняются лишь ожидаемые коллекции добавленных тестов.
Все прежние stages, assertions и allowed skips сохраняются.
Перед сборками проверяются память и свободный диск; штатные loaders продолжают
работу. Нельзя освобождать место удалением чужих данных или release evidence.

План активации должен связывать source/receipt/images/host scripts SHA,
ожидаемую исходную конфигурацию и хеш старой SQLite, проверку восстановления
старых references и postcheck. API/worker/reader должны понимать оба receipt paths.
Обратное переключение на reader, не знающий overflow, не считается безопасным
rollback после появления новых receipts. Данные не удаляются при rollback.

## Текущие проверки

Регрессии воспроизвели исходный отказ: второй ответ при заполненном store получал
FAILED. Добавлены проверки перехода, старых references, двух квот, sticky routing,
конкуренции, bounded lock и независимого quota report. Итог v2 приведён ниже.

Первый полный gate50/50 и actual-copy proof PASS сохранены, но payloadv1
не принимается к активации: финальный review воспроизвёл запись в свободные
ячейки уже полностью allocated файла. Добавлен отдельный regression и явный
page-count gate до INSERT. Scope и требование неизменного первого файла не
ослаблены; новый sourcev2 проходит полный mandatory gate заново.

## Итог v2 — 2026-10-19

Полный source-bound gate50/50PASS: unit3665PASS/27прежних explicit skips,
PostgreSQL16 —688PASS/0skips, Node178PASS/0skips,9doctests; Ruff/mypy,
docs, сборки и API/web smoke PASS. Cleanup9owned resources PASS; два accepted
images оставлены для выпуска. Все235Python modules итогового API image
проверены по source manifest. Изменены2модуля API: retention и ранее принятый
worker transport; defaultAPIgap2/worker configuration1.25 не меняются.

Изолированная копия реального store:57976records/128MiB. Старый файл сохранил
SHA256 после перехода; synthetic новый ответ сохранён в overflow20KiB,
old raw references3/3, replay и foreign-tenant refusal PASS. Production/source
requests0. Новый настоящий ответ ЕИС должен быть проверен после активации.

Receipt: `tmp/eis-no-data-segments-20261019-v1/release-receipt-v2.json`;
SHA256 `271a10e8a63aa5a16f6e462ad41fb8bd63e34bcd3bc4a254080dfdf8138bb3a6`.
Source68c64fd0…; image935dae45…; policy/verifier и все staged bytes связаны
с `activation-plan-v2.json` в том же каталоге. SHA256 точной операции:
`aca2b9b8edd68b2d8455ce125d9e7aca31007e40fd3c14dcaa31b97afdccb30d`.
Preflight этого payload PASS, source requests0/production writes0.

Операция обновляет API/worker image, host retention module/report и active
Compose override. Нужен короткий restartAPI; web/DB/schema/cron/source budgets
сохраняются. После неё ordinary cron должен дать RETAINED и raw/journal match;
без этого live recovery не объявляется. Нельзя применять superseded payloadv1.

Следующее действие — exact-payload approval пользователя по AGENTS, затем
установка и postcheck. Коммерческий API/full coverage этим срезом не приняты.
Этот итоговый evidence текст добавлен после sealing sourcev2 и не является
частью receipt-bound source archive; сами proof/plan hashes проверены отдельно.
