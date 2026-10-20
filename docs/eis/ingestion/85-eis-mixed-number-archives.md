# S202 — смешанные адресные архивы ЕИС

Owner root. Статус: реализовано и установлено на VPS 2026-10-05.

## Изменение

Только `getDocsIP/PRIZ/by-number/<number>` разрешает metadata-only документы
`epClarificationDoc`, `epProtocolEOK2020FirstSections`,
`epProtocolEOK2020SecondSections`, `epProtocolEOK2020Final`, `fcsPlacementResult`,
`fcsProposalsResult`. Все ZIP и XML остаются исходными, ни один member не пропускается.
Неизвестная семья, другой номер, ошибочный namespace, дубли или неоднозначный набор
останавливают весь атомарный intake. Датированные окна сохраняют прежний allowlist.

Метаданные читаются по точным direct-child путям: EP commonInfo/purchaseNumber
для разъяснений/протоколов, OOS root purchaseNumber для placement,
EP root purchaseNumber для proposals. Идентичность — SHA исходного XML;
варианты одного документа не перезаписываются. Result version0 не превращается
в notice version1. Публикация — только docPublishDTInEIS/publishDTInEIS,
не createDate. Отсутствующая/неaware дата остаётся UNKNOWN.

Официальная схема: [пакет ЕИС16.3,44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
ZIP SHA `4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`;
fcsExport.xsd SHA `b0ff5149d8bdb7c64179600e391ddb3221a8540122f7cf937a0bf60db651f151`.
Схема подтверждает семейства и поля; она не является доказательством актуальности
закупки и не задаёт бизнес-вердикт участия. Все 16 XML трёх сохранённых наборов
прошли полную offline-проверку по `fcsExport.xsd`; извлечены 3 извещения и
13 дополнительных документов. SHA каждого XSD сверены с официальным пакетом;
external entities и сетевое разрешение схем отключены.

Proof: `/var/lib/eis-browser/research/rejected/s202-official-xsd-proof.json`;
SHA `6d1abd0e87ce3043000bf561a4838f3e1cc7ed112bf98dad3ff7475d9b0f83f8`.
Эта проверка: source requests 0, database writes 0.

## Persistence и статус

Используется существующий tenant-scoped immutable `eis_procedure_events` с
parser_version `eis-companion-document-v1`, FK на полный сохранённый архив.
Migration20261005_01 связывает family/parser/SHA identity/recovery_stageNULL.
Cancellation остаются `eis-procedure-event-v1` с прежними правилами. Metadata-only
документы не участвуют в выборе последней отмены и не маскируют cancellationFAIL.
Их содержательный юридический/ценовой результат ещё UNKNOWN. DeadlineFAIL сохраняется;
метаданные не дают active-stage PASS, probability, market price или PARTICIPATE.

Адресная загрузка через существующий API получила поддержку этих семейств.
Preview/replay operator ограничен тремя неизменёнными наборами S201: input SHA,
tenant audit, manifest/SHA всех ZIP проверяются до canonical mutation. Повторный
intake использует прежние atomic/idempotent source contracts, notice+lexical refs
сверяются точно. Закупки с истёкшим latest deadline не запускают скачивание документов.
Для допустимого latest ref сохраняются прежние hold/queue checks.

```bash
bash scripts/server-eis-mixed-number-replay.sh          # preview/source0
bash scripts/server-eis-mixed-number-replay.sh --apply  # replay/source0
```

Wrapper использует priority/import leases и owned UUID cleanup изS201,
worker2CPU/2GiB. Проверка capacityDB<100GiB/free>=40GiB перед каждым apply;
SQL20s/lock2s. Полный replay3 sets; report<=1MiB0600. Не добавляется recurring lane
или source budget. Миграция forward; downgrade при наличии companion rows
отклоняется старым CHECK без удаления evidence. FullEIS coverage UNKNOWN.

## Проверка

2026-10-05 15:30:30 UTC: 95 Linux/isolated PostgreSQL тестов прошли.
Проверены ограничения схемы и tenant isolation, повторный intake, атомарный отказ
при чужом номере/namespace/неизвестном XML, exact lexical/document refs,
сохранение cancellation FAIL при более поздних metadata. Допустимый synthetic
notice создаёт задание именно для своей версии/SHA; реальные истёкшие закупки
должны остаться без новых заданий. Ruff, mypy для четырёх изменённых модулей
и bash syntax прошли. Временная тестовая БД удалена.

## Реальный результат на VPS

Deployment 15:46:33 UTC: forward HEAD `20261005_01`, atomic 14 файлов,
host 59/API 13/worker 13 SHA checks PASS. Dispatch leases получены последовательно
после штатного завершения corpus/223 циклов. Backup SHA
`d0b6ef2b1c20a8a39d8d3a4c48399c3af0671681470320285b0489bb67ea5b67`.
API image `sha256:6d18602ed058580f70b2abeb64f7eeee459016c7448c9711d462431c5e6e6562`;
worker `sha256:78bba392bc932933b2fa519f4800560aabcb2617a67ea959d7f36a0b07765cd0`.
Web image и cron прежние; лимиты памяти/CPU и source budgets прежние.

Preview 15:46:43.567525 UTC: source0, canonical writes0.
Proof `/var/lib/eis-browser/research/rejected/s202-mixed-replay-0acce6e6-0651-416a-a5ac-ebebdf3c4ade.json`;
SHA `6ff10acfdebf63543a3067c9d83f79548caa8fda67ae311b7d0226a9ea0ca2b2`.
Apply 15:46:59.964701 UTC: source0, **3 новые версии извещений + 13 companion rows**,
3 exact lexical refs и 3 tenant audit events. Полные исходные ZIP 158156 bytes
сохранены в canonical archive store; исходные retained evidence не удалены.

| Номер | Извещения | Дополнительные XML | Новые document jobs |
| --- | ---: | ---: | ---: |
| 0373100075926000096 | 1 | 6 | 0 |
| 0373100075926000095 | 1 | 4 | 0 |
| 0573500000526000095 | 1 | 3 | 0 |

У всех latest deadline истёк: application FAIL, queue BLOCKED/DEADLINE_EXPIRED.
Эти исторические закупки не являются рекомендациями для участия. Apply proof:
`/var/lib/eis-browser/research/rejected/s202-mixed-replay-50f0dd66-4e8f-41a0-8d25-763c48aad730.json`;
SHA `ac26cccd7c022a0407f7b94c3e74d117ed88088546ac9a7a9fda1bd29d71bb81`.

Read-only verification 15:48:51 UTC сверила исходные ZIP bytes, все 13 XML identities,
source-member/parser/FK bindings, prepared response/source URL и три intake audit.
Три извещения совпадают с запросами по собственному названию в штатном comparison
resolver и имеют FAIL с XML evidence. Это проверка ровно восстановленной тройки,
не поиск по всей ЕИС. Пробный запрос «бумага» на этой тройке дал 0 совпадений:
это услуги/работы из технического national/all-stage cohort S201, а не бумага.
Proof `/var/lib/eis-browser/research/rejected/s202-persisted-verification.json`;
SHA `a539c9b5b5be85530efbc834b6e462d7313b420ecdf74bb451d0c3480d872441`.

Ops 15:48:52 UTC: health200, HEAD01, test databases0, оба markers false,
DB4613258263/free258075906048 bytes. Proof
`/var/lib/eis-browser/research/rejected/s202-operations-proof.json`;
SHA `d037222cd9bd0141676132ea2312a481cc5262c1cc7784095f51452ab4beb896`.
Full coverage, source freshness, протокольные цены/участники и participation UNKNOWN.

Final documentation seal 15:50:51 UTC: atomic6 docs, host59/API13/worker13
hash checks PASS, установленные API/worker image IDs совпали, web/cron прежние.
API/web running, OOM false, memory1GiB/768MiB. Seal backup SHA
`acc00165933db16665637286bbe72d7bdcc418d1216d7429f6e5c7eb9dc37725`.

Следующий S203: извлечь содержательные факты из сохранённых протоколов по официальной
XSD с отдельным typed/evidence contract. Начать source0, явно различать этап,
число заявок, цену предложения и результат; не выводить прибыль из НМЦК и не
использовать исторический протокол как подтверждение свежей активной закупки.
