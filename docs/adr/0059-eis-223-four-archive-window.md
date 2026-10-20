# ADR-0059 — полный notice223 window до четырёх архивов

Статус: **ACCEPTED / DEPLOYED**, S176, 2026-10-04, 06:59 UTC.
Owner ADR: Astra; diagnostic/migration/deployment: root; source/index implementation: Sol. Production admission/deployment
подтверждены приведённым ниже evidence; полные source-set guards сохранены.

## Установленная причина

Window getDocsIP/RI223/77/2026-10-02+03:00/purchaseNotice давал
ARCHIVE_SET_MISMATCH до archive GET. Bounded initial/prepared capture:
4initial/4prepared,4uniqueUIDs, equalsets и requestbinding=true.
CaptureSHA:`75210e4ee522f86bb3c43ff1f6e3d880a4462fb1c4a2cf7387927b9057763077`.
Это доказанный count-only refusal, не нарушение UID/source binding.

Старое ограничение2 находится в binder, ReadyWindow archives/URLs и DB
ck_eis_223_counts. Ошибка смешивает count overflow с настоящим set mismatch;
новый контракт должен разделить диагностику, сохранив полную проверку связей.

## Диагностический бюджет

Полный набор того же request теперь сохранён: **4 ZIP, 24,527,171 compressed
bytes, 82,432,099 expanded bytes, 365 members, 0 duplicates**. Все четыре
архива проходят существующие per-archive guards. Исходная DB не изменена.
Это подтверждает пригодность выбранных численных caps для данного sample,
но само по себе не подтверждает production intake или расход памяти.

Proof: `research/223/local…/s176-20261004T063737Z/download-full.json`,
SHA-256 `15f2d670369b5181cd96d96c3646d607259d5de6ae08ba5b171f2aa64a745bf9`.
Связь с initial/prepared capture закреплена указанным выше capture SHA.

Первый bounded download прочитал4ZIP:24,527,171compressed bytes, меньше32MiB.
Уже3ZIP header totals69,221,572expanded bytes/300members превысили предложенный
aggregate64MiB; получен WINDOW_EXPANSION_LIMIT. Сохранены только первые2ZIP,
DB mutations0. Это не полный admitted set и не успешный window.

Root выбрал следующий явный bounded diagnostic budget на VPS2GiB worker:

| Bound | Значение |
|---|---:|
| Archives/window |4|
| Compressed/window |32MiB|
| Expanded/window |128MiB|
| XML members/window |400|
| Compressed/archive |16MiB|
| Expanded/archive |32MiB|
| Members/archive |200|
| XML/member |4MiB|

Aggregate expansion64→128MiB — отдельное обоснованное увеличение, не побочный
эффект count cap.400members сохраняет прежний aggregate ceiling, несмотря на
теоретические4×200. Превышение любого bound остаётся whole-window failure.

Для повторной диагностики допустимо использовать2cachedZIP +2missingGETs,
только связанные с тем же exact initial/prepared UID/URL set. Нельзя смешивать
новые source responses с прежним capture. Full header totals проверяются до
парсинга всех records; complete set и SHA manifest обязательны. No subset success.

## Принятый контракт реализации

Один общий notice-window budget используется binder/model/fetch/preflight/DB.
Source fetch проверяет cumulative compressed bytes после каждого GET и до
следующего. Все URLs/UID uniqueness/equalsets/docRequest binding проверяются
перед первым GET. Пер-архивные safeguards, version-conflict и token-reflection
guards прежние; события whole/lot cancellation сохраняют max2.

Explicit migration меняет только notice archive-count CHECK, с literal old/new
definitions. Downgrade отклоняется при>2archive history в любом tenant; RLS не
скрывает историю. Replay/ingest полного set атомарны; прежний FAILED journal
не переписывается. Новый успешный intake допустим только отдельным evidence.

Migration `20261004_01` не изменяет исторические migration definitions,
whole/lot event count CHECK или старые receipts. Проверка downgrade выполняется
до изменения constraint и видит все tenant rows; невозможность гарантировать
такую видимость означает отказ downgrade. При наличии истории с 3–4 архивами
никакие rows не удаляются, не сокращаются и не переобозначаются ради отката.
Upgrade/downgrade должны сохранять RLS и неизменяемость истории.

Отдельные причины resource refusal должны отличаться от реального UID/set
mismatch и оставаться локальными FAILED window attempts. Ни parser success,
ни превышение прежнего count cap не разрешают выбирать subset, обходить
проверку version conflicts или выдавать SYNCED до полного atomic commit.

## Admission gates

Exact full4ZIP proof получен. Root выполнил полный cached fetch → preflight →
isolated ingest → checkpoint → replay с resident Chromium в прежнем cgroup
2 GiB: 365 records / 365 new versions, 0 source calls, 7.220 s total.
Cgroup peak — 343,482,368 bytes (около 328 MiB), Python RSS — 193,003,520 bytes.
Это измерение полного offline пути на данном sample; оно не является fresh
online latency SLA или универсальной оценкой для всех возможных XML.
Полнота данного retained source set подтверждена, полнота ЕИС — UNKNOWN.

Memory proof: `/research/223/s176-memory-proof.json`, SHA-256
`5c646de291d44c5c3ccb5aec734a2dd2a540c42537ff7f19eebcfaaea7445096`.
Root сообщил 139 Linux PASS и 21 isolated PG PASS, включая empty-history
downgrade/upgrade roundtrip и отказ downgrade при wide history другого tenant.
Финальный regression gate, Ruff/mypy и production rollout подтверждены root.

Tests: valid4/mismatch4/duplicateUID; count5failbeforeGET; cumulative compressed
and expanded/member caps; late conflict rollback; tenant/replay/immutable raw;
fresh upgrade и downgrade history guard; unchangedeventcaps. Только после gates
полного retained sample и review возможен rollout. Whole coverage/freshness
и остальные unsupported223families остаются UNKNOWN.

## Bounded code review

Проверены shared limits, binder, fetch, header preflight, notice CHECK,
literal migration и PG acceptance tests. До XML parse проверяются headers всех
архивов; exact set проверяется до GET; duplicate/version conflicts и atomic
ingest сохранены. Оба event reader/binder и их DB constraints остаются max2.
Downgrade включает `SET LOCAL row_security = off` и global history guard
до изменения constraint. Optional failure SHA принимается только как 64 hex.

Исправлено и повторно проверено расхождение diagnostic allowlist runner: коды
`WINDOW_EXPANDED_LIMIT`, `WINDOW_MEMBER_LIMIT`, `ARCHIVE_RESOURCE_LIMIT`,
`ARCHIVE_INVALID` теперь присутствуют в allowlist и сохраняются в journal.
Root сообщил PASS regression для resource code / valid SHA и invalid secret
SHA. Isolated PG и full-pipeline memory gates подтверждены приведёнными выше
результатами. Дополнительных нарушений admission контракта при данном bounded
review не найдено; финальный regression gate пройден.

## Production evidence

Root подтвердил migration `20261003_05` → `20261004_01`, backup кода и
проверенный **schema-only dump** (это не backup существующих data rows).
Host 15 / API 5 проверенных hashes совпали; health 200, anonymous 401,
`no-store`, временные markers отсутствуют.

Exact retained набор 4 ZIP / 365 XML versions импортирован полностью:
365 new versions, window count 0 → 1, один новый SYNCED attempt. Прежние
8 FAILED attempts неизменны; replay дал 0 new versions, source calls 0.
Manifest SHA-256:
`30eaf9aa480eba3b4513ec5ce7bb31b6309dc9d793665f4dd8257915b3f3eec6`.
Admission proof `/research/223/s176-admit-proof.json`, SHA-256
`93440ab3f719c7ab6ae87654885721c34a6dc9fca6d555badd4921f19feba2c2`.

Проверенный planned scope имеет COMPLETE / old_gaps 0. Это не полнота ЕИС.
API sample: 2,876 current distinct purchase numbers / 2,979 versions;
paper 251.35 ms / 59 matches, server 607.15 ms / 184 matches. Эти измерения
не SLA. Proof `/research/regions/s176-final-api-20261004T065948Z.json`, SHA-256
`7d05cfc26681ec8c763b4cdb50ab5e67bca9651463c5a39c9d9ff3a493762a2c`.

Wide history теперь делает downgrade недопустимым по принятому guard;
его отказ проверен в isolated PG, на production downgrade не выполнялся.
Offline memory evidence сохраняет свой ограниченный смысл: около 328 MiB
с resident browser на данном cached sample, без обещания online SLA.

## Addendum 2026-10-08 — следующий bounded budget, не deployed

Позднее обновление77/05.10/purchaseNotice выросло со старых2 ZIP/190 XML
до5 ZIP/433 XML: count4 и aggregate400 теперь блокируют полноту обновления.
Новый локальный delta:8 ZIP/800 XML при прежних32MiB compressed/128MiB expanded
и неизменных per-archive caps. Миграция20261008_01 от actual installed08 меняет
только CHECK, guarded downgrade сохраняет историю>4 и fail closed visibility;
20261008_02 объединяет ветки без требования pending09–12 для этого hotfix.
В retained isolated production6 реально добавлены243 версии и проверен поиск;
production установка блокируется действующим installed-overlay quality guard.
Историческая приёмка четырёх архивов выше не переписана. Полный scope, ресурсы,
XSD FAIL/UNKNOWN, результаты и открытые пробелы —
[национальный охват](../eis/ingestion/120-eis-national-coverage.md).
