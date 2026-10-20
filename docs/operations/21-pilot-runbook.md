# Runbook пилотного прогона по серверному пути

Статус: **инструкция для исполнения; сам пилот не запущен**.

Протокол приёмки — [20-stabilization-pilot.md](20-stabilization-pilot.md):
там выборка, эталон, метрики и критерии `PASS/FAIL/UNKNOWN`. Этот файл —
только порядок действий по реализованному серверному пути (срезы S61–S66) и
контрольные списки. Нормативные требования протокола имеют приоритет: при
расхождении выполнять протокол, а расхождение фиксировать в отчёте.

## 0. Окружение

```powershell
uv sync --extra dev
docker compose up -d postgres
uv run alembic upgrade head
./scripts/verify-postgres.ps1
```

Обязательный storage gate — `./scripts/verify-postgres.ps1`; обычный
`uv run pytest tests/integration -q` без `DATABASE_URL` пропусков не даёт.
Детали ролей и URL — в [S2](17-storage-api.md).

Сервер API:

```powershell
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Ключи выдавать отдельно под каждую роль пилота (bootstrap `--access-role`):

| Роль | Для шагов |
|---|---|
| `OPERATOR` | загрузка, snapshot, manifest, binding, кейс |
| `COMPLETENESS_REVIEWER` | решения single/manifest review (API или UI) |
| `AI_REQUIREMENTS_REVIEWER` | только если AI-путь включён в пилот |
| `AUDITOR` | чтение evidence при вторичной проверке |

Bearer secret показывается один раз и не попадает в Git, отчёты и логи.
UI (`web/`, `npm ci`, `npm run build`) использует server-only токены
(`PROCUREMENT_API_URL`, `PROCUREMENT_API_TOKEN` и выделенные reviewer-токены);
браузер токенов не видит. Страницы пилота: `/`, `/document-search`,
`/ocr-review`, `/completeness-review`, `/document-set-review`,
`/ai-requirement-review`, `/case-from-evidence`.

## 1. Комплекты и manifest

Разложить разрешённые файлы по `samples/private/<set_id>/` (каталог в
`.gitignore`, в Git не попадает). На каждый комплект заполнить manifest по
шаблону из протокола: `set_id`, permission (`APPROVED`, scope `local_pilot`,
время с timezone), procedure reference, файлы с ролью, SHA-256 и размером,
`expected_difficulty`, `ground_truth_status`. До запуска проверить: файлы на
месте, SHA-256 совпадают, разрешение действительно, приватные файлы не попали
в `git status`.

## 2. Загрузка и extraction

На каждый файл — `POST /v1/documents` (одиночный) или
`POST /v1/document-bundles` (ZIP) с доверенной ролью `TENDER_REQUIREMENTS` или
`SUPPLIER_QUOTE` и новым `Idempotency-Key`. Записать `document_id`,
`ExtractionResult` (статус, reasons, units, extractor) и digest. Роль `UNKNOWN`
блокирует mapping. Макросы, формулы и внешние ссылки не исполняются — это
ожидаемое поведение, а не ошибка.

Scan-only PDF с `UNKNOWN/OCR_REQUIRED` — только поддержанным OCR endpoint
конкретного документа/member после проверки разрешения; недоступный или
неуверенный OCR остаётся `UNKNOWN`, текст не додумывается.

## 3. Completeness одного документа

Оператор: `POST /v1/documents/{id}/completeness-reviews` (server-derived
snapshot exact bytes/extraction/mapping). Reviewer (другая роль, не автор
snapshot): единственное решение `PASS | FAIL | UNKNOWN` через API или
`/completeness-review`. Self-review, stale digest и второе решение запрещены
сервером. Записать `review_id`, `evidence_sha256` и решение.

## 4. Комплект из нескольких документов

Оператор: `POST /v1/document-set-evidence-manifests` с явными
`(review_id, evidence_sha256)` всех 2–10 участников. Reviewer, независимый от
авторов snapshot и manifest: `POST /v1/document-sets/{manifest_id}/completeness-decisions`
или `/document-set-review?manifest_id=...`. Подтвердить каждого участника,
inventory и cross-document проверку; findings привязать к точным source blocks.
Статус выводится fail-closed сервером. Выбирать «последний PASS» автоматически
запрещено — только явный `manifest_id`.

## 5. Привязка и кейс

Оператор: `POST /v1/case-document-evidence-bindings` с exact
`manifest_id/manifest_evidence_sha256/decision_sha256` (или проверка готового
binding через `GET`). Затем `POST /v1/cases/from-evidence` с драфтом кейса
**без assessment**, теми же digest и дополнительными проверками (до 5, без kind
`document`) — либо `/case-from-evidence` в UI. Сервер выводит DOCUMENT-проверку,
собирает assessment с reviewer=actor и пишет версию кейса. Созданный кейс
читается обычным `GET /v1/cases/{id}/versions/{v}`.

КП и сценарии экономики собираются из проверенного эталона вручную (см.
протокол, шаг 4): деньги строками, `Decimal`, явный НДС, timezone-aware сроки.
Автопостроения кандидата/КП из extraction нет — это фиксируемый gap, а не
автоматический шаг.

## 6. Evaluation и наблюдение

`POST /v1/cases/{id}/versions/{v}/evaluations` на зафиксированный
`effective_at` с новым `Idempotency-Key`. Записать итог, все gate states,
основания, provenance, completeness, версию движка и audit/evaluation ID.
Внешняя отправка, подпись и юридические действия в пилоте запрещены.

## 7. AI-путь (опционально, только по явному решению)

Включать только если разрешены внешняя передача и ключ. Требуется:
`OPENROUTER_API_KEY`, pilot KEK (`AI_TRANSFER_RAW_ROOT_KEK_B64`,
`AI_TRANSFER_RAW_KEK_ID`), `AI_TRANSFER_LOCAL_PILOT_ENABLED=1`,
`DATABASE_URL` и записанный `authorization_reference` на передачу. Цепочка:
transfer request (operator) → approval (`AI_TRANSFER_APPROVER`, окно ровно
15 минут) → `dispatch-approved-ai-transfer` (по одному chunk за запуск) →
recovery при необходимости → reviewer queue (`/ai-requirement-review`,
import-only решения; completeness всегда `UNKNOWN`). Raw response хранится
шифрованно 720 часов и читается только reviewer/auditor. Без этих условий
AI-путь из пилота исключается, что фиксируется как ограничение выборки.

## 8. Негативный контроль

Минимум: один комплект с намеренно изменённым байтом (новый digest/snapshot,
старый evaluation неприменим); один межтенантный guessed-ID и один
replay/conflict на PostgreSQL gate. Проверки выполняются в рамках пилотного
tenant и не дают права публиковать внешние данные.

## 9. Сверка и отчёт

Сверить результат с human ground truth по каждой строке эталона (тип ошибки:
`extraction | mapping | completeness | candidate | quote | economics | policy |
presentation` + locator). Посчитать `false_pass_count` (цель `0`),
`material_requirement_recall`, `provenance_correctness`, ручное время по
интервалам из протокола. Отчёт — строго по шаблону протокола, только агрегаты
и digest; исходники, OCR-текст, КП и персональные данные остаются в защищённом
хранилище.

## Приложение A. Что нужно от владельца данных

1. 10–20 разрешённых комплектов в `samples/private/` с покрытием классов
   (обычный, неоднозначный, скан, вложения, КП-ловушка) и permission reference.
2. Назначенные `pilot_owner`, `data_owner`, `ground_truth_reviewer` (двое или
   один с отмеченной независимой второй проверкой).
3. Независимый human ground truth по каждому комплекту до просмотра вывода
   системы (требования, не-требования, КП, gates, рекомендация, locator).
4. Цель `material_requirement_recall` и допустимые ограничения выборки — или
   явное согласие, что цель остаётся `UNKNOWN`.
5. Решение о включении AI-пути (раздел 7) либо его исключении.
6. Окно пилота и подтверждение удаления/маскирования после него.
7. Доступ к Docker PostgreSQL для обязательного gate (или согласие, что gate
   выполняет владелец данных у себя по разделу 0).

Без пунктов 1–3 результат пилота остаётся `UNKNOWN` независимо от готовности
кода.

## Проверка самого runbook

Файл проверен как UTF-8 Markdown: все fenced code blocks закрыты, таблицы имеют
строки заголовка и разделитель, ссылки ведут на существующие документы
(`20-stabilization-pilot.md`, `17-storage-api.md`). Проверка не означает, что
пилот выполнен: команды и результаты появляются только после фактического
запуска с сохранением evidence.
