# Хранение и API — S2

Статус: **первый серверный срез завершён 2026-09-08**.

## Цель

Сохранить immutable-версии `ProcurementCase`, получить их через аутентифицированный
API и воспроизводимо записать оценку вместе с audit. В S2 нет отправки RFQ,
заявки, ставки или другого внешнего действия.

## Модель доверия

Bearer-ключ определяет `company_id` и `actor_id` на сервере. Заголовок или
query-параметр с tenant не является аутентификацией. Тело кейса сверяется с
tenant ключа; запрос чужого идентификатора возвращает тот же `404`, что
отсутствующий объект.

PostgreSQL применяет RLS по transaction-local `app.company_id`. Репозиторий
ставит tenant-контекст в каждой транзакции. Runtime-роль `procurement_app` не
владеет таблицами и не имеет `BYPASSRLS`; миграции выполняет отдельный владелец.
Проверка только в Python недостаточна.

Ключ хранится как SHA-256 digest, исходное значение БД не хранит и API не
логирует. Для production потребуется внешний secret manager и процедура ротации;
локальный bootstrap S2 предназначен только для разработки.

## Локальная БД

1. Скопировать `.env.example` в `.env` и задать два разных локальных пароля.
2. Запустить `docker compose up -d postgres`.
3. Выполнить миграции через `DATABASE_ADMIN_URL`.
4. Запускать приложение и интеграционные тесты через runtime `DATABASE_URL`.

Compose публикует PostgreSQL только на `127.0.0.1`. Инициализационный скрипт
создаёт runtime-роль только при первом создании volume. Изменение пароля в `.env`
после этого не меняет роль автоматически. `.env` исключён из Git.

Владельческое подключение обходит RLS и не используется приложением. Успешные
тесты через owner URL не являются доказательством tenant isolation.

Команды после заполнения `.env`:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Bootstrap выводит новый bearer secret один раз. Его нельзя помещать в Git,
документацию, URL или тело кейса. `DATABASE_ADMIN_URL` нужен миграции/bootstrap,
а сервер использует только `DATABASE_URL` runtime-роли.

## Контракт API

- `GET /health` — проверка процесса без раскрытия конфигурации;
- `POST /v1/cases` — immutable-сохранение версии кейса;
- `GET /v1/cases/{case_id}/versions/{version}` — точная версия своего tenant;
- `GET /v1/cases` — ограниченный список с cursor;
- `POST /v1/cases/{case_id}/versions/{version}/evaluations` — сервер загружает
  снимок, рассчитывает рекомендацию на timezone-aware момент и атомарно пишет audit.

Записи требуют `Idempotency-Key`. Повтор с тем же ключом и payload возвращает
исходный результат; другой payload — конфликт. Клиент не передаёт готовую
рекомендацию, actor или company для audit.

## Проверка и границы

Обычный локальный запуск остаётся необязательным: без двух URL PostgreSQL-тесты
помечаются как пропущенные. Это удобно для быстрого unit-test цикла, но не является
доказательством работоспособности хранения:

```powershell
uv run pytest tests/integration -q
```

Обязательный gate поднимает отдельный PostgreSQL 16, генерирует временные пароли,
создаёт owner/runtime-роли, применяет все миграции с нуля и удаляет изолированный
volume после проверки:

```powershell
./scripts/verify-postgres.ps1
```

Если Docker уже использует порт `55432`, нужно передать свободный локальный порт:

```powershell
./scripts/verify-postgres.ps1 -PostgresPort 55433
```

На Windows gate также умеет создать временный кластер из локально установленных
PostgreSQL 16+ binaries. Он не использует действующую службу или её данные,
настраивает password authentication на `127.0.0.1`, а после проверки останавливает
процесс и удаляет только созданный каталог `%TEMP%\vibe-seller-postgres-gate-*`:

```powershell
./scripts/verify-postgres.ps1 -Backend Local
```

Если binaries не находятся через `PATH` или `Program Files\PostgreSQL`, каталог
`bin` задаётся явно через `-PostgresBin`. Docker остаётся backend по умолчанию и
проверяет целевой PostgreSQL 16; local backend сверяет фактически найденную major
version. Оба режима выполняют один и тот же полный набор из 99 SQL integration
tests на чистой схеме.

Gate запускает PostgreSQL-набор с `--require-postgres`: отсутствие
`DATABASE_ADMIN_URL`/`DATABASE_URL`, недоступная БД или любой пропущенный тест
завершают проверку ошибкой. Отдельный opt-in тест реального PaddleOCR в этот gate
не входит. В CI тот же набор работает с PostgreSQL 16 service container; миграции
выполняет owner, а приложение и проверки хранения используют `procurement_app` без
`SUPERUSER`, `CREATEDB`, `CREATEROLE`, `INHERIT`, `BYPASSRLS` и владения таблицами.

Набор проверяет RLS и guessed-ID isolation, immutable
UPDATE/DELETE, отсутствие чтения digest runtime-ролью, глобальная bearer auth,
конкурентная идемпотентность, cursor, точный JSON/Decimal roundtrip, атомарная
evaluation + audit, сквозные HTTP-сценарии, tenant-scoped document/model→brand
workflows и полную цепочку reviewed requirement set → sourcing → offer →
economics → новые case versions → hard-gate assessment.

API в S2 не доказывает production security: TLS, rate limits, ротация ключей,
централизованные логи и deployment secrets относятся к следующим операционным
срезам. Снимок кейса целиком immutable; отдельные independently edited версии
профиля и КП появятся только вместе с самостоятельными workflow их изменения.

## Tenant-scoped document search (S4, 2026-09-15)

- `POST /v1/documents/{document_id}/search-indexes` создаёт append-only версию
  поискового evidence после повторной сверки immutable source bytes/extraction;
- `GET /v1/document-search?query=...&limit=50` ищет только по последней версии
  каждого документа текущего bearer tenant;
- ответ различает `TITLE`, `FILENAME`, `NATIVE_TEXT`, `VISION_TAG` и сохраняет
  locator/confidence/digests; исходные bytes не возвращаются;
- запись индекса, audit и idempotency receipt атомарны; другая нагрузка с тем же
  ключом получает `409`;
- миграция `20260915_02` добавляет RLS/FORCE RLS, append-only trigger и проверки
  согласованности JSON entry с tenant/document/SHA-256 колонками.

Полный формат и граница доверия vision-тегов описаны в
[контракте S4](../documents/19-document-pipeline.md#persisted-search-index-и-api-двадцать-третий-срез-s4-2026-09-15)
и [ADR-0013](../adr/0013-immutable-document-search-index.md).

## Tenant-scoped model→brand catalog (S4, 2026-09-16)

- `GET /v1/model-brand-catalogs/latest?effective_at=...` возвращает последнюю
  доступную версию только текущего tenant;
- новый immutable catalog публикуется только атомарным `APPROVED`-решением по
  proposal; tenant, reviewer и время создания выводятся сервером;
- `GET /v1/document-search` использует этот каталог на возвращённый
  timezone-aware `effective_at` и может вернуть `MODEL_BRAND_CATALOG` provenance;
- каталог, review decision, audit и idempotency receipt атомарны; exact replay
  стабилен, изменённая нагрузка с тем же ключом получает `409`;
- миграция `20260916_01` добавляет RLS/FORCE RLS, append-only trigger и typed JSON
  checks. Runtime-роль имеет только `SELECT, INSERT`.

Контракт immutable reviewed catalog — в
[ADR-0015](../adr/0015-immutable-reviewed-model-brand-catalog.md); замыкание на
persisted source bytes описано следующим разделом.

## Model→brand source artifacts (S4, 2026-09-16)

- `POST /v1/model-brand-source-artifacts` сохраняет bounded official PDF bytes,
  HTTPS URL/title, server times и SHA-256; artifact, audit и receipt атомарны;
- `GET /v1/model-brand-source-artifacts/{artifact_id}` возвращает metadata без
  bytes и не различает отсутствующий/чужой ID;
- persisted catalog entries требуют `source_artifact_id`; repository повторно
  хеширует bytes и сверяет title/URL/digest/retrieval time перед insert;
- миграция `20260916_02` применяет RLS/FORCE RLS, runtime `SELECT/INSERT` и
  append-only trigger.

Upload не скачивает URL автоматически. Полный trust boundary — в
[ADR-0016](../adr/0016-immutable-model-brand-source-artifacts.md).

## Role-aware model→brand review (S4, 2026-09-16)

- API keys имеют `OPERATOR` или `MODEL_BRAND_REVIEWER`; bootstrap поддерживает
  `--access-role`, а роль извлекается только authentication function;
- `POST /v1/model-brand-reviews` создаёт проверенный immutable `DRAFT`;
- `GET /v1/model-brand-reviews` показывает tenant-scoped derived states;
- `POST /v1/model-brand-reviews/{proposal_id}/decision` разрешён reviewer и
  атомарно публикует approved catalog либо фиксирует rejection без catalog;
- self-approval, второе решение и изменение idempotent payload запрещены;
- миграция `20260916_03` добавляет append-only proposal/decision с RLS/FORCE RLS.

Публичного прямого пути публикации каталога нет: единственный write-path проходит
через proposal и независимое решение reviewer. Полный контракт —
[ADR-0017](../adr/0017-role-aware-model-brand-review.md).

## Persisted document completeness review (S4, 2026-09-16)

- API keys дополнительно поддерживают отдельную роль `COMPLETENESS_REVIEWER`;
- `POST /v1/documents/{document_id}/completeness-reviews` доступен оператору и
  создаёт server-derived immutable evidence snapshot, не принимая mapping клиента;
- `GET /v1/completeness-reviews` и точечный GET возвращают только review текущего
  tenant, без source bytes;
- `POST /v1/completeness-reviews/{review_id}/decision` принимает exact
  `evidence_sha256`, status/scope/reason и решения по индексам unmapped-блоков;
- решение reviewer, audit и idempotency receipt атомарны; self-review, второе
  решение, stale evidence и изменённый replay запрещены;
- snapshot и decision append-only, защищены RLS/FORCE RLS и composite tenant FK.

Первый срез поддерживает только один persisted native-документ ТЗ. OCR, ZIP,
embedded media, multi-document completeness и case ingestion не получают
неявный положительный статус. Контракт — в
[ADR-0021](../adr/0021-persisted-document-completeness-review.md).

## Persisted AI requirement review (S4, 2026-09-17)

- миграция `20260917_01` добавляет `document_ai_requirement_runs` и
  `document_ai_requirement_review_decisions` с RLS/FORCE RLS, composite
  source/evidence FK и запретом `UPDATE/DELETE`;
- repository импортирует v1/v2 report только как `IMPORTED_REPORT`, повторно
  хеширует stored source bytes и связывает exact extraction/text/provenance;
- create replay actor-bound и возвращает исходный snapshot без решения,
  появившегося позднее;
- terminal review требует другого actor, exact evidence digest и ровно одно
  решение по каждому кандидату; incomplete run сохраняется для аудита, но не
  может получить terminal review;
- import/review, audit event и idempotency receipt фиксируются одной транзакцией;
- review не меняет completeness `UNKNOWN` и не публикует executable domain data.

Публичный provider-run endpoint в этом срезе отсутствует. До него должны быть
утверждены exact-payload approval и retention/access policy полного
`response_content`. Контракт —
[ADR-0023](../adr/0023-persisted-ai-requirement-review.md).

Sanitized API публикует только уже persisted run:

- `GET /v1/ai-requirement-runs` — metadata/counts для оператора и reviewer;
- `GET /v1/ai-requirement-runs/{run_id}` — reviewer-only candidates/evidence;
- `POST /v1/ai-requirement-runs/{run_id}/decision` — reviewer-only terminal
  decision по exact digest.

Все три ответа имеют `Cache-Control: no-store`. Ни один из них не содержит
полный extraction, chunks, `response_content`, provider response ID или
`authorization_reference`.

Import-only bridge `POST /v1/documents/{document_id}/ai-requirement-runs`
доступен только `OPERATOR` и принимает exact v1/v2 JSON report размером до
20 МиБ. Тело читается потоково до parsing; неверный media type, duplicate keys,
non-finite values, неизвестные поля и любая молчаливая нормализация запрещены.
Tenant, actor, run ID и время всегда server-owned. Repository повторно проверяет
stored source bytes/extraction/evidence и атомарно пишет run, audit и receipt.
Успешный ответ — только `AiRequirementReviewSummary` с `Cache-Control: no-store`;
import не вызывает внешнего провайдера и не выдаёт новое разрешение на передачу.

## Persisted AI transfer request and approval (S4, 2026-09-17)

- миграция `20260917_04` добавляет append-only `ai_transfer_requests`, ordered
  `ai_transfer_chunks` и `ai_transfer_approvals` с RLS/FORCE RLS;
- request создаёт только `OPERATOR`; endpoint принимает лишь model, а tenant,
  source/extraction binding, endpoint, policy, exact canonical bytes и digests
  выводит и повторно проверяет сервер;
- exact GET не имеет list/latest semantics и доступен только actor-владельцу
  request либо отдельному `AI_TRANSFER_APPROVER`;
- approval принимает только exact request digest, требует независимого actor и
  действует ровно 15 минут; self-approval, predating, stale/tampered request и
  повторное решение запрещены;
- deferred database triggers проверяют полный ordered chunk projection, а
  composite foreign keys не позволяют связать другой tenant/source/request;
- ответы имеют `Cache-Control: no-store`, audit/idempotency receipts записываются
  атомарно, JSON ограничен 16 КиБ и разбирается fail-closed.

Это request/approval-only граница: API ещё не создаёт execution run, не потребляет
approval и не вызывает OpenRouter. Политика и следующий durable execution
контракт зафиксированы в
[ADR-0026](../adr/0026-exact-ai-transfer-approval-and-response-retention.md).

## AI transfer execution admission and first claim (S4, 2026-09-17)

- миграция `20260917_05` добавляет immutable
  `ai_transfer_execution_admissions` и `ai_transfer_dispatch_claims`;
- `POST /v1/ai-transfer-requests/{transfer_id}/execution-admissions` атомарно
  потребляет approval и доступен только `OPERATOR`, подготовившему exact request;
- `GET /v1/ai-transfer-executions/{execution_id}` возвращает `no-store` metadata
  владельцу admission либо `AI_TRANSFER_APPROVER`, но не request body;
- admission уникален для transfer независимо от idempotency key; exact replay
  стабилен даже после expiry и не создаёт новую authority;
- internal worker method создаёт только один permanent claim первого chunk после
  commit; claim всегда имеет `attempt=1` и `DELIVERY_UNKNOWN`;
- actual DB time проверяется после locks через `clock_timestamp()`; direct SQL
  backdating, expired approval, другой actor, ordinal 2, cross-tenant binding,
  `UPDATE/DELETE` и повторный claim отклоняются.

Public claim endpoint и сетевой вызов отсутствуют. До trusted terminal receipt
нельзя claim-ить второй chunk и нельзя объявлять admission/claim успешной
отправкой.

## Exact-byte transport and terminal dispatch receipt (S4, 2026-09-17)

- `ExactAiTransferHttpClient` принимает только повторно проверенный exact request,
  добавляет secret authorization исключительно в памяти и выполняет один вызов
  без proxy, redirects и retry;
- response читается через raw stream с жёстким byte limit; compressed, incomplete,
  timeout и oversized ответы сохраняют `DELIVERY_UNKNOWN`, а не становятся
  доказанным отказом;
- `SUCCESS` требует HTTP 200, строгий provider envelope, exact model,
  `finish_reason=stop`, валидный wire-v2 и ссылки только на block IDs текущего
  chunk;
- миграция `20260917_06` добавляет `ai_transfer_dispatch_receipts`: один
  immutable terminal receipt на exact first-chunk claim, с composite FK,
  reason-specific CHECK, RLS/FORCE RLS и exact JSON projection;
- receipt хранит только безопасные времена, статусы, counts и SHA-256. Raw body,
  assistant content, HTTP headers, API key и provider error text в нём запрещены;
- repository принимает receipt только от claiming worker, повторно сверяет
  request digest и записывает receipt вместе с audit event в одной транзакции;
- `GET /v1/ai-transfer-executions/{execution_id}` может вернуть безопасную
  receipt metadata, но public receipt POST отсутствует.

Live worker намеренно не подключён: полный bounded response сначала должен
атомарно попасть в отдельное зашифрованное 30-дневное хранилище вместе с receipt.
Существующий `OpenRouterRequirementsClient.complete_json()` не является этой
execution boundary и не должен использоваться для durable dispatch.

## Encrypted complete provider response и retention (S4, 2026-09-17)

- миграция `20260917_07` добавляет tenant-scoped
  `ai_transfer_raw_responses`, encrypted blob rows и immutable deletion receipts;
- только complete bounded attempt может атомарно записать terminal receipt,
  metadata и ciphertext; incomplete/unknown/oversized response raw не сохраняет;
- каждый blob использует случайный per-blob DEK, AES-256-GCM и отдельный nonce;
  DEK оборачивается tenant KEK через явный provider protocol. Canonical AAD,
  envelope и metadata имеют exact SHA-256; plaintext не хранится в SQL;
- exact FK и deferred projection trigger связывают raw metadata с полным
  dispatch receipt, request/response digests и byte count. RLS/FORCE RLS,
  append-only metadata и минимальные runtime grants сохраняют tenant isolation;
- `GET /v1/ai-transfer-raw-responses/{raw_response_id}` доступен только
  `AI_REQUIREMENTS_REVIEWER` и `AUDITOR`, возвращает bounded raw как
  `application/octet-stream` с `no-store`, а любой access outcome пишется в
  audit. Operator и `AI_TRANSFER_APPROVER` raw не получают;
- raw считается expired ровно через 720 UTC-часов после `received_at`.
  Cleanup сначала вставляет immutable deletion receipt, затем удаляет ciphertext
  и wrapped DEK; metadata, digests, candidates, review и audit сохраняются.
  Deferred anti-resurrection checks запрещают раннее удаление, delete без
  receipt и повторную вставку blob;
- production capture и live worker остаются disabled до production tenant KEK
  provider и проверяемых backup/WAL/restore retention evidence. Эти prerequisites
  не считаются выполненными текущим срезом.

## AI requirement materialization после capture (S49–S60, 2026-09-17–18)

Ниже объединён текущий контракт; первоначальные ограничения S49 сохранены в
датированном implementation plan как историческая запись.

- миграция `20260917_08` добавляет append-only
  `ai_transfer_requirement_materializations` и расширяет
  `document_ai_requirement_runs` точной v1/v2 формой; v2 snapshot не может быть
  сохранён без соответствующей materialization receipt;
- `POST /v1/ai-transfer-executions/{execution_id}/requirement-materializations`
  доступен только owning operator и работает только с уже captured terminal
  `SUCCESS`. Он не вызывает provider и не повторяет сетевую попытку;
- ровно один single-chunk SUCCESS с валидным wire response создаёт raw-free
  `persisted-ai-requirement-run-v2`: candidates, source provenance и SHA-256
  evidence сохраняются, но `response_content`, plaintext и ciphertext raw blob
  в reviewer queue не попадают. `completeness=UNKNOWN` сохраняется явно;
- multi-chunk после ordered per-chunk capture материализуется в raw-free
  snapshot v3; invalid candidate evidence получает append-only terminal
  `REJECTED` receipt. Это не допуск в очередь и не скрытый `UNKNOWN`;
- materialization/recovery идемпотентны; reviewer queue читает persisted v1 и v2,
  а raw provider response остаётся отдельным reviewer/auditor-only endpoint.
  Encrypted raw сохраняется ровно 30 дней (720 UTC-часов), после purge остаются
  metadata, digests, review и deletion receipt;
- CLI recovery по умолчанию выключен. `dispatch-approved-ai-transfer` делает
  один bounded coordinator step, а `materialize-ai-transfer` выбирает single/
  multi materializer по immutable `chunk_count` и не вызывает provider.
  Production capture остаётся disabled до managed KMS с rotation и проверяемых
  backup/WAL/restore retention evidence.
- Текущий evidence: `780` no-DB тестов, `90` fresh PostgreSQL 16 тестов,
  `10` doctest; mypy по 55 source-файлам, Ruff, `uv lock --check`, single
  Alembic head `20260917_12` и offline SQL прошли.

## Document-set evidence manifest (S4, 2026-09-17)

- миграция `20260917_02` добавляет append-only
  `document_set_evidence_manifests` и ordered
  `document_set_evidence_members` с RLS/FORCE RLS;
- `POST /v1/document-set-evidence-manifests` доступен только `OPERATOR`, требует
  `Idempotency-Key` и принимает явный порядок 2–10 exact
  `review_id + evidence_sha256`;
- входной JSON читается потоково до 16 КиБ; duplicate keys, non-finite values,
  лишние поля и неподходящий media type отклоняются до repository;
- tenant, actor, manifest ID и время server-owned; exact replay actor-bound;
- repository повторно проверяет review snapshots, stored source bytes и
  extraction, а aggregate logical snapshot evidence ограничивает 20 МиБ;
- exact review digest связывает полный extraction/provenance, поэтому manifest
  не дублирует его отдельным производным хешем;
- deferred DB trigger сверяет manifest JSON с ordered member rows и связывает
  source/mapper projection с exact review/evidence FK;
- точечный GET tenant-scoped; POST/GET имеют `Cache-Control: no-store`.

Ресурс всегда возвращает `UNKNOWN/MULTI_DOCUMENT_REVIEW_REQUIRED`. List/latest,
terminal decision и case ingestion отсутствуют; constituent `PASS` не считается
полнотой комплекта. Контракт —
[ADR-0024](../adr/0024-document-set-evidence-manifest.md).

## Terminal document-set completeness review (S4, 2026-09-17)

- миграция `20260917_03` добавляет append-only
  `document_set_completeness_decisions` и ordered
  `document_set_completeness_member_attestations` с RLS/FORCE RLS;
- reviewer-only `GET /v1/document-sets/{manifest_id}/completeness-evidence`
  восстанавливает exact manifest, constituent snapshots и terminal decisions;
- reviewer-only `POST /v1/document-sets/{manifest_id}/completeness-decisions`
  требует manifest digest, complete ordered attestations, inventory/cross-document
  assessments, findings, статус и actor-bound `Idempotency-Key`;
- точечный GET того же decision resource возвращает только tenant-visible
  immutable terminal decision;
- POST читает strict JSON потоково до 256 КиБ; duplicate keys, non-finite values,
  лишние поля и неподходящий media type отклоняются до repository;
- repository повторно проверяет source bytes/extraction, exact constituent
  decision digests и server findings; logical evidence ограничено 40 МиБ;
- deferred trigger сверяет число members со связанным manifest, scope, ordered
  attestation rows и exact review/evidence binding;
- все ответы имеют `Cache-Control: no-store`.

`PASS` возможен только для полностью подтверждённого exact scope без findings;
подтверждённый материальный пропуск даёт `FAIL`, а сомнение или конфликт остаются
`UNKNOWN`. Ресурс не объединяет mappings, не выбирает latest, не подключается к
case и не разрешает `PARTICIPATE`. Контракт —
[ADR-0025](../adr/0025-terminal-document-set-completeness-review.md).
## Server-managed first-chunk worker и local pilot (S48, 2026-09-17)

- worker выполняет только server-revalidated claimed dispatch для первого chunk;
  exact request/chunk bytes и approval expiry проверяются непосредственно перед
  сетью, затем выполняется ровно один HTTP call без retry/redirect;
- `dispatch-approved-ai-transfer` по умолчанию disabled и может быть включён
  только явным `AI_TRANSFER_LOCAL_PILOT_ENABLED=1`; legacy `analyze-tz-ai`
  отключён;
- local pilot использует `AI_TRANSFER_RAW_ROOT_KEK_B64` и
  `AI_TRANSFER_RAW_KEK_ID` через HKDF-derived tenant KEK adapter. Это не
  production KMS, не rotation и не production key-management contract;
- complete raw response шифруется per-blob DEK и сохраняется ровно 720 часов.
  Execution detail показывает reviewer/auditor безопасные metadata и digest;
  raw endpoint остаётся reviewer/auditor-only, no-store и audit-logged;
- purge записывает immutable deletion receipt, затем удаляет ciphertext и
  wrapped DEK; metadata/digests/review/audit остаются.

S48 не объявляет production готовым: необходимы managed KMS/rotation и
проверяемые backup/WAL/restore retention evidence. Текущий общий final gate также
не фиксируется в этом документе до его отдельного полного прогона.

## Case-bound sourcing runs (S80, 2026-09-20)

`POST /v1/cases/{case_id}/versions/{version}/sourcing-runs` принимает только
ограниченный поисковый запрос из 1–5 слов и обязательный `Idempotency-Key`.
Сервер сам выполняет один read-only GET allowlisted страницы ServerMall. При
успехе `sourcing_runs` сохраняет exact HTML bytes, SHA-256, время наблюдения,
выведенные карточки, tenant/case binding и audit event. Исходный HTML через API
не возвращается. `GET .../sourcing-runs/latest` читает последний результат
только в пределах той же компании и точной версии кейса.

`COMPLETED` с пустым shortlist означает проверенный снимок без совпадений по
названию. `SOURCE_ERROR` означает недоступность либо неподдерживаемую форму
источника; это состояние не подменяется пустой выдачей. Без exact case binding
исполняемые требования не применяются; `technical_scope_status` остаётся `UNKNOWN`.

## Reviewed requirement sets и case binding (S81, 2026-09-20)

- `POST /v1/reviewed-requirement-sets` доступен operator и принимает exact
  `source_document_id + SHA-256`, declared scope, ожидаемое число строк и полный
  упорядоченный список entries. Идентификатор, actor, время и digest назначает
  сервер;
- entry хранит исходные name/value, provenance и одно из двух состояний:
  `EXECUTABLE` с typed `Requirement` либо `MANUAL_REVIEW_REQUIRED` без скрытого
  допуска. Ordinals должны непрерывно покрывать весь заявленный диапазон;
- `POST /v1/reviewed-requirement-sets/{set_id}/decision` доступен только
  `COMPLETENESS_REVIEWER`, требует exact proposal digest и сохраняет единственное
  решение. Автор proposal не может быть reviewer; `PASS` требует подтверждённых
  coverage и normalization;
- `POST /v1/case-requirement-set-bindings` доступен operator, принимает точные
  proposal/decision digests и связывает только `PASS` с одной существующей
  `case_id + version`. Reviewer не может быть binder. Для версии кейса допустим
  ровно один immutable binding;
- GET-ресурсы читают только явный `set_id` или `binding_id`; list/latest выбора
  нет. Все JSON body bounded, duplicate keys и лишние поля отклоняются;
- три таблицы append-only, tenant-scoped через RLS/FORCE RLS, связаны composite
  FK с exact document/case/decision identity. Каждая запись повторно собирается
  из payload и проверяется по digest при чтении.

Sourcing сначала читает binding точной версии кейса. При его наличии применяются
только typed requirements, а manual entries перечисляются как открытый scope.
Результат хранит `requirement_set_id` и три SHA-256 ссылки; общий
`technical_scope_status` остаётся `UNKNOWN`, потому что карточка не подтверждает
полный exact BOM и КП.

## Server-derived materialization requirement set (S82, 2026-09-20)

- `POST /v1/documents/{document_id}/reviewed-requirement-set-preview` принимает
  exact source SHA-256 и ожидаемое число строк. Сервер читает tenant-scoped
  persisted document, проверяет роль `TENDER_REQUIREMENTS` и extraction `PASS`,
  затем выбирает ровно одну полную native DOCX-таблицу с непрерывными строками;
- preview возвращает все исходные name/value/instruction, provenance и digest.
  Browser не передаёт исходный текст. Числовые результаты маппера обозначены
  как подсказки и не являются исполнимыми требованиями;
- `POST /v1/documents/{document_id}/reviewed-requirement-set-materializations`
  повторно строит preview и требует exact `preview_sha256`. Оператор может явно
  выбрать только показанную числовую подсказку и обязан задать canonical
  property, обязательность и основание. Все остальные строки сохраняются как
  `MANUAL_REVIEW_REQUIRED`;
- оба endpoint доступны только роли `OPERATOR`, bounded strict JSON и
  `Cache-Control: no-store`; commit идемпотентен и использует существующее
  append-only S81 storage. Отдельные reviewer decision и case binding остаются
  обязательными.

## Official manufacturer source selection (S83, 2026-09-20)

Существующий `POST .../sourcing-runs` сначала маршрутизирует отличительный exact
model query в allowlisted официальный каталог: `DL360 Gen12` — HPE QuickSpecs,
`SR630 V3` — Lenovo Press Product Guide. Успешный ответ проходит bounded HTML и
identity validation, после чего его неизменённые bytes и SHA-256 сохраняются в
прежней append-only записи sourcing run. `source_name/source_url` всегда
указывают реально использованный источник.

Если HPE endpoint недоступен или изменил identity, сервис один раз пробует
релевантный ServerMall HPE Gen12 catalog. Успешный fallback сохраняется как
supplier source; если он также не дал проверяемого снимка, run получает
`SOURCE_ERROR` без bytes и карточек. Для Lenovo нерелевантный HPE supplier
catalog не вызывается, и ошибка official source остаётся явной.
`ServerLead.source_kind` различает
`MANUFACTURER_CATALOG | SUPPLIER_CATALOG`; official lead содержит manufacturer,
но доменная модель запрещает приписывать странице семейства цену или exact BOM.
Schema migration не требуется: поля находятся в проверяемом JSON result, а
exact snapshot использует существующие digest/size constraints.

## Exact artifacts нескольких sourcing sources (S84, 2026-09-20)

Миграция `20260920_03` добавляет `sourcing_run_sources`. Ключ —
`company_id + run_id + ordinal`; строка ссылается composite FK на parent run и
хранит source kind/URL/media type/status/observed-at. При `COMPLETED` обязательны
exact bytes, SHA-256 DB-проверка и размер 1..20 МиБ; при `SOURCE_ERROR` bytes и
digest отсутствуют, error code обязателен. Таблица использует RLS/FORCE RLS,
только `SELECT/INSERT` для app role и общий immutable trigger.

Parent `sourcing_runs.source_content` при частичном/полном успехе содержит
canonical `sourcing-source-manifest-v1` с ordered metadata всех attempts. Parent
`COMPLETED`, если есть минимум один successful child; ошибки других children
сохраняются. `SOURCE_ERROR` допустим только без successful child и без parent
snapshot. Каждый lead обязан ссылаться digest на один successful child.
Deferred constraint trigger при commit проверяет число и identity child rows
против ordered `result.sources`, включая digest, byte size и observed-at.

Существующий endpoint и idempotency key не меняются. API result добавляет
ordered `sources`; старые persisted rows валидируются с пустым списком. Для HPE
run может содержать official и supplier attempts, для Lenovo/Dell — только
релевантный official attempt.

## Reviewer decision и operator binding через BFF (S85, 2026-09-20)

Новых endpoint и таблиц нет. Reviewer BFF читает только явный
`GET /v1/reviewed-requirement-sets/{set_id}` и пишет
`POST .../{set_id}/decision` через dedicated credential роли
`COMPLETENESS_REVIEWER`. Перед записью server action повторно читает exact set и
сверяет `proposal_sha256`; выбранных по умолчанию assessment/status нет.

Operator BFF тем же exact GET через `PROCUREMENT_API_TOKEN` проверяет persisted
terminal `PASS`, повторно сверяет `proposal_sha256 + decision_sha256` и только
затем вызывает `POST /v1/case-requirement-set-bindings` с явными
`case_id + case_version`. API сохраняет authority за проверкой разделения ролей,
существования версии кейса и единственности append-only binding. Ни один маршрут
не имеет list/latest выбора.

## Exact server-offer proposal (S86, 2026-09-20)

Миграция `20260920_04` добавляет append-only `server_offer_proposals`. Строка
содержит exact case version, requirement-set binding ID/digest, sourcing run/lead,
`SUPPLIER_QUOTE` document ID/SHA-256, canonical proposal digest, actor и
timezone-aware время. Composite FK связывают case, binding, sourcing run и exact
document identity. RLS/FORCE RLS, immutable trigger и JSON/column identity checks
не позволяют читать другой tenant или изменять сохранённое предложение.

`POST /v1/cases/{case_id}/versions/{version}/server-offer-proposals` доступен
только `OPERATOR`. Payload принимает exact references, 1–500 упорядоченных BOM
lines и коммерческие условия. Сервер заново читает binding и sourcing run,
требует, чтобы run использовал тот же binding, находит exact lead, проверяет роль
и digest КП-документа и только после этого назначает offer ID, actor, время и
digest. Caller не передаёт lead snapshot, status или review result.

`GET /v1/server-offer-proposals/{offer_id}` читает один явный immutable resource;
list/latest endpoint отсутствует. Ответ всегда `technical_status=UNKNOWN` и
`review_status=PENDING_REVIEW`. Полностью itemized BOM дополнительно проверяется:
сумма line totals должна равняться `amount_ex_vat`. Lump-sum КП допускается с
пустыми line prices, но эта неизвестность остаётся видимой.
## Independent server-offer review (S87, 2026-09-20)

`server_offer_review_decisions` хранит одно append-only решение на exact
`company_id + offer_id`. Composite FK фиксирует proposal digest и exact
`reviewed_requirement_set_decisions` proposal/decision digests. JSON identity
продублирована CHECK constraints; RLS/FORCE RLS, immutable trigger и grant
разрешают приложению только `SELECT, INSERT`.

`GET /v1/server-offer-proposals/{offer_id}/review` возвращает proposal и полный
approved requirement set вместе с сохранённым решением либо `null`. `POST
/v1/server-offer-proposals/{offer_id}/review-decision` принимает только exact
proposal SHA-256, решения всех requirement ordinals, BOM/terms assessments и
основание. Оба route требуют `COMPLETENESS_REVIEWER`; caller не передаёт итоговый
status, actor или время. Сервер проверяет независимость reviewer, evidence refs,
срок и полноту КП и атомарно записывает decision, audit и receipt.
## Server-offer economics package (S88, 2026-09-20)

`server_offer_economics_packages` хранит один immutable package на exact case
version. Composite FK связывает его с terminal offer review; repository также
сверяет persisted case input SHA-256. Таблица tenant-scoped, RLS/FORCE RLS,
append-only и доступна runtime role только для `SELECT, INSERT`.

Operator-only `GET/POST
/v1/cases/{case_id}/versions/{version}/server-offer-economics` читает evidence и
создаёт package. POST не принимает goods, НДС, status, actor или время: эти поля
сервер получает из PASS КП и request context. Caller передаёт exact offer/review
digests и три полных scenario inputs.

## Controlled case materialization из economics package (S89, 2026-09-20)

`POST /v1/cases/{case_id}/versions/{version}/server-offer-economics/materialize`
принимает только `offer_id`, `economics_id` и `package_sha256`. Endpoint доступен
OPERATOR, использует strict JSON и `Idempotency-Key`, повторно читает exact
tenant-scoped package и создаёт только версию `version + 1`.

Repository атомарно вставляет immutable case snapshot, audit event
`case.materialized_from_server_offer_economics` и write receipt. Quote и
scenario set строятся сервером. Assessment содержит лишь evidence-backed
technical PASS; отсутствие остальных hard gates сохраняется как отсутствие, а
не превращается в PASS. Endpoint не вызывает evaluation engine.

## Exact hard-gate assessment materialization (S90, 2026-09-20)

`GET /v1/cases/{case_id}/versions/{version}/hard-gate-assessments/evidence`
возвращает OPERATOR точный source case и `case_input_digest`, только если case
имеет актуальный единственный technical PASS. POST `.../materialize` принимает
этот digest, exact document binding/manifest/decision digests и четыре решения:
LEGAL, PARTICIPANT, COMPANY_POLICY, LOGISTICS.

Repository дополнительно требует уникальный S89 audit lineage и побайтно
реконструируемый economics source. DOCUMENT check выводится сервером из terminal
document-set binding. Для каждого известного caller-owned verdict проверяются
tenant-scoped document ID и SHA-256; в case сохраняется locator/provenance, а
полные exact refs остаются в audit basis. Case `version + 1`, audit и receipt
создаются атомарно. Endpoint не создаёт evaluation.
# S92: independent participation decision

`GET /v1/evaluations/{evaluation_id}/participation-decision` возвращает exact
evaluation evidence и optional terminal decision только роли
`PARTICIPATION_APPROVER` или read-only `AUDITOR`. `POST` доступен только
`PARTICIPATION_APPROVER` и принимает evidence SHA-256, `APPROVED | REJECTED` и
основание. Reviewer должен отличаться от actor события `case.evaluated`.

Repository восстанавливает evaluation из immutable case, recommendation и
единственного audit event. Перед `APPROVED` тот же case повторно вычисляется на
текущее timezone-aware серверное время и обязан снова дать `PARTICIPATE`.
Таблица `participation_decisions` tenant-scoped, append-only и содержит одну
terminal запись на evaluation; decision, `case.participation_decided` audit и
idempotency receipt атомарны. `external_action_authorized` всегда `false`.

## S93: immutable комплектация заявки

`GET /v1/participation-decisions/{decision_id}/application-package` возвращает
exact APPROVED case/decision и optional пакет роли OPERATOR или AUDITOR. `POST`
доступен только OPERATOR и принимает decision SHA-256, Decimal-цену без НДС,
упорядоченные требования с locator в `TENDER_REQUIREMENTS` и маппинг на
immutable `APPLICATION_ATTACHMENT` document ID/SHA-256. Сервер сверяет роли и
байты в tenant, актуальный deadline, `PARTICIPATE`, floor и НМЦК. Нельзя
передать review/coverage status, actor, время или external authorization.

`application_packages` хранит одну запись на decision под composite FK,
RLS/FORCE RLS, JSON identity constraints и immutable trigger. Package, audit
`application.package_prepared` и idempotency receipt атомарны. GET повторно
восстанавливает пакет из exact evidence и сверяет документы. Результат только
`PENDING_REVIEW / UNKNOWN`, `external_action_authorized=false`.

## S94: независимый review exact пакета заявки

`GET /v1/application-packages/{package_id}/review` возвращает immutable пакет
и optional terminal decision роли `APPLICATION_REVIEWER` или read-only
`AUDITOR`. `POST` доступен только reviewer, отличному от автора пакета, и
принимает exact package SHA-256, verdict/основание для каждой строки и файла,
ссылки на проверенные вложения, оценку полного перечня с IDs проверенных
документов заказчика и оценку цены. Сервер вычисляет итог, заново проверяя
deadline, `PARTICIPATE`, floor и НМЦК. `GET .../documents/{document_id}/content`
отдаёт оригинал только если он входит в этот пакет и совпадают tenant, роль,
SHA-256 metadata и байтов; browser получает его через BFF без bearer token.

`application_package_reviews` содержит не более одного terminal решения на
пакет, composite FK, JSON/column checks, RLS/FORCE RLS и immutable trigger.
Decision, `application.package_reviewed` audit и idempotency receipt атомарны.
Любой `PASS` всё равно хранит `external_action_authorized=false`.

## S95: exact команда подачи и независимое подтверждение

`GET /v1/application-packages/{package_id}/submission` доступен `OPERATOR`,
`APPLICATION_SUBMISSION_APPROVER` и read-only `AUDITOR`. `POST` по этому пути
доступен только `OPERATOR` и принимает exact package/review SHA-256 и HTTPS
адрес. При terminal review `PASS` сервер заново проверяет актуальные
`PARTICIPATE`, deadline и ценовой коридор, затем строит `ActionRequest` с
адресом, Decimal-ценой и точными данными каждого файла. Клиент не передаёт
состав payload. Для пакета сохраняется не более одной команды.

`POST /v1/application-packages/{package_id}/submission/approval` доступен
только `APPLICATION_SUBMISSION_APPROVER`, отличному от автора пакета,
проверяющего и автора команды. Он принимает action ID, payload SHA-256,
`APPROVED | REJECTED` и reason. Положительный `Approval` действителен максимум
15 минут и не дольше deadline или срока КП; `REJECTED` не имеет approval. `application_submission_intents`
и `application_submission_approvals` append-only, tenant-scoped с RLS/FORCE
RLS, composite FK и JSON identity checks. Каждая запись, audit и receipt
атомарны. GET реконструирует exact source/review/intent/decision. Нет endpoint
для подписи или отправки; исполнитель и одноразовое потребление — следующий
срез.

## S96: одноразовый admission exact заявки

`GET /v1/application-packages/{package_id}/submission/admission` возвращает
exact S95 команду, approval и optional admission роли
`APPLICATION_SUBMISSION_EXECUTOR` или read-only `AUDITOR`. `POST` принимает
action ID, payload SHA-256 и approval decision SHA-256 только от исполнителя.
В одной транзакции сервер проверяет актуальные approval/deadline/участие/floor,
перечитывает байты всех `APPLICATION_ATTACHMENT`, сверяет их SHA-256, роль,
имя, MIME type и точный состав. Затем сохраняет один
`application-submission-admission-v1` с byte size/хешем каждого файла и
`ADMITTED_NO_DISPATCH`. `application_submission_admissions` имеет FK к
approval, уникальный action ID, RLS/FORCE RLS, immutable trigger и JSON
identity checks; запись, audit и receipt атомарны. Повторный claim с другим
idempotency key получает конфликт. GET проверяет сохранённый manifest по
оригинальным байтам. Адрес ЭТП не вызывается, подписи и receipt подачи нет.
