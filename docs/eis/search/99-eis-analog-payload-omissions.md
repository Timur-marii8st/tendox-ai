# S216 — частичная выдача аналогов при ограничении размера

Статус: завершено, 2026-10-06. Измеренный блокер: три ранее проверенных запроса
по бумаге стали завершаться ANALOG_NOTICE_PAYLOAD_LIMIT после очередной загрузки.

## Контракт

Сохраняются tenant, latest-version, source holds, lexical/date/type predicates,
порядок и выбор первых 20 ссылок с 21-й как sentinel. Пропуски не заполняются
карточками за пределами этой выборки. Целевая карточка сверх 256KiB отклоняется.
Размер каждого кандидата проверяется SQL octet_length сохранённого lot_items
JSONB до загрузки payload. Слишком большой кандидат или кандидат, не помещающийся
в оставшийся общий бюджет 2MiB, получает отдельную typed omission с точной
ссылкой/version/XML SHA, причиной, размером и применённым лимитом. Следующая
меньшая карточка может поместиться. Размер JSONB не выдаётся за размер XML.

Report policy eis-analog-retrieval-v2; интерфейс также читает старую v1 без
пропусков. Причины: CANDIDATE_NOTICE_PAYLOAD_LIMIT / CANDIDATE_TOTAL_PAYLOAD_LIMIT.
Omitted и рассмотренные карточки уникальны/не пересекаются по номеру закупки,
исключают target и вместе не превышают 20. Strict integer fields и bounds.
Omission не является EXCLUDED или FAIL. Количество позиций и сопоставимость
пропущенной карточки UNKNOWN. Ошибки целостности, SHA, повреждённых данных и
прав доступа продолжают отклонять запрос. Нет широкого catch-and-skip.

## Проверка и выпуск

Проверки: strict wire/byte boundaries, лимиты target, все20omitted плюс sentinel,
later-fit, SQL-параметры hydration, tenant/holds/SHA, реальные frozen-paper запросы,
Next Action/SSR с видимыми ссылками и причинами. Web-first dual compatibility,
затем два backend-модуля. Без миграций, новых зависимостей, увеличения ресурсов
и сетевых обращений к ЕИС при сравнении. Browser visual отдельно не подтверждён.

409 isolated PG/unit/API тестов PASS41.56s, zero skips; Ruff/mypy/Astra review PASS.
Node13characteristic/11analog/8protocol, TypeScript/ESLint/production build PASS.
SQL spy подтверждает отсутствие oversized и total-budget omissions и присутствие
later-fit admitted ref в параметрах hydration. PG log SHA256
`aa0a457306b05d741114c96538032d506ac55d208b0c1a8b958a01d0c6a3489e`;
web build SHA256 `26e5991451acd8e2d09c6acc848ef965b57258cff6163d373a863600cc640f54`.

Web-first05:50:29UTC atomic3/host122/web22; old backend compatibility проверена
на шести selected-pair SSR reads и пяти negatives. Все три аналоговых запроса
на oldAPI сохраняли известный BLOCKED; это не объявлялось PASS. Backend05:54:09UTC
atomic9/host124/API24/worker24 PASS. Выпуск дождался завершения штатной загрузки.
Source0 rollout, no schema/deps/cron/caps change.

## Реальные запросы после выпуска

Все три frozen-paper запроса успешно прочитаны first/repeat: HTTP1147–1297ms,
direct1134–1214ms; при фиксированном checked_at HTTP/direct отчёты идентичны.
Каждый отчёт:19admitted/1omitted/142positions, truncation true. SQL trace
подтверждает, что omitted payload не загружен. Пропущена exact карточка
0373100040126000766v1/XML SHA
`8cbebd2848d0b39c2b5c8a27fb8c02d02f6b8e313b17870beacf370869dc8751`:
263338bytes JSONB при лимите262144. Восемь API negatives PASS.
Next Action/compiled SSR три запроса1205–1312ms: явные omission refs/reason/UNKNOWN,
142 кнопки сравнения; шесть selected-pair reads141–187ms/пять negatives PASS.
Browser visual NOT_PERFORMED. Серверные private proofs:

- `s216-analog-live-proof.json`, SHA256 `a7b7938d7240cf2d870e7a044529a8d31017be3a1f33e167622770e7444545c5`.
- `s216-verified-characteristic-live-proof.json`, SHA256 `31fe9cb696bfe023d5b0c5e0059715605e7f47ce10bb72ffb36d187fc2892752`.
- `s216-web-final-proof.json` (state), SHA256 `cd848f54d363e37db9be5551c099fcf73dc5654039d7491ebed605c8d324e006`.
- `s216-final-operations-proof.json`, SHA256 `c65c89fe0f0a19e6aa6796a010bd9a2e57ad57afba970af43ca3fbe424f261a1`.

Ops05:54:49UTC: DB5508307991/free252010950656/head20261005_01/testDB0/health200/
markersfalse. Images:

- API `sha256:3e291b1e07c037df8be5e19329b3c0e1124db615e2b4abdc6170af6dfa84c2c1`.
- Worker `sha256:bf9a4f4de98c57c2c5d9ee680022dac71222bc348dc828ec9557655aec63c835`.
- Web `sha256:f6771932332eba99d46bc6ae3aab5a2e60ec4ee931e4556ab46c2846a67cf42f`.

Backups в `/home/syurai/vibe-seller-state/backups/`:

- `s216-before-20261006T055026Z-web.tar.gz`, SHA256 `00ff756df3d05bb54ef76c66117b78572f38acbb4a0d70c8e16f3323bb7da47a`.
- `s216-before-20261006T055404Z-code.tar.gz`, SHA256 `f563dd11d03d21e625b6c1d836e83cd45ea2297afcf51d4ce4ef3d14767b2219`.

Следующий этап: точный полный ТЗ/поставка review package; существующие snippets
и legacy blocks_total не доказывают полноту извлечения. Отдельно26oldparserfailures
ожидают штатного24h cooldown (S217 read-only proof), не новую retry lane.

Полнота ЕИС, полнота выборки, технический допуск, прибыль и участие UNKNOWN.
