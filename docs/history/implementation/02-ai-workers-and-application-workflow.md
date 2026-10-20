> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

## S48 — server-managed first-chunk worker и local pilot KEK (2026-09-17)

S48 реализует ограниченный vertical slice поверх S47: worker принимает только
свежий server-revalidated claim и approval, повторно сверяет exact request/chunk
bytes, проверяет срок approval по database clock и делает ровно одну попытку
первого chunk. До сети durable claim уже записан; результат транспорта атомарно
сохраняется через raw-capture sink. Redirect, incomplete, oversized и unknown
ответы не получают raw blob, а crash/timeout не превращаются в retry.

Добавлен `LocalPilotDerivedTenantKekProvider`: это только тестовый/local-pilot
адаптер HKDF-SHA256 + AES-GCM, не production KMS и не замена ротации ключей.
Он включается только при наличии `AI_TRANSFER_RAW_ROOT_KEK_B64` и
`AI_TRANSFER_RAW_KEK_ID`. CLI `dispatch-approved-ai-transfer` дополнительно
требует `AI_TRANSFER_LOCAL_PILOT_ENABLED=1`; по умолчанию dispatch выключен.
Старый `analyze-tz-ai` отключён и не читает документы/не вызывает сеть.

Полный provider response хранится отдельно в зашифрованном raw blob ровно 720
UTC-часов; metadata/digests остаются discoverable через execution detail, а
точечное чтение raw разрешено только reviewer/auditor и аудируется. После purge
удаляются ciphertext и wrapped DEK, но сохраняются metadata, digests, review и
deletion receipt.

Историческая evidence предыдущего среза: S47 — 705 no-DB тестов и 67 тестов на
чистой PostgreSQL 16. Итоговый gate зафиксирован в S49 ниже. Production остаётся
заблокирован до managed KMS с rotation и проверяемых backup/WAL/restore retention
evidence; local pilot эти prerequisites не закрывает.

## S49 — materialization captured AI response в очередь требований (2026-09-17)

Срез завершён. После уже зафиксированного единственного `SUCCESS` capture для
одного chunk сервер без нового сетевого вызова валидирует provider response и
атомарно создаёт raw-free persisted run v2 (`persisted-ai-requirement-run-v2`)
и append-only materialization receipt в миграции `20260917_08`. В persisted
результат попадают только typed candidates, digests, provenance и ссылки на
request/claim/receipt/raw metadata; `response_content` и ciphertext туда не
копируются. Полнота результата остаётся `UNKNOWN`.

Многоchunk capture и semantic/candidate evidence, не прошедшие строгую проверку,
фиксируются как terminal `REJECTED` и не превращаются в очередь требований.
Повторная материализация идемпотентна, не делает network retry и допускает
recovery только для owning operator через `POST
/v1/ai-transfer-executions/{execution_id}/requirement-materializations`;
CLI recovery также выключен по умолчанию. Reviewer queue принимает как legacy
v1, так и новый v2 snapshot, но не раскрывает raw provider response.

Evidence среза: targeted набор `146 + 17` тестов и recent `134` теста; полный
no-DB набор собрал `843` теста (`760 passed`, `83 PostgreSQL/integration skipped`),
а обязательная fresh PostgreSQL 16 selection прошла `82 passed`. Doctest: `10 passed`;
mypy по 55 source-файлам, Ruff, `uv lock --check`, Alembic head `20260917_08` и
offline SQL прошли. Astra final review: `APPROVED`. Global Ruff format check не
заявляется пройденным из-за pre-existing drift в 40 несвязанных файлах; формат
изменённых S49-файлов проверен. Production остаётся заблокирован до внешних
доказательств managed KMS с rotation и backup/WAL/restore retention; multi-chunk
пока намеренно не поддержан и production-ready не является.

## S50 — pure-domain contract полного multi-chunk aggregate (2026-09-17)

Завершён preparation-only срез без сети, SQL и изменения production-флагов.
`AiTransferRequirementResult` теперь способен строго материализовать любой
ordinal уже успешно captured chunk: claim/receipt/raw metadata сверяются с exact
chunk request digest и только с принадлежащими этому chunk source blocks. Это не
разрешает второй dispatch: действующие repository/migration/worker gates S48–S49
по-прежнему ограничены первым chunk.

Новый immutable `ai-transfer-requirement-batch-v1` создаётся только из полного
ordered contiguous набора chunk-results одного tenant/transfer/execution и exact
request digest. Он запрещает пропуск, перестановку, повтор claim/receipt/raw
evidence, смешение source identity и backdated aggregation; aggregate candidates
и unresolved coverage заново детерминированно выводятся из chunk-results.
Модель raw-free и сохраняет `completeness_status=UNKNOWN`: provider success и
полное техническое покрытие chunks не являются human completeness review.

Evidence среза: focused contract/execution/review/worker suite — `60 passed`;
полный no-DB gate — `762 passed`; doctest — `10 passed`; Ruff, scoped format,
mypy по 55 source-файлам, `uv lock --check` и Alembic single head
`20260917_08` прошли. Следующий срез должен отдельно спроектировать persisted
per-chunk materialization/aggregate receipt, SQL chronology/RLS, worker recovery
и reviewer snapshot v3. До этого multi-chunk execution и production остаются
запрещены.

## S51 — durable ordered next-chunk claim без network enablement (2026-09-17)

Завершён persistence-only срез. Миграция `20260917_09` снимает историческое
ограничение `ordinal = 1`, но новый SQL guard разрешает только следующий
contiguous ordinal в пределах approved `chunk_count`. Все предыдущие claims
обязаны иметь exact terminal `SUCCESS/VALIDATED_RESPONSE`, complete capture и
связанную encrypted raw metadata; missing receipt, `FAILED`, `DELIVERY_UNKNOWN`,
пропуск ordinal, истёкший approval и конкурентный повтор блокируются до вставки.

Внутренний `claim_next_ai_transfer_dispatch` commit-ит permanent claim под
transaction advisory lock и не выполняет сеть. Конкурентный запуск даёт ровно
одного победителя. Loader повторно строит всю ordered claim/receipt history через
доменный контракт, а существующий execution detail показывает только последний
claim/receipt. API-модель дополнительно запрещает смешивать последний claim с raw
metadata предыдущего chunk; raw возвращается только при exact terminal receipt
текущего claim.

Live worker/CLI/API route намеренно не подключены к `claim_next`: второй HTTP-call
и автоматический batch-loop остаются выключены. Materialization persistence и
reviewer snapshot также пока single-chunk.

Evidence среза: полный no-DB gate — `762 passed`; fresh PostgreSQL 16 с миграциями
с нуля, RLS, concurrency и stop conditions — `84 passed`; doctest — `10 passed`;
Ruff, scoped format, mypy по 55 source-файлам, `uv lock --check`, Alembic single
head `20260917_09` и offline SQL прошли.

## S52 — one-attempt worker для следующего chunk (2026-09-17)

Завершён внутренний worker-срез без public API, CLI и автоматического batch-loop.
`NextChunkAiTransferWorker` в одном invocation сначала вызывает durable
`claim_next_ai_transfer_dispatch`, повторно получает server-validated exact
request, затем делает не более одного HTTP-вызова через тот же capture/receipt
контур, что и первый chunk. Worker дополнительно отклоняет ordinal 1; first-chunk
worker симметрично отклоняет любой другой ordinal.

Успешный следующий chunk не переиспользует single-chunk materialization S49 и не
выдаёт частичный результат за готовый reviewer run. Его безопасный outcome имеет
`requirement_batch_pending=true`, raw capture остаётся encrypted, а все поля
materialization отсутствуют. Любой `FAILED`, `DELIVERY_UNKNOWN`, незавершённый
claim или конфликт следующего claim оставляет pending false и не допускает
следующий ordinal через SQL-инварианты S51. Повторной сетевой попытки для уже
permanently claimed chunk нет.

Integration acceptance проверяет настоящую границу PostgreSQL: claim ordinal 2
виден в отдельной транзакции до входа mock transport, сеть вызывается ровно один
раз, terminal receipt/raw metadata сохраняются и execution detail указывает на
тот же claim/receipt. Миграция `20260917_10` снимает только прежний raw ordinal-1
check; уникальность `(tenant, execution, ordinal)` и exact receipt FK сохраняются.
Persistent per-chunk results, batch aggregate receipt,
reviewer snapshot v3 и orchestration всего batch остаются следующим отдельным
срезом; production flags не изменены.

Evidence среза: focused worker/execution/transport/result suite — `77 passed`;
полный no-DB gate — `765 passed`; fresh PostgreSQL 16 с миграциями с нуля, RLS,
commit-before-network и raw capture ordinal 2 — `85 passed`; doctest —
`10 passed`. Ruff, scoped format, mypy по 55 source-файлам, `uv lock --check`,
Alembic single head `20260917_10`, offline SQL и `git diff --check` прошли.
Production остаётся заблокирован до managed KMS/rotation, доказанного
backup/WAL/restore retention и persisted multi-chunk aggregate/review boundary.

## S53 — persisted per-chunk results и complete batch reviewer run (2026-09-17)

Завершён persistence-only срез без нового network orchestration, public API или
CLI. Миграция `20260917_11` добавляет две tenant-scoped immutable таблицы:
raw-free result каждого exact captured chunk и единственный полный batch result
для `(tenant, execution, parser_version)`. Per-chunk result связан составными FK
с claim, successful receipt и raw metadata; SQL trigger дополнительно сверяет
request/response/provider/source digests, exact `source_block_ids`, chronology и
неистёкший encrypted raw retention.

`materialize_ai_transfer_requirement_batch` работает без сети под transaction
advisory lock. Уже сохранённые chunks используются повторно; новый raw временно
расшифровывается только для строгого parser/builder и в persisted result не
попадает. Пока результатов меньше approved `chunk_count`, метод возвращает
ordered results и `record=None`: partial batch не становится reviewer-visible.
После последнего exact результата полный `ai-transfer-requirement-batch-v1` и
`persisted-ai-requirement-run-v3` создаются атомарно. Snapshot остаётся
`completeness_status=UNKNOWN`, а существующий независимый reviewer workflow
требует решение по всем aggregate candidates.

Deferred SQL trigger запрещает orphan v3 run, batch trigger требует точного
`jsonb_agg` всех ordered chunk results, а RLS и immutable triggers закрывают
cross-tenant чтение, update и delete. Recovery-вызов после commit возвращает тот
же batch/run и не расшифровывает raw повторно. Невалидный semantic result
fail-closed не создаёт chunk result или aggregate; отдельный durable rejection
receipt для multi-chunk остаётся будущим срезом.

Evidence: полный no-DB gate — `765 passed`; fresh PostgreSQL 16 с миграциями с
нуля, per-chunk recovery, complete aggregate, replay, RLS и immutability —
`86 passed`; doctest — `10 passed`. Ruff, scoped format, mypy по 55 source-файлам,
`uv lock --check`, Alembic single head `20260917_11`, offline SQL и
`git diff --check` прошли. Production flags не изменены; automatic batch-loop,
recovery API/CLI, managed KMS/rotation и backup/WAL/restore evidence всё ещё
обязательны до production.

## S54 — durable semantic rejection и no-network batch recovery API (2026-09-17)

Завершён fail-closed recovery-срез без нового dispatch route, batch-loop или
изменения production-флагов. Миграция `20260917_12` добавляет tenant-scoped
immutable receipt `ai-transfer-requirement-chunk-rejection-v1` для successful
captured chunk, чей wire result не прошёл строгую semantic/evidence validation.
Receipt содержит только exact request/claim/receipt/raw digests, ordinal,
parser version, actor/time и reason `INVALID_CANDIDATE_EVIDENCE`; provider text,
ciphertext и ключи в него не входят.

`materialize_ai_transfer_requirement_batch` теперь различает terminal semantic
rejection и повреждение durable evidence. Только `INVALID_WIRE_RESPONSE`
фиксируется как rejection; invalid ciphertext, binding, source или provider
envelope остаются integrity error. Сохранённый rejection идемпотентно
возвращается без повторного decrypt, не переписывает успешный transport receipt,
запрещает chunk result/aggregate для того же parser version и блокирует claims
следующих ordinal на SQL-границе.

Owning operator получил отдельный no-network recovery endpoint `POST
/v1/ai-transfer-executions/{execution_id}/requirement-batch-materializations`.
Он возвращает только `PENDING | MATERIALIZED | REJECTED`, materialized ordinals,
run digests либо typed rejection. Approver, reviewer, auditor, другой operator и
чужой tenant не получают доступ. Endpoint не claim-ит следующий chunk и не
делает provider call; single-chunk execution остаётся на S49 boundary.

Evidence: полный no-DB gate — `765 passed`; fresh PostgreSQL 16 с миграциями с
нуля, terminal rejection, replay, stop-before-next-claim, RLS и immutability —
`87 passed`; doctest — `10 passed`. Ruff, scoped format, mypy по 55 source-файлам,
`uv lock --check`, Alembic single head `20260917_12`, offline SQL и
`git diff --check` прошли. Production по-прежнему заблокирован до managed
KMS/rotation и доказанного backup/WAL/restore retention; автоматический
multi-chunk orchestration и public dispatch API не добавлены.

## S55 — automatic post-capture batch materialization (2026-09-17)

Завершён worker-integration срез без новой миграции и без расширения network
autonomy. `AiTransferPreparedDispatch` теперь получает server-validated
`chunk_count` из immutable execution admission. Поэтому first-chunk worker
больше не отправляет первый chunk multi execution в legacy single-chunk
`UNSUPPORTED_MULTI_CHUNK`: single execution использует S49 materialization, а
multi execution после каждого complete `SUCCESS/VALIDATED_RESPONSE` вызывает
S53/S54 batch materializer.

Worker повторно валидирует возвращённый progress: ordinals должны быть ordered и
contiguous, последний result либо rejection обязан exact-связываться с текущими
claim, receipt и raw-response ID, а финальный run обязан быть snapshot v3 с тем
же набором chunk results. Partial progress остаётся
`requirement_batch_pending=true`; complete batch возвращает `MATERIALIZED` и
run ID, semantic rejection — `REJECTED` без run ID.

Materialization выполняется только после атомарного сохранения transport receipt
и encrypted raw. Её ошибка не создаёт второй receipt и не вызывает network retry:
факт доставки уже durable и восстанавливается отдельным S54 endpoint. Worker
по-прежнему обрабатывает ровно один claim за invocation; он не claim-ит следующий
ordinal, не запускает batch-loop и не получает public dispatch route.

Evidence: полный no-DB gate — `767 passed`; fresh PostgreSQL 16 — `87 passed`;
doctest — `10 passed`. Ruff, scoped format, mypy по 55 source-файлам,
`uv lock --check` и `git diff --check` прошли. Схема не менялась, Alembic head
остаётся `20260917_12`. Production prerequisites S54 остаются обязательными.

## S56 — bounded internal multi-chunk coordinator (2026-09-18)

Завершён внутренний orchestration-срез без public dispatch route и без новой
миграции. `AiTransferBatchCoordinator.run_once` читает durable execution state и
выбирает ровно одно действие: first chunk для execution без claim, один next
chunk после exact successful terminal receipt, recovery после последнего chunk
либо fail-closed `STOPPED` для permanent claim без receipt и любого
неуспешного transport outcome.

Coordinator не содержит batch-loop: один invocation создаёт максимум один новый
permanent claim и выполняет максимум одну provider attempt. Все сетевые действия
делегированы S48/S52 workers, поэтому claim commit, approval clock, exact bytes,
no-redirect/no-retry и atomic raw capture остаются прежними. Concurrent
coordinators по-прежнему сериализуются repository/SQL claim boundary: проигравший
не получает второй сетевой вызов.

Typed outcome раскрывает только action, `PENDING | MATERIALIZED | REJECTED |
STOPPED`, ordinal и безопасные materialization/run IDs. API key и raw bytes в
него не входят. Final recovery повторно использует S49 либо S53/S54 boundary без
сети; complete execution не может остаться `PENDING`.

Evidence: полный no-DB gate — `770 passed`; fresh PostgreSQL 16 — `87 passed`;
doctest — `10 passed`. Ruff, scoped format, mypy по 55 source-файлам и
`uv lock --check` прошли. Alembic head остаётся `20260917_12`. Coordinator пока
не доступен через API/CLI и не является фоновой бесконечной задачей.

## S57 — bounded coordinator в local-pilot CLI (2026-09-18)

Завершён opt-in CLI-срез. Существующая команда
`dispatch-approved-ai-transfer` теперь вызывает
`AiTransferBatchCoordinator.run_once`, а не first-chunk worker напрямую. Каждый
явный запуск продвигает execution максимум на один permanent claim/provider
attempt либо выполняет no-network recovery. Команда не содержит batch-loop и не
создаёт background job.

Защитные условия S48 сохранены: требуется
`AI_TRANSFER_LOCAL_PILOT_ENABLED=1`, `DATABASE_URL`, непустой trimmed
`OPENROUTER_API_KEY` и pilot KEK configuration. Вывод raw-free: action, status,
reason, ordinal и безопасные claim/receipt/raw metadata/materialization/run IDs;
API key и response body не печатаются. Exit codes стабильны: `0` для
`PENDING/MATERIALIZED`, `3` для `DELIVERY_UNKNOWN`, `4` для
`REJECTED/STOPPED`, configuration/integrity error — `2`.

Evidence: полный no-DB gate — `772 passed`; последний fresh PostgreSQL gate
coordinator path — `87 passed`; doctest — `10 passed`. Ruff, scoped format, mypy
по 55 source-файлам, `uv lock --check` и `git diff --check` прошли. Alembic head
остаётся `20260917_12`; production API и фоновой scheduler не добавлены.

## S58 — coordinator concurrency и terminal recovery hardening (2026-09-18)

Завершён high-risk hardening без новой миграции и без расширения полномочий.
Typed `AiTransferBatchCoordinatorOutcome` теперь fail-closed запрещает
противоречивые комбинации: recovery не может вернуть `PENDING`, terminal
`MATERIALIZED/REJECTED` требует exact materialization/run evidence, а `STOPPED`
не может содержать materialization ID.

Fresh PostgreSQL проверка воспроизводит два coordinator invocation, одновременно
прочитавших одно исходное successful состояние. Permanent claim boundary
допускает ровно один новый ordinal и один HTTP-вызов; проигравший invocation
получает conflict до сети. Отдельный тест complete batch подтверждает, что
повторный coordinator step возвращает существующий run через `RECOVERY` и не
обращается к transport вообще.

Evidence: unit worker suite — `27 passed`; fresh PostgreSQL 16 с миграциями с
нуля, concurrency и no-network recovery — `88 passed`. Ruff, scoped format,
mypy и `git diff --check` прошли. Alembic head остаётся `20260917_12`;
production scheduler/API не добавлены.

## S59 — post-capture crash recovery evidence (2026-09-18)

Завершён recovery-срез без изменений production surface. На реальном
PostgreSQL воспроизведено падение процесса после atomic commit успешного
transport receipt и encrypted raw response, но до materialization. Следующий
`AiTransferBatchCoordinator.run_once` распознаёт terminal claim и выполняет
только server-side materialization: HTTP transport не вызывается и API key не
используется.

Проверены оба исхода single-chunk recovery: валидный captured result создаёт
reviewer-visible run со статусом `UNKNOWN`, semantic-invalid wire создаёт typed
`REJECTED` receipt, не меняя успешный transport outcome. Повторный recovery с
другим worker ID возвращает те же materialization/run IDs и также не обращается
к сети.

Evidence: полный fresh PostgreSQL 16 gate — `90 passed`; no-DB baseline остаётся
`776 passed`, doctest — `10 passed`. Ruff/format прошли, схема не менялась,
Alembic head остаётся `20260917_12`.

## S60 — корректный single/multi CLI recovery (2026-09-18)

Исправлен legacy-разрыв no-network команды `materialize-ai-transfer`. Раньше она
безусловно вызывала single-chunk S49 boundary и для multi execution могла
зафиксировать ложный `UNSUPPORTED_MULTI_CHUNK`, несмотря на доступный S53/S54
batch materializer. Теперь команда сначала читает immutable execution admission
и выбирает materializer строго по `chunk_count`.

CLI остаётся env-gated и не создаёт HTTP client. Для single и multi она печатает
единый raw-free результат: recovery mode, `PENDING | MATERIALIZED | REJECTED`,
ordered materialized ordinals, безопасный materialization/run ID и evidence
digest. Provider body, ciphertext, ключ и API key не выводятся. Unit contract
проверяет все четыре ветки: single materialized, multi pending, materialized и
rejected; неправильный materializer не вызывается.

Evidence: CLI suite — `16 passed`; Ruff и mypy прошли. Миграций, API routes и
network полномочий не добавлено; Alembic head остаётся `20260917_12`.

## S61 — pure-domain привязка terminal document-set решения к кейсу (2026-09-18)

Завершён preparation-only срез без сети, SQL, API и изменения production-флагов.
Новый `case-document-evidence-binding-v1` связывает точные
`DocumentSetReviewEvidence` и `DocumentSetReviewDecision` с заготовкой кейса:
вызывающий код передаёт явные `manifest_id`/`decision_sha256`, серверный builder
заново проецирует constituent reviews, сверяет tenant, manifest digest и ordered
member refs. Несовпадение, stale digest и автовыбор «последнего PASS» отклоняются.
Статус `PASS | FAIL | UNKNOWN` наследуется без повышения: привязка не объединяет
mappings, не создаёт `Requirement` и не разрешает `PARTICIPATE` — экономика, КП и
hard gates по-прежнему проверяются case evaluator. Binder обязан отличаться от
terminal decision maker; время привязки timezone-aware; digest канонический.

Владелец: Sol. Owned files: `src/procurement/documents/case_evidence.py` (new),
`tests/test_case_evidence_binding.py` (new), `src/procurement/documents/__init__.py`
(export), этот файл (только секция S61). Persistence (`case_evidence` таблицы,
RLS, API `POST /v1/cases/.../document-evidence`, UI) и session auth остаются
следующим отдельным срезом; production prerequisites S54 без изменений.

Evidence среза: focused suites — `28 passed`
(`test_case_evidence_binding` 11 + `test_document_set_review`/`test_document_set_evidence`/`test_document_completeness_review`
без регрессий); Ruff и strict mypy нового модуля проходят; формат проверен.
Полный no-DB gate — exit `0` без failures (интеграционные PostgreSQL/opt-in тесты
штатно пропущены без `DATABASE_URL`). Миграций не требовалось, Alembic head
остаётся `20260917_12`.

## S62 — persisted case-document-evidence binding и API (2026-09-18)

Завершён persistence+API срез без новой сети, UI и изменения production-флагов.
Миграция `20260918_01` добавляет tenant-scoped immutable таблицу
`case_document_evidence_bindings` с exact FK на manifest digest и terminal
decision, identity CHECK-проекцией JSON, RLS/FORCE RLS, runtime `SELECT/INSERT` и
запретом `UPDATE/DELETE`. Repository в одной транзакции перечитывает exact
evidence/decision, сверяет запрошенные digest, строит binding через S61 builder,
пишет строку, audit `case.evidence_binding_created` и idempotency receipt;
loader при чтении перестраивает binding из текущих exact строк и отвергает
подмену. Повтор exact запроса возвращает прежний binding, смена payload с тем же
ключом даёт конфликт, чужой/отсутствующий binding — `404`.

`POST /v1/case-document-evidence-bindings` доступен только `OPERATOR`, читает
strict JSON до 16 КиБ (duplicate keys, non-finite, oversized отклоняются),
binding ID назначает сервер; `GET /v1/case-document-evidence-bindings/{binding_id}`
tenant-scoped для любой аутентифицированной роли. Оба ответа `no-store`.
Ошибки разделены на `401/403/404/409/413/415/422`; binder, равный terminal
decider, получает `422`. UI и session auth остаются следующим отдельным срезом.

Владелец: Terra. Owned files: `migrations/versions/20260918_01_*` (new),
`src/procurement/storage/models.py`, `repository.py`, `__init__.py`,
`src/procurement/api/contracts.py`, `postgres.py`, `app.py`,
`tests/test_case_evidence_api.py` (new),
`tests/integration/test_case_evidence_binding_sql.py` (new), этот файл.

Evidence среза: focused suites — `18 passed`
(`test_case_evidence_binding` 11 + `test_case_evidence_api` 7);
integration SQL (`store/replay/get/RLS/immutability/forged-row`) собран и штатно
пропущен без `DATABASE_URL`. Полный no-DB gate — exit `0`; Ruff всех затронутых
файлов проходит; Alembic single head `20260918_01`, полная цепочка компилируется
в offline SQL (2687 строк). Production prerequisites S54 без изменений.

## S63 — DOCUMENT-проверка кейса из case-привязки (2026-09-18)

Завершён preparation-only срез без сети, SQL, API и изменения production-флагов.
`document_gate_check_from_binding` детерминированно выводит `GateCheck`
(`GateKind.DOCUMENT`) из immutable `CaseDocumentEvidenceBinding`: статус
наследуется один к одному (`FAIL` блокирует кандидата через существующий hard
gate, `UNKNOWN` не становится допуском), reason ссылается на точный decision
digest и manifest, evidence — `Provenance` с `document_id=manifest_id`,
`locator=terminal decision <digest>`, `MANUAL`, confidence `1.0`. Функция
перепроверяет digest привязки и не выполняет ввод-вывод. Проверка сама по себе
не разрешает `PARTICIPATE`: оператор включает её в полную оценку кейса, а КП,
сценарии и остальные gates по-прежнему проверяет case evaluator.

Владелец: Sol. Owned files: `src/procurement/documents/case_evidence.py`,
`src/procurement/documents/__init__.py` (export),
`tests/test_case_evidence_binding.py`, этот файл (только секция S63).
Persistence оценки кейса и API создания кейса из привязки остаются следующим
отдельным срезом.

Evidence среза: focused suite — `16 passed`
(`test_case_evidence_binding` 11 + 5 новых gate-тестов); Ruff, format и strict
mypy модуля проходят. Полный no-DB gate — exit `0` без failures (интеграционные
PostgreSQL/opt-in тесты штатно пропущены без `DATABASE_URL`).

## S64 — создание кейса из case-привязки (2026-09-18)

Завершён вертикальный срез documents → case без новой миграции и изменения
production-флагов. `PostgresStorage.create_case_from_evidence` в одной
транзакции перечитывает exact binding, сверяет запрошенные digest, выводит
DOCUMENT-проверку через S63, отвергает caller-owned assessment и DOCUMENT в
`other_checks` (не более пяти), собирает `CaseAssessment` с reviewer=actor,
server-time и `input_digest` по точному снимку и пишет версию через проверенный
`_insert_case` вместе с audit `case.created_from_evidence` и idempotency
receipt. Повтор exact запроса возвращает тот же кейс, смена payload — конфликт,
чужой/отсутствующий binding — `404`, stale digest и невалидный драфт — `422`.

`POST /v1/cases/from-evidence` доступен только `OPERATOR`, читает strict JSON до
256 КиБ, проверяет tenant и отдаёт созданный `ProcurementCase` с `no-store`.
Созданный кейс читается существующим `GET /v1/cases/{id}/versions/{v}` и
оценивается существующим evaluation-путем без изменений. Новых версий,
автовыбора binding и UI в срезе нет.

Владелец: Sol. Owned files: `src/procurement/storage/repository.py`,
`src/procurement/api/contracts.py`, `postgres.py`, `app.py`,
`tests/test_case_from_evidence_api.py` (new),
`tests/integration/test_case_from_evidence_sql.py` (new), этот файл.

Evidence среза: API suite — `6 passed`; integration SQL (server assessment,
replay/conflict, stale/missing/foreign, caller assessment/DOCUMENT, version
collision, audit immutability) собран и штатно пропущен без `DATABASE_URL`;
Ruff/format всех затронутых файлов проходят; маршрут виден в OpenAPI.
Полный no-DB gate — exit `0`.

## S65 — операторский экран создания кейса из привязки (2026-09-18)

Завершён UI-срез без новой сети, миграций и изменения production-флагов.
`web/src/app/case-from-evidence` (server page + client form + server action)
принимает exact binding ID/digest, JSON драфта кейса без assessment и
опциональный JSON дополнительных проверок (до 5, без kind document), проверяет
границы локально и создаёт кейс через `POST /v1/cases/from-evidence` с
server-only operator token. Bearer не попадает в browser bundle; idempotency
key генерирует сервер. Успех показывает case ID/версию и server-derived
DOCUMENT-статус; ошибки API объясняются без трассировок. Очереди, latest и
автовыбора привязки нет; inbound-навигация не менялась.

Владелец: Terra. Owned files: `web/src/lib/procurement-api.ts`
(`createCaseFromEvidence`), `web/src/app/case-from-evidence/{page,form,actions}.ts*`,
этот файл. Reviewer session auth остаётся отдельным срезом.

Evidence среза: Next.js ESLint и production build проходят; маршрут
`/case-from-evidence` собран как static; production smoke — `200`, заголовок и
форма exact привязки на месте. Python gate после среза не менялся.

## S66 — сквозной regression привязка → кейс → recommendation (2026-09-18)

Завершён test-only срез без изменения кода продукта, миграций и флагов.
`tests/test_case_from_evidence_e2e.py` фиксирует поведение server-derived
DOCUMENT-проверки внутри `evaluate_case` на синтетическом paper-кейсе:
PASS-путь даёт `PARTICIPATE` и совпадает с ручным baseline один к одному,
FAIL-путь даёт `DO_NOT_PARTICIPATE` с основанием `document:`, UNKNOWN-путь даёт
`NEEDS_ANALYSIS` без превращения в допуск. Свежесть `input_digest` нового пути
проверена явно.

Владелец: Terra. Owned files: `tests/test_case_from_evidence_e2e.py` (new),
этот файл (только секция S66).

Evidence среза: `3 passed`; Ruff/format проходят. Полный no-DB gate — exit `0`.

## S67 — runbook пилотного прогона (2026-09-18)

Завершён docs-only срез без изменения кода, миграций и флагов.
`docs/operations/21-pilot-runbook.md` задаёт порядок исполнения стабилизационного пилота
по реализованному серверному пути (окружение и gate, комплекты и manifest,
загрузка/extraction/OCR, completeness, manifest и terminal decision, binding,
кейс из привязки, evaluation, опциональный AI-путь, негативный контроль,
свёрка и отчёт) со ссылками на протокол и S2. Приложение A фиксирует точный
список данных и решений от владельца: 10–20 комплектов, роли, ground truth,
цель recall, решение по AI-пути, окно пилота, Docker gate. Без пунктов 1–3
результат пилота остаётся `UNKNOWN`.

Владелец: Luna. Owned files: `docs/operations/21-pilot-runbook.md` (new),
`docs/README.md` (строка навигации), этот файл (только секция S67).

Evidence среза: Markdown проверен машинно (fences сбалансированы, таблицы
корректны, ссылки ведут на существующие документы). Исполнение пилота требует
данных и решений владельца и в срез не входило.

## S68 — публичный classifier feed ЕАТ и первый source probe (2026-09-19)

Владелец: Codex (основной агент). Owned files: `src/procurement/sources/__init__.py`,
`src/procurement/sources/eat_classifier.py`, `tests/test_eat_classifier.py`,
`docs/research/07-research-log.md` (секция проверки источников), `docs/product/05-roadmap.md`
(вводный статус) и этот файл (статус S4 и S68). Зависимость: опубликованная
документация ЕАТ и публичный ZIP; ни токен, ни отправка на площадку не нужны.

Read-only probe скачивает только фиксированный публичный URL классификатора ЕАТ,
ограничивает размер ответа и XML, запрещает redirects, proxy и произвольный URL,
проверяет структуру ZIP/XML, уникальность и родителей категорий. Результат
содержит URL, timezone-aware время и SHA-256 точных bytes. Ошибка доступа или
формата даёт `UNKNOWN`; `PASS` означает только успешное чтение классификатора.

Acceptance: синтетические тесты отвергают повреждённый/лишний ZIP, DTD,
дубли и отсутствующего родителя; живой `GET` разбирает опубликованный архив;
количество категорий, digest и время воспроизводимо фиксируются без выдачи
категорий за закупки, товары или КП.

Evidence: `python -m procurement.sources.eat_classifier` — HTTP 200,
403 203 байта, SHA-256
`3d1f2ad92d28b3761dd5ab7830b2d2742a436503cace79cb597fd70f021e81d5`,
12 825 категорий (10 479 активных, 2 346 удалённых); 8 unit-тестов,
Ruff и strict mypy нового модуля прошли. Сервис ЕИС и методы ЕАТ с токеном
не проверены: доступность их API и покрытие закупок остаются `UNKNOWN`.

Следующий ограниченный продуктовый срез: получить актуальную спецификацию и
разрешённый доступ к read-only сервису ЕИС; проверить одну процедуру, её
deadline/статус и вложения с immutable bytes/SHA. Параллельно допустим
пользовательский импорт через отдельные слоты ТЗ и КП поверх существующего
`document_role`. Проверка на 3–5 реальных закупках одной категории предшествует
формальному пилоту на 10–20 комплектах; ручная сборка КП из эталона не считается
доказательством автоматизации поиска поставщиков или разбора КП.

## S69 — операторские слоты загрузки ТЗ и КП (2026-09-19)

Владелец: Codex (основной агент). Owned files: `web/next.config.ts`,
`web/src/lib/procurement-api.ts` (upload helper), `web/src/app/document-upload/`
(новая страница), `web/src/app/pilot-dashboard.tsx` (ссылка),
`web/README.md`, `docs/operations/18-first-screen.md` (раздел S69),
`docs/research/07-research-log.md` (дополнение о прямом доступе ЕИС), этот файл
(только S69). Зависимость: существующий `POST /v1/documents` и операторский
server-only bearer.

На `/document-upload` выбор слота серверно фиксирует `TENDER_REQUIREMENTS`
или `SUPPLIER_QUOTE` до загрузки одного PDF/DOCX/XLSX. Проверяется размер
до 20 МиБ и имя; API сохраняет исходные bytes, роль и SHA-256. Экран показывает
ID, SHA-256, status/reasons извлечения. Ни один результат не называется
проверенным КП, требованием или решением об участии. ZIP и связь документов
с одной закупкой остаются следующими пользовательскими задачами.

Acceptance: с главного экрана доступна загрузка в оба слота; browser bundle
не содержит bearer; role назначается server action, а не текстом документа;
неподдержанный/пустой/слишком большой файл отклоняется; полученный статус
`UNKNOWN` остаётся видимым. Проверки: Next.js lint/build и существующие
API/domain тесты загрузки документа и роли.

Evidence: `npm run lint` и `npm run build` прошли; build включает маршрут
`/document-upload`. Выбранные API/domain тесты прошли. Реальный upload через
Next.js → FastAPI → PostgreSQL в этой среде не выполнен: Docker server
недоступен, поэтому runtime-приёмка этого пути остаётся `UNKNOWN`.

Одна процедура ЕИС пока не получена: в этой среде публичная главная страница
отвечает, но прямые запросы карточек нестабильно возвращают `404`; сервис
машиночитаемых данных и разрешённый токен не доступны. Номер процедуры,
deadline и вложения поэтому не выдаются за проверенный факт.

## S70 — диагностический прогон реальной закупки ЕИС (2026-09-19)

Владелец: Codex (основной агент). Owned files: `docs/research/07-research-log.md`
(добавление диагностического evidence), этот файл (секция S70). Зависимость:
публичная закупка № 0359100000626000015 и существующие функции native
extraction/mapping. Acceptance: получить точные байты хотя бы одного вложения
ЕИС, проверить SHA-256 и формат, запустить извлечение и маппинг без подмены
`UNKNOWN` на `PASS`; отдельно назвать непроверенные слои.

Evidence: все пять DOCX получены непосредственно с ЕИС с HTTP 200 при
браузерном `User-Agent`; точные размеры, digest и статусы в журнале исследования.
ТЗ — 56 223 байта, SHA-256
`a466032c5e9a0d3684d952a47e9733b8b8b52e457fc1df6d2e8cd08b5fb0489e`:
native extraction `PASS`, 567 блоков, 21 022 символа. Маппинг ТЗ нашёл
0 требований: 567 блоков `unmapped`, completeness `UNKNOWN`. Корневой пример:
характеристика, порог и единица таблицы извлекаются в отдельные ячейки, а
текущий маппер не связывает их по строке. У трёх других DOCX статус extraction
`UNKNOWN` из-за `EXTERNAL_LINKS_IGNORED`; обоснование НМЦК — `PASS`.
Ни полнота комплекта, ни готовность API+PostgreSQL, ни кандидат/КП/экономика
этим прогоном не подтверждены. Код и миграции не менялись.

Следующий ограниченный срез: table-aware candidate extraction для точных
row/cell provenance с независимой проверкой на этом ТЗ; не выдавать
эвристическую сборку строки за подтверждённую полноту или решение об участии.

## S71 — два публичных ТЗ ЕИС и источники поиска производителей (2026-09-19)

Владелец: Codex (основной агент). Owned files: `samples/private/eis/README.md`
и три неизменённых DOCX в двух подкаталогах, этот файл (только S71).
Зависимости: публичные ссылки ЕИС, существующий native extractor и mapper.
Acceptance: два разных комплекта, прямые исходники ЕИС, размеры и SHA-256,
диагностика извлечения/маппинга и маршрут поиска производителей без ложного
утверждения о соответствии конкретного товара.

Собраны закупки № 0359100000626000015 (ПК и периферия) и
№ 0142200001326017501 (сервер): во втором комплекте основное ТЗ и приложение
«Описание объекта закупки» нужны вместе. Все три DOCX получены с HTTP 200,
exact bytes/URL/digest записаны в локальном manifest. Native extraction даёт
`PASS` для трёх файлов, но mapping — 0 требований и completeness `UNKNOWN`.
Дополнительный gap: вложенная таблица описания сервера имеет 87 строк;
`word/document.xml` содержит 11 668 текстовых символов, тогда как extractor
возвращает лишь 647. Из-за этого поиск по автоматическому output пока
недопустим как полный поиск эквивалентных изделий. Ни производитель, ни
точная модель, ни цена, ни реестровый статус не подтверждены этим срезом.

Порядок sourcing для этой категории: ГИСП/реестры и каталог продукции для
кандидатов и происхождения → каталоги самих производителей для exact model
и спецификаций → B2B-каталоги/маркетплейсы для предложения, наличия, цены и
контакта. ЕИС — источник спроса; ЕАТ «Берёзка» и ЭТП — не доказательство
статуса производителя. Выбор площадок и условия автоматизированного доступа
нуждаются в отдельной проверке перед коннектором.

## S72 — вложенные таблицы DOCX на реальном серверном ТЗ (2026-09-19)

Владелец: Codex (основной агент). Owned files:
`src/procurement/documents/extraction.py`, `tests/test_document_extraction.py`,
`docs/documents/19-document-pipeline.md` (контракт DOCX),
`samples/private/eis/README.md` (локальный ignored manifest), этот файл
(секция S72). Зависимость: exact bytes приложения к закупке
№ 0142200001326017501, SHA-256
`e8103ee396069f05b7b55c4e978733842da3d098e6b32c90d659b6f0824e3f83`.

Извлекатель теперь обходит вложенные таблицы итеративно, выдаёт полный
row/cell locator, не дублирует merged-ячейки и применяет resource limits к
вложенным единицам. Синтетические регрессии покрывают два уровня вложенности,
точные locators, повторяющиеся merged-ячейки, лимит source units и символов.
На неизменённом реальном файле: **279 блоков / 11 632 символа** вместо
18 / 647; 261 вложенный блок охватывает все 87 строк таблицы. Два остальных
сохранённых ТЗ не изменили число блоков (567 и 34). Повторные прогоны
детерминированы. Все три native extraction — `PASS`, но mapping в каждом случае
по-прежнему 0, completeness `UNKNOWN`: связывание ячеек в требования и
подтверждение модели — отдельный следующий срез. Старые persisted snapshots
не мутируются автоматически.

Evidence: focused document extraction/facts/completeness tests — 63 passed;
полный no-DB `pytest` — exit 0; `ruff check .`, doctests домена и `mypy`
домена+извлекателя — exit 0. PostgreSQL gate не выполнен: Docker daemon в
локальной среде недоступен. Внешние RFQ и отправки не выполнялись.

## S73 — кандидаты требований из строк таблиц DOCX (2026-09-20)

Владелец: Codex (основной агент). Owned files:
`src/procurement/documents/facts.py`, `tests/test_document_facts.py`,
`docs/documents/19-document-pipeline.md`, `samples/private/eis/README.md` (локально),
этот файл (секция S73). Зависимость: S72 и сохранённые exact bytes трёх
публичных DOCX. Acceptance: связывать только соседние ячейки той же строки
и документа, поддержать вложенные таблицы и отдельную единицу, сохранять
source locators, не создавать подтверждённое требование из кандидата;
распознать явную фразу о гарантии и не повышать полноту выше `UNKNOWN`.

Реализован `TableRowCandidate` для числовых `GE/LE` из нативного DOCX:
исходные ячейки и точные provenance сохранены, `requirements` и
`blocks_mapped` кандидатами не увеличиваются, все эти ячейки остаются
`unmapped`. На неизменённых публичных файлах получено 86 кандидатов
для ТЗ на ПК и 28 для приложения сервера; основное ТЗ сервера даёт
одно `warranty >= 36 мес` из `paragraph 35`. Во всех трёх документах
`completeness=UNKNOWN`. Никакой модели/производителя или КП не подтверждено.
Следующий срез — human review кандидатов, нормализация свойств/единиц
и поиск моделей только по проверенному набору требований.

Evidence: focused facts — 49 passed; полный no-DB `pytest` — exit 0;
`ruff check` и `ruff format --check` для owned code — exit 0; `mypy`
маппера — exit 0. PostgreSQL gate в этом срезе не выполнялся; Docker
daemon локально недоступен. Старые persisted snapshots не мутируются.

## S74 — triage серверного ТЗ и каталогов производителей (2026-09-20)

Владелец: Codex (основной агент). Owned files:
`docs/suppliers/22-server-sourcing-triage.md` (новый), `docs/README.md` (одна строка),
этот файл (секция S74). Зависимости: S73, два exact DOCX закупки
№ 0142200001326017501 и публичные официальные каталоги. Acceptance:
сверить все 28 числовых кандидатов с source rows; проверить минимум два
реальных семейства по прямым источникам производителя; не объявлять
совместимость конфигурации, реестровый статус или КП без доказательства.

Создан аналитический отчёт S74: 28 числовых строк с точной схемой locator,
отдельно отмечены остальные 59 строк и условия основного ТЗ.
HPE DL360 Gen12 — перспективное семейство, но без exact BOM итог `UNKNOWN`.
Lenovo SR630 V3 конфликтует с требованием двух OCP 3.0-слотов, Dell R660 —
с четырьмя LFF-отсеками; это не предложения поставщиков. Публичная страница
реестра ГИСП в этой среде возвращает HTTP 403, поэтому национальный
реестровый статус не подтверждён. Formal independent review, оценки
в API/PostgreSQL, RFQ, цены и участие не выполнялись.

Evidence: exact SHA-256 двух DOCX сохранены в отчёте; ручная сверка
локаторов и текста; ссылки на HPE QuickSpecs, Lenovo Product Guide и
Dell official product page. Markdown-ссылки/таблицы проверены; код и
миграции не менялись.

## S75 — reviewer packet 87 строк и SKU skeleton HPE (2026-09-20)

Владелец: Codex (основной агент). Owned files:
`docs/suppliers/23-server-review-bom.md` (новый), `docs/README.md` (одна строка),
этот файл (секция S75). Зависимости: exact bytes двух DOCX из S71,
S73/S74 и актуальные официальные каталоги HPE/Intel. Acceptance: все 87
строк приложения с исходными значениями и точной схемой locators;
условия основного ТЗ отдельно; предварительные SKU не называются
проверенным BOM, review и предложение не симулируются.

Ведомость покрывает 87/87 строк, включая 59 ранее не распознанных
числовым маппером. Черновик содержит SKU 4LFF шасси, CPU, ОЗУ, SATA SSD,
PSU, PCIe RAID-контроллера и кабеля для запроса exact BOM; разные
каталожные опции не складываются в автоматический `PASS`. Нужны
независимый reviewer и официальный совместимый BOM/КП. Внешних сообщений
и persisted review не было; статус HPE/комплекта остаётся `UNKNOWN`.

Evidence: 87 строк сверены с неизменённым локальным DOCX по cell text/locator;
SKU сверены с официальными HPE QuickSpecs и Intel CPU specifications.
Markdown и ссылки проверены; код и миграции не менялись.

## S76 — частичная программная проверка серверного BOM (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый
`src/procurement/domain/server_bom.py`, `tests/test_server_bom.py`,
`src/procurement/domain/units.py` (алиас `Гбайт`), `tests/test_units.py`
(один тестовый вариант), `docs/architecture/03-compliance-engine.md` (секция BOM),
этот файл (секция S76). Зависимости: S75 и существующие `Requirement`,
`Attribute`, `Provenance`, `check_requirement`. Acceptance: семь критичных
числовых gates по установленным деталям, provenance и digest входа,
`FAIL` при доказанном обязательном нарушении, `UNKNOWN` при неполном
составе/слабом источнике; общий `PASS` невозможен. Проверка без API,
persisted review и без автоматического превращения каталога в exact BOM.

Реализован отдельный доменный диагностический срез; он не меняет общий
compliance/evaluation pipeline. `EXACT_CONFIG` — только явное утверждение
полноты источника со стороны вызывающего workflow; код проверяет привязку
строк к одному документу, но не подлинность его содержания. Поэтому выход
не утверждает соответствие всей закупке и не изменяет прежний `UNKNOWN`
по HPE. Следующий срез — получение и независимая проверка настоящего BOM/КП
конкретной сборки, затем сопоставление всех строк ТЗ и интеграция через
существующий серверный путь.

Evidence S76: `uv run pytest tests/test_server_bom.py tests/test_units.py
tests/test_compliance.py` — 83 passed; `uv run pytest tests
--ignore=tests/integration` — 839 passed; Ruff check/format и mypy нового
модуля — пройдены. PostgreSQL gate и реальный BOM-прогон не выполнялись.

## S77 — публичный маршрут к exact HPE BOM (2026-09-20)

Владелец: Codex (основной агент). Owned files: `docs/suppliers/23-server-review-bom.md`
(раздел дополнительной проверки), `docs/research/07-research-log.md` (раздел
публичного поиска), этот файл (секция S77). Зависимости:
S75–S76 и официальный QuickSpecs. Acceptance: проверить открытый HPE OCS,
не менее одного российского и одного зарубежного маршрута конфигурации;
не путать каталог опций с exact BOM и не отправлять внешние заявки.

OCS анонимно открыт и показывает DL360 Gen12 в каталоге США, но не в
просмотренном каталоге РФ; требуемый 4LFF CTO не найден среди стартовых
американских BTO-моделей. Proliant.ru публикует список SKU, ЛайтНэт и
Express Computer Systems предлагают подбор через заявку, но открытого
валидированного единого BOM для этого ТЗ не обнаружено. По QuickSpecs
выявлены обязательные зависимости 4LFF от контроллера/кабеля и отсутствие
встроенной сети в CTO. Результат HPE — `UNKNOWN`; external RFQ/quote,
регистрация, покупка и оценка всей закупки не выполнялись. Evidence:
публичные страницы источников и фактический анонимный проход OCS; проверки
кода не требовались, поскольку срез docs-only.

## S78 — предварительный shortlist наблюдений о серверных товарах (2026-09-20)

Владелец: Codex (основной агент). Owned files:
`src/procurement/domain/sourcing.py` (новый), `tests/test_sourcing.py`
(новый), этот файл (только секция S78). Зависимости: S76 и существующий
`assess_server_bom`. Acceptance: входная карточка имеет HTTPS URL, digest
снимка и timezone-aware момент; цена — только `Decimal`; подтверждённый
обязательный `FAIL` уходит из очереди, недостающие данные остаются на review;
ни цена, ни частичный BOM не создают `PASS` или действительное КП.

Реализована чистая доменная функция `shortlist_server_leads` для уже найденных
наблюдений. Она отделяет `REJECTED` от `NEEDS_TECHNICAL_REVIEW`, сохраняет
причины/непроверенные свойства и не ранжирует по непроверенной цене. Это
**фильтрация входных карточек, не автоматический поиск площадок**: адаптеры
публичных источников, дедупликация между сайтами, актуальность цены/остатка,
полный reviewer и отправка RFQ остаются в S5. HPE по-прежнему `UNKNOWN`.

Evidence: `uv run pytest tests/test_sourcing.py tests/test_server_bom.py`
— 12 passed; Ruff и mypy нового модуля проходят. Live-каталоги и PostgreSQL
в этом срезе не тестировались.

## S79 — read-only поиск в одном публичном каталоге (2026-09-20)

Владелец: Codex (основной агент). Owned files:
`src/procurement/sources/servermall.py` (новый), `tests/test_servermall_source.py`
(новый), `src/procurement/domain/sourcing.py` (поле `product_url`), этот файл
(только секция S79). Зависимости: S78 и публичная страница ServerMall HPE Gen12.
Acceptance: один фиксированный GET без redirect/login/form; ограниченный HTML;
строгий разбор JSON-LD OfferCatalog, allowlist ссылок и digest exact bytes;
полученные названия идут в shortlist без подмены цены базы на КП и без
автоматического технического PASS.

Адаптер `search_servermall_hpe_gen12` читает одну публичную страницу каталога,
ищет по названию и создаёт `ServerLead` с URL страницы товара и digest
снимка каталога. Не обходит весь сайт, не открывает карточки товаров, не
извлекает exact BOM и не сохраняет HTML в БД. Поэтому отсутствие находок на
этой странице не доказывает отсутствие товара на рынке. Структурированная
цена не импортируется: страница товара называет её ценой базы без компонентов.

Live evidence: поиск `DL360 Gen12` дал 1 карточку
`HPE ProLiant DL360 Gen12 8SFF`, URL
`https://servermall.ru/catalog/servers/hpe-proliant-dl360-gen12-8sff/`, digest
каталога `a9b229df4195c2b381fa86ecad6d92453ca449211c3503ac18c213ccea5edeb5`.
При отсутствии подтверждённого BOM карточка остаётся в review queue,
`price_rub=None`; это не 4LFF предложение и не подтверждённое соответствие
ТЗ. Evidence: `uv run pytest tests --ignore=tests/integration` — 851 passed;
Ruff check/format и mypy новых модулей проходят. PostgreSQL gate не запускался.

## S80 — case-bound sourcing run и операторский экран (2026-09-20)

Владелец: Codex (основной агент). Owned files: доменный контракт sourcing run,
адаптер ServerMall, PostgreSQL schema/repository и миграция `20260920_01`,
FastAPI contracts/routes, карточка кейса в pilot UI, связанные тесты и эта секция.
Зависимости: S78–S79, immutable `ProcurementCase`, tenant RLS и write receipts.
Acceptance: запуск относится к точным `case_id + version`; exact HTML успешного
ответа сохраняется с SHA-256 и audit event; replay идемпотентен; чужой tenant
получает `404`; UI различает найденные карточки, ноль совпадений и ошибку источника.

Реализованы `POST .../sourcing-runs` и `GET .../sourcing-runs/latest` для одного
allowlisted источника ServerMall. Успешный ответ хранится неизменяемо вместе с
исходными bytes, но HTML не выдаётся через API. Ошибка сети или изменившийся
формат сохраняется как `SOURCE_ERROR` без ложной пустой выдачи и без сохранения
невалидированного ответа. Экран показывает URL карточки, время, digest и статус
technical review.

Существенная граница: в `ProcurementCase` ещё нет исполнимой независимо
проверенной версии всех технических требований, а AI review по контракту не
материализует `Requirement`. Поэтому sourcing run всегда сохраняет
`technical_scope_status=UNKNOWN` и прямо сообщает, что нужен exact BOM.
Следующий срез — persisted reviewed requirement set для 87 строк и его exact
binding к версии кейса; только после него shortlist сможет выполнять технические
gates для найденных карточек.

## S81 — reviewed requirement set и exact case binding (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый доменный контракт
`documents/reviewed_requirements.py`, PostgreSQL schema/repository и миграция
`20260920_02`, FastAPI contracts/routes, sourcing binding, минимальное отображение
binding в pilot UI, связанные тесты и документация. Зависимости: S73, S75–S76,
S80, immutable document/case storage и роль `COMPLETENESS_REVIEWER`. Acceptance:
каждая исходная строка сохранена по порядку с provenance; строка либо содержит
typed `Requirement`, либо явно остаётся manual review; автор не принимает своё
предложение; только exact terminal `PASS` привязывается к одной версии кейса;
sourcing использует только исполнимую часть такого binding и не создаёт общий
technical `PASS`.

Реализованы append-only `reviewed_requirement_set_proposals`,
`reviewed_requirement_set_decisions` и `case_requirement_set_bindings` с
RLS/FORCE RLS, exact composite FK, write receipts и audit. Proposal проверяет
полное непрерывное покрытие `1..expected_entry_count`, source document digest и
provenance каждой строки. Decision требует другого actor; `PASS` допустим только
при `CONFIRMED` coverage и `REVIEWED` normalization. Binding требует третью
операцию operator и запрещает reviewer быть binder. Автовыбора latest нет.

API добавляет создание/чтение набора, reviewer decision и создание/чтение exact
case binding. В пилотном распределении отдельная роль технического reviewer ещё
не заведена: endpoint решения использует существующую изолированную роль
`COMPLETENESS_REVIEWER`. Sourcing run сохраняет set/proposal/decision/binding
digests, применяет typed requirements и оставляет manual ordinals открытыми.
Публичная карточка и частичный BOM по-прежнему не являются КП и не дают `PASS`.

Evidence: `pytest tests --ignore=tests/integration` — 864 passed; domain doctest —
9 passed; Ruff и mypy (62 source files) — passed; web ESLint, `tsc --noEmit` и
production build — passed; Alembic имеет один head `20260920_02`, offline SQL
содержит все три новые таблицы. SQL integration test добавлен, но локально
пропущен без `DATABASE_URL` (Docker daemon недоступен).

## S82 — server-derived materialization всех строк DOCX (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый
`documents/requirement_set_materialization.py`, два FastAPI endpoint и методы
PostgreSQL service, операторский маршрут `/requirement-set-materialization`,
связанные тесты, ADR-0029 и статусная документация. Зависимости: S72–S73,
S81 и persisted immutable document/extraction. Acceptance: сервер сам находит
ровно одну полную native DOCX-таблицу с ожидаемыми строками `1..N`; browser не
может заменить исходные name/value/provenance; preview привязан digest; только
явно выбранная показанная числовая подсказка становится typed requirement;
остальные строки сохраняются как `MANUAL_REVIEW_REQUIRED`.

Реализован двухшаговый workflow. Preview требует exact document SHA-256,
`TENDER_REQUIREMENTS`, extraction `PASS`, непрерывные строки и ячейки 1–2;
неоднозначная или неполная таблица отклоняется. Commit повторно строит preview
из persisted source и сверяет digest, поэтому устаревшая либо изменённая форма
не материализуется. Число/operator/value берутся только из server-derived
кандидата; оператор явно задаёт canonical property, unit, mandatory и основание.
Невыбранная подсказка не считается согласием. Proposal по-прежнему требует
отдельного решения reviewer и exact case binding из S81.

На неизменённом локальном приложении закупки № 0142200001326017501 с SHA-256
`e8103ee396069f05b7b55c4e978733842da3d098e6b32c90d659b6f0824e3f83`
preview детерминированно восстановил **87/87 строк** из
`table 1 row 3 cell 3 nested table 1`, показал 28 числовых подсказок и получил
валидный canonical digest, привязанный также к tenant/document identity. Это
локальная проверка materializer, не reviewer `PASS` и не созданное КП.

Evidence: full no-DB pytest — 870 passed; domain doctest — 9 passed; Ruff и
mypy (63 source files) — passed; web ESLint, `tsc --noEmit` и production build —
passed. Alembic сохранил единственный head `20260920_02`; PostgreSQL schema в
S82 не менялась. SQL integration test пропущен без `DATABASE_URL`/Docker.

## S83 — официальный каталог производителя с supplier failover (2026-09-20)

Владелец: Codex (основной агент). Owned files: новые адаптеры
`sources/manufacturer_catalog.py` и `sources/catalog_search.py`, расширение
typed sourcing lead, существующий case-bound sourcing service/UI, тесты,
ADR-0030 и статусная документация. Зависимости: S79–S82. Acceptance: точный
запрос поддерживаемого семейства сначала читает allowlisted официальный источник;
успех сохраняет exact bytes/digest и явно помечает manufacturer catalog;
страница семейства не становится ценой, exact BOM или техническим `PASS`;
недоступность HPE official source допускает один релевантный ServerMall fallback,
а двойная ошибка сохраняется как `SOURCE_ERROR`; Lenovo не использует
нерелевантный HPE supplier catalog.

Allowlist содержит две проверенные официальные страницы: HPE ProLiant Compute
DL360 Gen12 QuickSpecs (`hpe.com/psnow`) и Lenovo ThinkSystem SR630 V3 Product
Guide (`lenovopress.lenovo.com`). Маршрутизация требует отличительную пару
model+generation (`DL360 Gen12` или `SR630 V3`); общие запросы вроде `server`
не приписываются случайному производителю. HTTP ограничен одним GET без redirect,
HTML — 2 МиБ, host/URL заданы кодом, visible title обязан совпасть. Exact
snapshot сохраняется прежним append-only S80 storage, поэтому миграция не нужна.

`ServerLead` теперь различает `MANUFACTURER_CATALOG` и `SUPPLIER_CATALOG` и
содержит явный manufacturer. Для official family page доменная модель запрещает
цену и BOM. Операторский экран показывает тип источника. Это уже исполнимый
поиск по двум официальным семействам, но не общий поиск по всем производителям,
не конфигуратор и не реестр происхождения. Dell и другие семейства остаются
следующими независимыми адаптерами.

Evidence: official HPE/Lenovo URLs сверены 2026-09-20; parser/routing/failover,
ошибки identity и доменные запреты покрыты тестами. Full no-DB pytest — 880
passed; domain doctest — 9 passed; Ruff и mypy (65 source files) — passed; web
ESLint, `tsc --noEmit` и production build — passed. Alembic сохранил один head
`20260920_02`; migration не требовалась. Live GET из локального Python
окружения остаётся недоступен из-за DNS; сетевой отказ проверяется как явный
fallback/error path. PostgreSQL integration пропущен без `DATABASE_URL`.

## S84 — Dell R660 и exact multi-source sourcing run (2026-09-20)

Владелец: Codex (основной агент). Owned files: sourcing domain/adapters/service,
PostgreSQL model/repository и миграция `20260920_03`, sourcing UI, связанные
tests, ADR-0031 и статусная документация. Зависимости: S80–S83. Acceptance:
каждый запрошенный источник получает отдельные status, media type, URL,
observed-at, exact bytes/digest либо error code; хотя бы один успешный source
делает run `COMPLETED`, но не скрывает ошибки остальных; без успешных snapshots
run остаётся `SOURCE_ERROR`; все artifacts tenant-scoped и append-only.

Allowlist расширен официальным Dell PowerEdge R660 Technical Guide. Для PDF
действуют direct allowlisted URL, `application/pdf`, лимит 20 МиБ, максимум 200
страниц и identity по metadata/тексту первых восьми страниц. Dell family lead,
как HPE/Lenovo, не содержит цены или exact BOM и остаётся в technical review.

HPE `DL360 Gen12` теперь в одном run проверяет два релевантных источника:
official QuickSpecs и ServerMall HPE Gen12. Каждый attempt сохраняется независимо.
Lenovo и Dell не вызывают нерелевантный HPE supplier catalog. Parent
`sourcing_runs.source_content` содержит небольшой canonical manifest метаданных;
новая `sourcing_run_sources` хранит exact source bytes с собственным SHA-256,
RLS/FORCE RLS, composite FK и immutable trigger. Deferred constraint trigger
сверяет ordered child metadata с canonical manifest при commit. Старые runs без
`sources` остаются читаемыми.

Операторский экран перечисляет все attempts, их тип, digest и результат. Partial
success показывает найденные leads и одновременно ошибку конкретного source;
общий technical scope остаётся `UNKNOWN` даже при нескольких official pages.

Evidence: Dell official Technical Guide URL сверён 2026-09-20; synthetic PDF,
multi-source, partial/all-error и exact-source persistence покрыты тестами.
Full no-DB pytest — 884 passed; domain doctest — 9 passed; Ruff и mypy (65
source files) — passed; web ESLint, `tsc --noEmit` и production build — passed.
Alembic имеет один head `20260920_03`, offline SQL содержит child table, RLS,
digest constraint и immutable trigger. SQL integration добавлен, но локально
пропущен без `DATABASE_URL`.

## S85 — независимый requirement-set review и exact case binding UI (2026-09-20)

Владелец: Codex (основной агент). Owned files: requirement-set API client/BFF,
новые UI routes `/requirement-set-review` и `/requirement-set-binding`, role
tests, ADR-0032 и статусная документация. Зависимости: S81–S82. Acceptance:
reviewer открывает только explicit `set_id`, видит все строки и exact proposal
digest, не получает выбранный `PASS` по умолчанию и не может принять собственный
proposal; operator после persisted terminal `PASS` связывает exact proposal и
decision digests с явными `case_id + version`; browser не получает bearer token,
а reviewer и operator credentials не смешиваются в одном server action.

Реализован отдельный reviewer route с dedicated server-only
`PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN` без fallback. Он показывает source
document/digest, declared scope, preparer, все entries, provenance, typed
нормализацию и manual ordinals. Assessment и terminal status начинаются пустыми;
перед decision action заново читает set и сравнивает proposal digest. Уже
сохранённое решение доступно только read-only.

Operator route использует обычный `PROCUREMENT_API_TOKEN`, открывает только
explicit set ID и показывает binding form исключительно для persisted `PASS`.
Перед POST action повторно сверяет exact proposal/decision digests. Case ID и
версия вводятся явно; latest selection отсутствует. UI прямо сообщает, что
reviewer `PASS` не закрывает `MANUAL_REVIEW_REQUIRED` и не подтверждает товар,
BOM или КП. Схема БД и API не менялись; Alembic head остаётся `20260920_03`.

Evidence: full no-DB pytest — 884 passed; domain doctest — 9 passed; Ruff и
mypy (65 source files) — passed; web ESLint, `tsc --noEmit` и production build —
passed. Alembic имеет один head `20260920_03`. PostgreSQL integration не
запускался без `DATABASE_URL`; S85 не меняет схему хранения.

## S86 — exact server BOM и коммерческое предложение (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый доменный контракт
`documents/server_offer.py`, PostgreSQL table/repository и миграция
`20260920_04`, FastAPI routes, operator BFF `/server-offer-proposal`, sourcing
navigation, тесты, ADR-0033 и статусная документация. Зависимости: S80–S85 и
immutable `SUPPLIER_QUOTE` document. Acceptance: proposal относится к exact case
version, requirement-set binding, sourcing run/lead и КП bytes; все BOM/quote
facts имеют provenance; деньги считаются Decimal; stale/cross-bound references
отклоняются; operator не может присвоить technical `PASS`.

Реализован `server-offer-proposal-v1`: 1–500 contiguous BOM lines с typed part
kind, manufacturer/SKU/description, Decimal quantity, optional itemized prices и
locator; коммерческие условия содержат supplier/quote identity, RUB amount без
НДС, НДС, timezone-aware validity, scope, availability, delivery, payment и
locator. При полностью заполненных line totals их сумма обязана совпасть с общей
суммой. Lump-sum КП не получает выдуманных цен строк.

API принимает только exact references и operator-entered facts. Repository сам
перечитывает PASS requirement binding, требует sourcing run для того же binding,
находит lead в persisted shortlist и проверяет exact документ роли
`SUPPLIER_QUOTE`. Lead snapshot, offer ID, actor/time, status и digest назначает
сервер. Proposal всегда `UNKNOWN / PENDING_REVIEW`; это ещё не соответствие,
полное КП для экономики или разрешение участия.

Миграция добавляет tenant-scoped append-only table с composite FK, JSON/column
identity checks, RLS/FORCE RLS, immutable trigger, audit и idempotency receipt.
UI доступен из конкретного sourcing lead и показывает offer ID/digest после
сохранения. Следующий ограниченный срез — независимая comparison matrix всех
reviewed requirements против exact BOM/КП и terminal decision по proposal digest.

Evidence: full no-DB pytest — 890 passed; domain doctest — 9 passed; Ruff и
mypy (66 source files) — passed; web ESLint, `tsc --noEmit` и production build —
passed. Alembic имеет один head `20260920_04`; offline SQL содержит table,
RLS/FORCE RLS и immutable trigger. Расширенный PostgreSQL integration test
добавлен и локально пропущен без `DATABASE_URL`.
## S87 — independent exact review server offer (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый доменный review-контракт,
append-only decision table и migration `20260920_05`, reviewer API/BFF
`/server-offer-review`, тесты, ADR-0034 и статусная документация. Зависимости:
S81, S85 и S86. Acceptance: reviewer видит один exact requirement set и
BOM/КП вместе, решает каждую source row как `PASS | FAIL | UNKNOWN` с offer
evidence; общий status вычисляет сервер; любой подтверждённый FAIL блокирует;
PASS требует полного покрытия, полного BOM и действующего полного КП; reviewer
не является автором proposal, latest selection отсутствует.

Реализован `server-offer-review-decision-v1`. Каждая известная построчная оценка
содержит typed refs на одну или несколько BOM lines либо commercial terms.
Сервер проверяет ordinals `1..N`, существование ссылок, exact proposal и оба
requirement-set digest. Истёкшее или явно неполное КП даёт FAIL; незаполненные
условия и unresolved assessments остаются UNKNOWN. Одно terminal decision,
audit event и idempotency receipt записываются атомарно под tenant RLS; update и
delete запрещены immutable trigger.

Reviewer UI использует отдельный server-only
`PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN`, повторно читает evidence перед POST и
не передаёт итоговый status. Сохранённое решение показывается read-only. Этот
review ещё не создаёт три экономических сценария и сам по себе не разрешает
`PARTICIPATE`.

Evidence: full no-DB pytest — 899 passed; domain doctest — 9 passed; Ruff и
mypy (67 source files) — passed; web ESLint, TypeScript production build —
passed. Alembic имеет один head `20260920_05`; offline SQL содержит новую
таблицу, RLS/FORCE RLS и immutable trigger. Расширенный PostgreSQL integration
test добавлен и локально пропущен без `DATABASE_URL`.
## S88 — complete economics из PASS server offer (2026-09-20)

Владелец: Codex (основной агент). Owned files: новый economics package contract,
append-only table и migration `20260920_06`, operator API/BFF
`/server-offer-economics`, тесты, ADR-0035 и статусная документация. Зависимости:
S86–S87 и существующий Decimal/ScenarioSet домен. Acceptance: только terminal
PASS review той же case version допускается как источник goods/НДС; operator
явно заполняет каждую статью и допущения во всех `base`, `realistic`,
`conservative`; сервер проверяет полноту и digests; package не создаёт
`PARTICIPATE`.

Реализован `server-offer-economics-package-v1`. Goods и ставка НДС копируются
сервером из действующего полного КП, contract revenue ограничена exact НМЦК.
Все 17 остальных статей обязательны в каждом сценарии, поэтому пропуск не
превращается в ноль. Сценарии принимаются только в порядке base → realistic →
conservative и получают явные assumptions. Package связывает case input,
proposal, review decision и source document digests.

Одна append-only запись на case version защищена tenant RLS/FORCE RLS и
immutable trigger; package, audit и idempotency receipt пишутся атомарно.
Operator UI повторно читает exact evidence перед commit. Результат имеет
`scenario_status=COMPLETE`, но `recommendation_status=UNKNOWN`: новая case
version и recommendation остаются следующим отдельным срезом.

Evidence: full no-DB pytest — 905 passed; domain doctest — 9 passed; Ruff и
mypy (68 source files) — passed; web ESLint, TypeScript и production build —
passed. Alembic имеет один head `20260920_06`; offline SQL содержит package
table, RLS/FORCE RLS и immutable trigger. PostgreSQL integration расширен и
локально пропущен без `DATABASE_URL`.

## S89 — controlled next case version из exact economics (2026-09-20)

Владелец: Codex (основной агент). Owned files: server-side case materializer,
repository/API command, operator UI на `/server-offer-economics`, тесты,
ADR-0036 и статусная документация. Зависимости: S87–S88 и существующий
append-only `case_versions`. Acceptance: browser передаёт только exact package
identity; сервер переносит reviewed КП и complete scenarios в версию `N+1`;
technical PASS имеет provenance; остальные hard gates не выводятся из offer;
команда не создаёт evaluation или `PARTICIPATE`.

Реализован server-owned materializer. Он повторно сверяет case input, offer,
review и package digests, создаёт selected quote из commercial terms и копирует
ровно три сценария. Partial assessment содержит единственный technical PASS с
evidence из row-level review. Legal, participant, company-policy, logistics и
document checks отсутствуют, поэтому существующий engine возвращает
`NEEDS_ANALYSIS`.

POST materialization защищён ролью OPERATOR, strict JSON, exact package digest,
idempotency и конфликтом существующей следующей версии. Case version, audit
event и receipt пишутся одной транзакцией под tenant scope. UI перечитывает
package перед POST и не принимает assessment/recommendation. Новая migration не
нужна; Alembic head остаётся `20260920_06`.

Evidence: full pytest — 909 passed, 100 environment/PostgreSQL tests skipped без
`DATABASE_URL`; domain doctest — 9 passed; Ruff и mypy (69 source files) —
passed; web ESLint, TypeScript и production build — passed. Alembic имеет один
head `20260920_06`, offline upgrade SQL строится. SQL integration покрывает
tenant isolation, exact package identity, atomic version creation, idempotent
replay и `NEEDS_ANALYSIS`, но локально пропущен без PostgreSQL connection.

## S90 — exact assessment оставшихся hard gates (2026-09-20)

Владелец: Codex (основной агент). Owned files: hard-gate assessment contract,
repository/API command, operator BFF `/hard-gate-assessment`, tests, ADR-0037 и
status docs. Зависимости: S63 exact document evidence и S89 controlled case
materialization. Acceptance: source version восстанавливается из exact S89
lineage; caller не меняет technical и DOCUMENT gates; четыре остальных gate
решаются явно с persisted document SHA-256 для PASS/FAIL; новая версия и audit
атомарны; evaluation остаётся отдельной командой.

Реализован server-owned переход `N → N+1`. Repository повторно читает S89 audit,
economics package и offer review, реконструирует source snapshot и только затем
переносит technical PASS. DOCUMENT выводится из exact terminal document-set
binding прежним fail-closed projector. LEGAL, PARTICIPANT, COMPANY_POLICY и
LOGISTICS принимаются ровно по одному разу; известный verdict без tenant-visible
document bytes и совпадающего digest отклоняется. UNKNOWN допускается без
evidence и остаётся блокирующим для PARTICIPATE.

API использует strict JSON, OPERATOR role, source input digest, exact binding
digests и idempotency. UI перечитывает source evidence перед POST, не предлагает
technical/DOCUMENT verdict и после успеха направляет к отдельной evaluation на
главном экране. Schema migration не нужна; Alembic head остаётся
`20260920_06`.

Evidence: full pytest — 914 passed, 100 environment/PostgreSQL tests skipped без
`DATABASE_URL`; domain doctest — 9 passed; Ruff и mypy (70 source files) —
passed; web ESLint, TypeScript и production build — passed. Alembic имеет один
head `20260920_06`, offline upgrade SQL строится. Расширенный SQL integration
проверяет exact S89 lineage, server-derived DOCUMENT, tenant isolation и
idempotent replay, но локально пропущен без PostgreSQL connection.

## S91 — обязательный clean PostgreSQL acceptance (2026-09-20)

Владелец: Codex (основной агент). Owned files: PostgreSQL verification harness,
storage reconstruction для timezone-aware AI transfer events, полный S90 SQL
flow test и runbook/status docs. Зависимости: S2–S90. Acceptance: новая БД
проходит все миграции до единственного head; owner и runtime разделены; весь
SQL-набор запускается с `--require-postgres` без skip; кластер после gate
удаляется; exact JSON digests воспроизводимы при не-UTC timezone PostgreSQL.

`scripts/verify-postgres.ps1` теперь включает все девять SQL suites — 99 tests,
включая evidence binding, case-from-evidence, reviewed requirement set и цепочку
S86–S90. Docker PostgreSQL 16 остаётся backend по умолчанию. Добавлен явный
`-Backend Local`: gate находит PostgreSQL 16+ binaries, создаёт отдельный
password-authenticated кластер в `%TEMP%`, случайные owner/runtime credentials,
чистую БД и гарантированно останавливает/удаляет её. Обычная установленная служба
и её данные не используются.

Реальный прогон на PostgreSQL 18 с timezone `Europe/Moscow` выявил скрытую
зависимость SHA-256 reconstruction от session timezone. Loader теперь
восстанавливает content-addressed admission/claim/receipt по exact timestamp из
immutable JSON и независимо сверяет тот же момент с typed SQL column. S90
integration flow также исправлен: DOCUMENT получается из отдельной настоящей
document-set lineage, а не из requirement-set binding; unresolved completeness
остаётся `UNKNOWN`.

Evidence: чистый PostgreSQL 18 применил миграции `20260908_01 → 20260920_06`;
99/99 mandatory SQL integration tests прошли без skip; ephemeral cluster был
остановлен и удалён. Target Docker backend по-прежнему требует PostgreSQL 16;
local backend подтвердил forward compatibility и timezone independence на 18.
Обычный pytest — 914 passed, 100 environment/SQL/OCR tests skipped; domain
doctest — 9 passed; Ruff, strict mypy по 70 source files, `uv lock --check` и
PowerShell syntax check прошли.

## S92 — independent participation decision (2026-09-21)

Владелец: Codex (основной агент). Owned files: participation-decision domain,
tenant-scoped table и migration `20260921_01`, repository/API, отдельный BFF
`/participation-approval`, tests, ADR-0038 и status docs. Зависимости: S90
complete hard gates, persisted evaluation и S91 clean PostgreSQL gate.
Acceptance: только exact persisted `PARTICIPATE` evaluation; отдельная роль
`PARTICIPATION_APPROVER`; approver отличается от evaluator; перед `APPROVED`
сервер пересчитывает тот же case на текущее время; decision, audit и receipt
атомарны и tenant-scoped; внутреннее решение не разрешает внешнее действие.

Реализован `participation-evaluation-evidence-v1` и terminal
`participation-decision-v1`. Evidence повторно восстанавливается из immutable
case, evaluation и её единственного audit event. `APPROVED` допустим только при
исходной и текущей рекомендации `PARTICIPATE`; self approval и stale positive
evaluation отклоняются. `REJECTED` сохраняет текущий пересчёт и явное основание.

Новая append-only таблица имеет composite FK на evaluation, одну terminal
запись на evaluation, JSON/column identity checks, RLS/FORCE RLS и immutable
trigger. UI использует только server-only
`PROCUREMENT_PARTICIPATION_APPROVER_TOKEN`, повторно читает exact digest перед
POST и показывает сохранённое решение read-only. Каждый payload фиксирует
`external_action_authorized=false`; подача заявки остаётся отдельным будущим
exact-payload workflow.

Evidence: clean PostgreSQL 18 (`Europe/Moscow`) применил миграции до единственного
head `20260921_01`; 101/101 mandatory SQL tests прошли без skip, после чего
ephemeral cluster был остановлен и удалён. Обычный pytest — 919 passed и 102
environment/SQL/OCR tests skipped; doctest — 10 passed; Ruff, strict mypy по 71
source file и `uv lock --check` прошли. Web ESLint, TypeScript и production
Next.js build прошли; dynamic route `/participation-approval` вошёл в build.

## S93 — exact application package proposal (2026-09-21)

Владелец: Codex (основной агент). Owned files: `documents/application_package.py`,
роль документа `APPLICATION_ATTACHMENT`, table/repository и migration
`20260921_02`, API, operator BFF `/application-package`, тесты, ADR-0039 и
status docs. Зависимости: S92 exact APPROVED participation, S90 complete case и
immutable document storage. Acceptance: пакет собирается только из exact
APPROVED decision, tenant-visible source/attachment SHA-256, актуального
`PARTICIPATE`, действующего deadline и цены в допустимом коридоре; одна
immutable запись, audit и receipt атомарны; результат не выдаёт право подачи.

Реализован `application-package-v1`: оператор явно перечисляет необходимые
формы/декларации/подтверждения с source locator в `TENDER_REQUIREMENTS`,
привязывает каждую заявленную строку к уже загруженному
`APPLICATION_ATTACHMENT` и задаёт Decimal-цену без НДС. Сервер проверяет exact
decision/case/evaluation, document roles/bytes/digests, полноту *заявленного*
маппинга, текущий floor и НМЦК. Он назначает actor/time и хранит текущую
рекомендацию. Полнота реальных требований закупки не выводится из ручного
списка: `coverage_status=UNKNOWN`, `review_status=PENDING_REVIEW`,
`external_action_authorized=false`.

Tenant-scoped append-only table имеет composite FK, JSON/column checks,
RLS/FORCE RLS и immutable trigger. Repository на чтении заново сверяет
документы и реконструирует пакет. OPERATOR создаёт, AUDITOR только читает.
Экран открывается по явному decision ID, повторно читает digest перед POST и
показывает terminal пакет read-only. Подписи и отправки нет. Следующий срез —
независимый review полного состава и exact package digest; отдельный
exact-payload approval потребуется до внешней подачи.

Evidence: clean PostgreSQL 18 (`Europe/Moscow`) применил миграции до
единственного head `20260921_02`; mandatory SQL gate прошёл без skip, включая
S93 atomic/replay/tenant/immutability test, после чего ephemeral cluster был
остановлен и удалён. Full pytest и domain doctest прошли; Ruff, strict mypy по
72 source files и `uv lock --check` прошли. Web ESLint, TypeScript и production
Next.js build прошли; dynamic route `/application-package` вошёл в build.

## S94 — независимый review комплекта заявки (2026-09-21)

Владелец: Codex (основной агент). Owned files: новый
`documents/application_review.py`, роль `APPLICATION_REVIEWER`, append-only
table и migration `20260921_03`, repository/API, reviewer BFF
`/application-package-review`, тесты, ADR-0040 и status docs. Зависимости:
S92 APPROVED participation и S93 immutable package. Acceptance: reviewer
отличается от preparer и видит exact package digest и оригиналы связанных
документов; каждое требование и вложение получает explicit verdict; полнота
перечня и цена проверяются отдельно; сервер выводит итог из трёх состояний и
актуальных deadline/floor/PARTICIPATE; decision/audit/receipt атомарны,
tenant-scoped, без права внешней подачи.

Реализован `application-review-decision-v1`. Known row verdict требует ссылки на
exact сопоставленные файлы; `PASS` строки охватывает все её файлы. Inventory
assessment содержит IDs проверенных исходных документов заказчика и основание;
`CONFIRMED_COMPLETE` требует каждого source ID, указанного в пакете. Reviewer
также решает каждый файл и цену. Сервер пересчитывает case на время review:
известный FAIL/пропуск/отклонённая цена/закрытый deadline блокирует, `PASS`
требует всех позитивных оценок, текущего `PARTICIPATE` и цены в коридоре.
Неустановленное остаётся `UNKNOWN`. Package и review неизменяемы;
`external_action_authorized=false` при любом verdict.

Отдельный server-only reviewer token без operator fallback открывает пакет по
явному ID. Экран показывает provenance и извлечённые блоки; защищённый маршрут
даёт скачать только оригиналы с exact ID/SHA-256 и ролью внутри данного
пакета. Ни один verdict не выбран заранее. Следующий срез — отдельный
exact-payload approval с ограниченным сроком и позднее контролируемая подача;
S94 ничего не подписывает и не отправляет.

Evidence: clean PostgreSQL 18 (`Europe/Moscow`) применил миграции до
единственного head `20260921_03`; обязательный SQL gate прошёл без skip,
включая S94 self-review rejection, tenant isolation, replay, audit и immutable
trigger; ephemeral cluster остановлен и удалён. Full pytest, doctest (10),
Ruff, strict mypy по 73 source files и `uv lock --check` прошли. Web ESLint,
TypeScript и production build прошли; routes `/application-package-review` и
защищённая загрузка оригинала вошли в build.

## S95 — exact команда подачи и независимое краткосрочное подтверждение (2026-09-21)

Владелец: Codex (основной агент). Owned files: новый
`documents/application_submission.py`, роль `APPLICATION_SUBMISSION_APPROVER`,
append-only таблицы и migration `20260921_04`, repository/API, operator BFF
`/application-submission`, approver BFF `/application-submission-approval`, тесты,
ADR-0041 и status docs. Зависимость: S94 terminal `PASS` review. Acceptance:
сервер сам строит exact payload из проверенного пакета с адресом, ценой и
каждым файлом; независимый actor подтверждает точный action ID/SHA-256;
approval истекает через 15 минут, при deadline или expiry КП; решение, audit и receipt
атомарны и tenant-scoped. Подпись и отправка не выполняются.

Реализован `application-submission-intent-v1` поверх `ActionRequest` типа
`SUBMIT_APPLICATION`: destination, case/version, package/review SHA-256,
Decimal-цена строкой, валюта и упорядоченные ID/SHA-256/имена/MIME файлов.
Сервер повторно проверяет `PARTICIPATE`, deadline и текущий floor при
подготовке и положительном решении. `application-submission-approval-v1`
фиксирует `APPROVED | REJECTED`, reason, actor/time, exact `Approval` и
decision digest. Автор пакета, reviewer и автор команды не могут согласовать
её сами. Изменённый payload или истёкший срок не проходят чистую проверку
действительности. Одна команда на пакет и одно terminal решение неизменяемы.

Оператор и согласующий используют отдельные BFF/token; согласующий видит
полный payload и его digest. Следующий срез — контролируемый исполнитель с
атомарным одноразовым потреблением approval, проверкой реальных файлов и
platform wire payload. Перед фактической подачей также нужны персональная
аутентификация согласующего с MFA и доверенные адреса площадок. При
трансформации байтов площадки требуется новое exact-payload approval. S95 не
является подписью или фактом подачи.

Evidence: clean PostgreSQL 18 (`Europe/Moscow`) применил миграции до
единственного head `20260921_04`; обязательный SQL gate прошёл без skip,
включая S95 exact/replay/tenant/self-approval/immutability test, затем кластер
остановлен и удалён. Full pytest, Ruff, strict mypy по 74 source files и
`uv lock --check` прошли. Web ESLint, TypeScript и production build прошли;
dynamic routes `/application-submission` и `/application-submission-approval`
вошли в build.

## S96 — одноразовый admission exact заявки без отправки (2026-09-21)

Владелец: Codex (основной агент). Owned files: новый
`documents/application_submission_execution.py`, роль
`APPLICATION_SUBMISSION_EXECUTOR`, таблица и migration `20260921_05`,
repository/API, executor BFF `/application-submission-execution`, тесты,
ADR-0042 и status docs. Зависимости: S93 immutable attachments, S94 `PASS`
review и S95 exact approval. Acceptance: только отдельный executor один раз
резервирует approved action в действующем окне; сервер повторно проверяет
гейты и SHA-256 реальных байтов каждого файла; admission/audit/receipt атомарны
и tenant-scoped; результат явно сообщает, что отправки не было.

Реализован `application-submission-admission-v1`: original byte size и SHA-256
каждого attachment входят в digest неизменяемого claim. Получение admission
реконструирует его из exact S93–S95 evidence и заново сверяет исходные байты.
Второй claim блокируется даже с новым idempotency key; exact replay возвращает
первую запись. Статус только `ADMITTED_NO_DISPATCH`, признака успешной подачи
нет. UI показывает отличие admission от внешнего действия.

Следующий срез — адаптер конкретной ЭТП и фактический dispatch с отдельным
exact approval wire payload, правовой проверкой, allowlist и персональной MFA;
перед сетевой попыткой нужно снова проверить окно, deadline, цену и байты,
затем записать receipt исхода. Истёкший после admission approval не допускает
отправку, а claim не освобождается.

Evidence: clean PostgreSQL 18 (`Europe/Moscow`) применил миграции до
единственного head `20260921_05`; обязательный SQL gate прошёл без skip,
включая S96 exact bytes/replay/tenant/self-claim/immutability test, затем
кластер остановлен и удалён. Full pytest, Ruff, strict mypy по 75 source
files и `uv lock --check` прошли. Web ESLint, TypeScript и production build
прошли; dynamic route `/application-submission-execution` вошёл в build.

## S97 — проверяемый архив для ручной передачи (2026-09-21)

Владелец: Codex (основной агент). Owned files: новый
`documents/application_handoff.py`, защищённый API GET
`/submission/handoff`, executor BFF download route/экран, тесты,
ADR-0043 и status docs. Зависимости: S93 immutable оригиналы, S94 PASS review,
S95 exact approval, S96 admission record. Acceptance: при действующем approval
сервер строит ограниченный ZIP из всех утверждённых оригиналов с проверенными
SHA-256 и canonical manifest; другой tenant/роль, изменённый файл, истёкший
approval или уже существующий admission блокируют выдачу. Подачи на ЭТП нет.

Реализован `application-handoff-v1`: манифест связывает package/action/approval
digest, адрес, Decimal-цену строкой, срок approval и упорядоченные файлы.
На выдаче заново вычисляются deadline, `PARTICIPATE`, floor и хеши байтов;
архив ограничен 100 MiB. Исполнитель может скачать ZIP до admission; интерфейс
явно отделяет ручную передачу от отправки и квитанции площадки. Архив не
потребляет approval и не фиксирует результат действия человека. Проверка
отсутствия admission не атомарна с его созданием, поэтому будущий dispatch
обязан разделить эти ветви транзакционно.

Следующий срез реального dispatch зависит от выбранной ЭТП, официального
контракта интеграции и правовой проверки; также нужны персональная MFA,
allowlist, exact approval wire payload и receipt. Эти входные данные пока не
заданы, поэтому S97 не объявляет заявку поданной.

Evidence: unit/API-тесты S97 прошли, включая tenant/role, целые и изменённые
байты, истечение approval и существующий admission. Full pytest прошёл
(интеграционные SQL-тесты пропущены без PostgreSQL; схема не менялась).
Ruff, strict mypy по 76 source files, web ESLint и production build прошли;
dynamic route `/application-submission-execution/handoff` вошёл в build.

