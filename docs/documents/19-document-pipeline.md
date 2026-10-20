# S4: конвейер документов и извлечения

## S142: текстовая производная legacy DOC (2026-10-02)

OLE Word 97–2003 читается серверным antiword 0.37-16 после MIME/magic/FIB/
stream preflight; encryption/macros отклоняются. Child ограничен ресурсами,
сетью/дочерними процессами и не наследует secrets. `legacy_doc_text` — lossy,
UNKNOWN/LAYOUT_NOT_VERIFIED: locator `antiword-0.37-16 utf8 w0 :: line N`
относится к reproducible выводу, а таблицы/полнота требований требуют review.
На Windows без конвертера — UNKNOWN/CONVERTER_UNAVAILABLE. ZIP сохраняет member
provenance. Подробности — [ADR 0049](../adr/0049-legacy-doc-text.md).

EIS v3-doc добавлен миграцией 20261002_02 без изменения v1/v2-xls и receipts.
Cached reanalysis S141 проверяет exact current ref/SHA/size/tenant и не скачивает
документ повторно. На двух реальных DOC выбранной карточки подтверждены
40/72 blocks, 12/21 condition snippets; source bytes и immutable proofs на VPS.
Эти snippets ещё не утверждённые требования и не финансовая рекомендация.

## S141: ограниченный legacy XLS (2026-10-02)

OLE BIFF8 XLS поддержан отдельно как native_xls с sheet!cell locators и
archive-member prefix в ZIP. Literal TEXT/NUMBER извлекаются после preflight
MIME/magic/OLE/BIFF/limits; formula coordinates и их cached values исключены.
VBA/macro sheet и шифрование отвергаются, старый BIFF/непрочитанные cell types,
drawings и внешние ссылки остаются UNKNOWN. Парсер не вычисляет формулы и не
вызывает Office/сеть. Подробный контракт — [ADR 0048](../adr/0048-legacy-xls-extraction.md).
PASS native text не подтверждает роль или полноту комплекта.

EIS analyzer v2-xls хранится рядом с v1: исходные bytes/receipt/analysis
не переписываются. Worker делает максимум один versioned cached reanalysis
step без download, проверяет SHA, manifest size и current exact tenant ref.
Stale ref отклоняется; replay не извлекает повторно. Status отдельно показывает
analysis_pending_count для полученных файлов, ожидающих новой версии разбора.
Legacy DOC расширен следующим S142; ограничения его layout описаны выше.

Статус: живой контракт S4; шестьдесят ограниченных срезов завершены к
2026-09-18. Ранние разделы фиксируют базовую границу первого среза, последующие
датированные разделы расширяют её. S4 остаётся незавершённым до production-
калибровки OCR на разрешённых закупочных сканах и подключения первого
согласованного источника мониторинга.

## Назначение

Конвейер принимает документ закупки или его версию, сохраняет исходные байты
неизменяемо, извлекает подтверждённый нативный текст и возвращает факты с
provenance. На этом срезе он не делает юридический вывод, не принимает решение
об участии и не вызывает внешние каналы. Любое содержимое документа считается
недоверенным вводом.

## Приём и неизменяемость

Каждая загрузка принадлежит tenant и получает идентификатор, размер, проверенный
по расширению и сигнатуре заявленный MIME, SHA-256 исходных байтов и время приёма.
Байты и результат извлечения относятся к одной версии. Существующую версию
нельзя изменять или перезаписывать; исправление создаёт новую версию с новой
доказательной цепочкой. Внешний идентификатор или имя файла не используется как
путь, SQL-идентификатор или разрешение доступа.

В пилоте исходные байты хранятся в PostgreSQL `BYTEA` (см. ADR 0009). Слой
хранилища должен применять лимит размера до записи и проверять tenant в каждой
операции. В production этот интерфейс заменяется S3-совместимым хранилищем с
неизменяемыми объектами и retention policy; идентификатор объекта и digest
останутся частью записи версии.

## Поддерживаемые форматы и защита

Первый срез принимает PDF, DOCX и XLSX после проверки расширения, MIME и
сигнатуры файла. Макросодержащие варианты и иные неподдержанные контейнеры
отклоняются. У архивных форматов до разбора проверяются число членов, суммарный
распакованный размер, отношение распакованного размера к входному и отсутствие
опасных путей. Ограничения действуют также на число страниц, листов и объём
извлечённого текста.

Парсер не запускает макросы, формулы, вложенные программы, внешние ссылки,
шаблоны или сетевые ресурсы. Ячейки XLSX с формулами исключаются из фактов и
делают результат `UNKNOWN/FORMULAS_IGNORED`; литеральные значения сохраняют
собственный locator. Переполнение лимита, повреждённый контейнер, шифрование или
нарушение политики безопасности дают безопасную ошибку загрузки; успешно
принятый снимок и его результат записываются вместе с audit event.

## Извлечение и provenance

Нативный текст извлекается с локаторами, достаточными для повторной проверки:

| Формат | Минимальный locator |
|---|---|
| PDF | номер страницы и диапазон блока/позиция извлечения |
| DOCX | номер абзаца или таблицы, строка и ячейка при наличии |
| XLSX | имя листа и диапазон ячеек |

Каждый сегмент содержит `document_id`, текст или безопасно нормализованное
значение, тип извлечения, locator, extractor/version и confidence. Сегменты не
сливаются так, чтобы потерять ссылку на исходный документ. Неоднозначное
распознавание не повышается до факта без подтверждения источником.

Для DOCX и XLSX `source_units_total` считает непустые нативные текстовые
единицы, из которых могут быть созданы evidence-блоки. Пустые абзацы, ячейки и
разреженная область листа всё равно обходятся и входят в resource-limit guard,
но не изображаются как потерянный текст. Для PDF единица — страница: страница
без нативного текста может быть сканом, поэтому разность total/extracted
остаётся блокирующим признаком неполноты для persisted completeness review.

Срез S72 (2026-09-19): DOCX-обход включает таблицы, вложенные в ячейки, на
любой конечной глубине. Locator дочерней ячейки сохраняет полный путь, например
`table 1 row 3 cell 3 nested table 1 row 7 cell 2`. Ячейки объединённой
области не дублируются; вложенные единицы входят в лимиты числа source units и
извлечённых символов. Это извлечение текста, а не объединение соседних ячеек в
семантическое требование. `PASS` native extraction не означает `PASS` полноты.
Ранее сохранённые immutable extraction snapshots не переписываются автоматически.

Для PDF без извлекаемого нативного текста базовый результат имеет статус `UNKNOWN`
с причиной `OCR_REQUIRED`. OCR не подменяет этот результат: отдельный workflow,
описанный ниже, создаёт immutable производную версию с собственными extractor,
confidence и provenance. Пустой документ, изображение без принятого OCR-текста,
неподдержанный формат и нечитаемое содержимое не считаются соответствующими
требованиям закупки.

## Состояния результата

Статус относится к конкретному проверяемому утверждению или операции:

- `PASS` — формат и содержимое успешно обработаны, а указанный результат
  подтверждён источником;
- `FAIL` — операция запрещена политикой или документ нарушает проверяемое
  техническое условие (например, опасный архив);
- `UNKNOWN` — данных недостаточно, текст требует OCR, либо результат неоднозначен.

`UNKNOWN` не превращается в допуск и должен быть виден оператору вместе с
причиной и provenance. Парсер не создаёт правовых, коммерческих или технических
выводов, которых нет в исходном документе; LLM-анализ и нормализация требований
будут отдельным слоем с теми же правилами доказательности.

## Граница API первого среза

`POST /v1/documents` принимает один multipart-файл, обязательное поле
`document_role` (`UNKNOWN | TENDER_REQUIREMENTS | SUPPLIER_QUOTE`), bearer
credential и `Idempotency-Key`. Лимит файла — 20 МиБ. Успешный ответ содержит
`document_id`, роль, имя, MIME, размер, SHA-256, время создания и типизированный
результат извлечения; исходные байты в HTTP-ответ не входят. Роль входит в digest:
повтор точного запроса с тем же ключом возвращает ту же запись, а изменение роли
или другого payload с прежним ключом даёт конфликт.

`GET /v1/documents/{document_id}` возвращает те же метаданные и сегменты только
в tenant текущего bearer credential. Отсутствующий и чужой идентификаторы одинаково
дают `404`. Для записи обязательны tenant scope, digest, статус
`PASS|FAIL|UNKNOWN`, причины, provenance и audit event.
Публикация, отправка заявки, запрос КП, переписка, подписание и любые другие
внешние действия в этот конвейер не входят и требуют отдельного exact-payload
approval.

## Проверка и известные границы

Минимальная приёмка: одинаковый digest даёт неизменяемую версию; другой файл
создаёт новую версию; чужой tenant не видит байты, метаданные или сегменты;
валидные PDF/DOCX/XLSX возвращают нативный текст с locator; сканированный или
пустой PDF возвращает `UNKNOWN/OCR_REQUIRED`; архивные лимиты и macro/external
link policy срабатывают до разбора; ни один parser не выполняет формулы или код.

Нужно отдельно добавить проверку антивирусом/санитизацию, полнотекстовый и
семантический индекс, извлечение таблиц с более точной геометрией, юридический
модуль и источники ЕИС/ЭТП. До их реализации отсутствие извлечённого факта
остаётся `UNKNOWN`.

## OCR-производная версия (второй срез S4, 2026-09-09)

Оригинал не мутирует: OCR создаёт отдельную immutable-запись
`document_ocr_derivatives` с FK на `(company_id, source_document_id)`,
собственным `ocr_id`, `engine`, `threshold`, типизированным `result`
(`OcrDerivative`), `mean_confidence` и `created_at`. RLS/FORCE RLS,
append-only trigger, `GRANT SELECT, INSERT` и атомарная связка
запись + `document.ocr_stored` + idempotency receipt повторяют контракт
таблицы `documents` (миграция `20260909_02`).

API: `POST /v1/documents/{id}/ocr` (body содержит только `threshold` по умолчанию
`0.75`; обязательный `Idempotency-Key`; digest связывает
`document_id/engine/threshold/source_sha256`), `GET
/v1/documents/{id}/ocr/latest`, `GET /v1/document-ocr/{ocr_id}`. Байты наружу
не отдаются; чужой tenant и отсутствующий id одинаково дают `404`; повтор
ключа с тем же digest — тот же `201`, с другим — `409`.

Домен (`procurement.documents.ocr`): кандидаты с `confidence < threshold`
и пробельный текст отбрасываются и в факты не повышаются; пустой итог —
`UNKNOWN/OCR_REQUIRED` с `mean_confidence 0.0`; прошедшие блоки несут
`Provenance(extractor=ocr, confidence=кандидата)` с locator страницы/блока.
Engine выбирается сервером и не принимается от клиента. Production runtime
использует локальный `paddleocr/3.7.0:PP-OCRv5-ru`; тестовый app factory без
явного runner сохраняет детерминированный `local-stub/0.1`. Сетевые OCR-сервисы
запрещены теми же границами, что и весь конвейер.

## Маппинг блоков в строгие факты и золотой набор v0 (третий срез S4, 2026-09-10)

Детерминированный маппер `procurement.documents.facts.map_blocks_to_requirements`
переводит `ExtractedBlock` в доменные `Requirement` (домен уже типизирован:
`Requirement/Attribute/Certificate/LineItem + Provenance`). Правила среза —
только `warranty` (гарантия, годы нормализуются в месяцы) и `ethernet_ports`
(порты), оба `mandatory=True`, `operator=GE`, provenance блока без изменений.
Блок с `confidence < 0.75` уходит в `unmapped` с `LOW_CONFIDENCE`, распознанный,
но непокрытый правилами текст — с `NO_PATTERN_MATCH`; ничто непокрытое в факты
не повышается. Результат — `FactMappingResult` (requirements, unmapped,
blocks_total, blocks_mapped, completeness).

Дополнение S73 (2026-09-20): для нативных DOCX маппер собирает соседние
ячейки **одной** строки, включая вложенную таблицу, в `table_row_candidates`,
если видит явную числовую границу `GE/LE`. Кандидат хранит исходное имя
характеристики, порог, единицу при её явном наличии и provenance каждой
использованной ячейки. Он не является `Requirement`: обязательность,
канонический атрибут, предмет закупки и полноту должен проверить человек.
Эти ячейки продолжают учитываться как `unmapped`; `blocks_mapped` и
`completeness=UNKNOWN` не меняются. Низкий confidence и роль не-ТЗ запрещают
кандидатов. Фраза «гарантия сроком 36 месяцев» теперь распознаётся как
одноблочное требование `warranty >= 36 мес` с точным provenance, но сама по
себе не подтверждает полноту документа или комплекта.

Золотой набор `data/goldenset/v1/tz_001.{docx,expected.json}`: DOCX из трёх
абзацев → 2 требования с точным provenance + 1 честный unmapped; тест
`tests/test_goldenset_v1.py` сверяет маппинг с эталоном и запрещает ложный
PASS (каждое требование обязано нести provenance с confidence не ниже порога).
Расширение набора (скан-PDF, XLSX с формулами, КП-ловушки, сертификаты) и
мониторинг источника — следующие срезы; S4 ещё не завершён.

Золотой набор v1 (2026-09-10) добавляет негативные пути: `tz_002.pdf`
(пустой скан → `UNKNOWN/OCR_REQUIRED`, блоков нет, маппинг пуст — без синтеза)
и `tz_003.xlsx` (лист `Spec`: литерал `Spec!A1` маппится в `warranty >= 12`,
формула `=1+1` исключена, статус `UNKNOWN/FORMULAS_IGNORED`). Набор синтетический
и версионируется (`data/goldenset/`, исключение в `.gitignore`); эталоны
проверены вручную поле за полем, `Decimal` в эталонах — числами.

Правила R1–R4 (2026-09-10): запрет эквивалента → `equivalent_allowed=False`
(отсутствие фразы — `None`, `True` не ставится никогда); якорная дата
поставки `DD.MM.YYYY` → `delivery_deadline` (невалидная дата и относительные
сроки — честный unmapped); ключевые числовые `depth`/`data_rate`/`power`
с сырой единицей из ТЗ; страна происхождения только EQ
(`NE` отложен — нужен словарь прилагательное→страна). Связка `tests/test_tz001_e2e.py`: факты tz_001 → `compliance.evaluate` —
`COMPLIANT`, `FAIL` по гарантии/сертификату/эквиваленту,
`NEEDS_CLARIFICATION` при пропуске и низкой уверенности; `%` при `FAIL`
не показывается.

Золотой набор v2 (2026-09-10): `tz_004` (запрет эквивалента + якорная дата,
флаги без требований) и `tz_005` (`depth`/`power`/`country EQ` как файлы).
Словарь стран (12 форм → 6 стран, нормализация ё, неизвестное — в unmapped)
закрывает `country NE`; R2 терпит двоеточие/тире после якоря
(«Срок поставки: до ...»).

## Семантические AI-кандидаты требований (тридцать второй срез S4, 2026-09-16)

Реальный pilot показал границу regex mapper: из 2 853 native-блоков он покрыл
один. Regex сохраняется как узкий детерминированный extractor и regression
oracle, но больше не рассматривается как полноценный анализатор свободных ТЗ.

`procurement.documents.ai_requirements` передаёт полное native extraction в
`google/gemma-4-31b-it:free` через фиксированный OpenRouter HTTPS endpoint.
Текст разбивается на стабильные chunks; строки таблиц остаются целыми, а header
из первой физической строки повторяется для следующей части большой таблицы.
Многострочные заголовки пока не определяются. Содержимое документа явно
помечается как недоверенное и не может менять policy, запрашивать секреты,
назначать роль или инициировать действие.

Для ZDR-пилота доступен `inclusionai/ling-3.0-flash-vl:free`. Модель не
поддерживает provider-side `response_format`, поэтому транспорт не отправляет
неподдерживаемый параметр, но strict local validation и fail-closed `UNKNOWN`
остаются обязательными. Ровно один fenced JSON block без окружающего текста
нормализуется перед строгим разбором; произвольный markdown и текст вокруг JSON
отклоняются.

Ответ модели валидируется локально строгой Pydantic-схемой. Модель ссылается
только на `block_id`; document ID, locator, точный source text и provenance
восстанавливаются из server-owned `ExtractionResult`. Лишние поля, выдуманный
block ID, повторный JSON-ключ, неправильный тип или невалидная пара
operator/value переводят весь chunk в `UNKNOWN`. Tenant-scoped отчёт обязательно
связан с `company_id` и хранит digests запроса/ответа, model и provider
generation ID.

Это `AiRequirementCandidate`, а не исполняемый `Requirement`. Даже успешный
run имеет `completeness=UNKNOWN/HUMAN_REVIEW_REQUIRED`, не попадает в compliance
и не запускает sourcing. Следующий срез должен persisted-связать exact AI run с
независимым review и только после него построить нормализованный mapping.

Для ручного теста одного полного native-документа:

```powershell
# OPENROUTER_API_KEY заранее задаётся через локальный secret manager/окружение.
uv run python -m procurement analyze-tz-ai `
  .\samples\private\tender.docx `
  --company-id company-a `
  --authorization-reference "owner approval reference" `
  --output .\samples\private\tender.ai-requirements.json
```

Команда требует явную ссылку на разрешение внешней передачи, не принимает ключ
аргументом, не печатает текст документа и публикует отчёт без перезаписи. Запрос
принудительно задаёт `data_collection=deny`, `zdr=true` и
`require_parameters=true`. Environment proxy по умолчанию отключён; если прямой
egress недоступен, он включается только явным `--allow-env-proxy`, а основание
должно фиксировать согласованный маршрут. Полная граница — в
[ADR-0022](../adr/0022-openrouter-semantic-requirement-candidates.md).

Live pilot 2026-09-17 подтвердил весь путь на приватном
`Приложение_№3_Описание_объекта_закупки.docx`. Прямой egress среды был недоступен,
поэтому после отдельного разрешения использован explicit `--allow-env-proxy`.
Gemma не получила ТЗ: её единственный бесплатный Google AI Studio endpoint не
совместим с ZDR. Ling через бесплатный ZDR endpoint завершил один chunk:
20/20 blocks covered, 3 source-bound кандидата (наименование/коды, единица `ПАЧ`,
количество `150.00`) и 17 unresolved blocks. Это соответствует фактически
непустым ячейкам документа, но остаётся `UNKNOWN/HUMAN_REVIEW_REQUIRED`.
Приватный report сохранён в ignored pilot directory; evidence SHA-256:
`54d48d45c1866385aba36882206f3439ec891a866fe7b0624828ab86029a618b`.

Нормализованный v2 rerun того же документа разделил смешанный результат на одну
review-only позицию: `Бумага для офисной техники`, ОКПД2 `17.12.14.119`, КТРУ
`17.12.14.110-00000005`, единица `ПАЧ`, количество `Decimal("150.00")`.
Название/коды ссылаются на block `b000018`, единица — `b000019`, количество —
`b000020`; отдельных псевдотребований больше нет. V1 contract и digest остаются
неизменными, schema dispatch не повышает старые отчёты автоматически. V2 также
остаётся `UNKNOWN/HUMAN_REVIEW_REQUIRED` и не является `LineItem`.
Evidence SHA-256 v2 report:
`05bfe658362e9e1c25a845bab5821e717e20299eb324757a8e605ccd740d78c8`.

## Persisted import и независимый review AI-кандидатов (2026-09-17)

Готовый v1/v2 report теперь можно сохранить через repository только как
недоверенный `IMPORTED_REPORT`. Перед insert сервер заново проверяет stored bytes,
роль `TENDER_REQUIREMENTS`, source/extraction digests, полное покрытие block IDs,
exact text/provenance каждого requirement и каждого поля item, response content
digest и provider model. Пересчитанный внутренний hash подменённого файла эту
проверку не обходит.

Snapshot остаётся immutable. Независимый reviewer принимает одно append-only
решение, покрывающее каждый candidate ровно один раз. `ACCEPTED` подтверждает
только существующий claim; отсутствующие unit/quantity/mandatory не заполняются.
Даже полностью принятый run остаётся `UNKNOWN` и не превращается в `Requirement`
или `LineItem`. Технически незавершённый run сохраняется как audit evidence, но
terminal review для него запрещён.

Этот срез не вызывает OpenRouter из HTTP и не считает строку
`authorization_reference` доказательством нового разрешения на передачу.
Server-managed dispatch и production retention полного provider response
остаются отдельными границами. Решение —
[ADR-0023](../adr/0023-persisted-ai-requirement-review.md).

Backend review API теперь выдаёт metadata queue оператору и reviewer, а exact
candidates/evidence — только `AI_REQUIREMENTS_REVIEWER`. Provider transcript,
полный extraction и approval reference всегда остаются за публичной схемой;
ответы помечены `no-store`. Решение reviewer actor-bound и идемпотентно, но не
даёт completeness `PASS`. Provider-run endpoint по-прежнему отсутствует.

Изолированный `/ai-requirement-review` использует отдельный server-only reviewer
token без fallback на operator credential. Очередь и exact evidence рендерятся на
сервере; browser не получает provider transcript, полный extraction, approval
reference или управление импортом/запуском модели. Решение покрывает точный набор
кандидатов и exact digest, после сохранения показывается только для чтения.
Незавершённый run остаётся read-only. Пустой COMPLETE-run можно закрыть пустым
terminal review, но полнота остаётся `UNKNOWN`.

Import-only API `POST /v1/documents/{document_id}/ai-requirement-runs` принимает
у `OPERATOR` ранее полученный v1/v2 report, но никогда не вызывает provider.
Tenant/actor/run/time принадлежат серверу; exact JSON ограничен 20 МиБ, читается
потоково и отвергается при неверном media type, duplicate/non-finite values,
неизвестных полях или silent normalization. После повторной source/evidence
валидации атомарно сохраняются run, audit и actor-bound receipt. Ответ содержит
только metadata summary и `no-store`; provider transcript и authorization string
не возвращаются и не становятся доказательством approval.

Preparation-only builder создаёт детерминированный
`ai-requirements-transfer-manifest-v1` без чтения ключа, сети, persistence или
API. Он фиксирует exact canonical request bytes и SHA-256 каждого chunk,
source/extraction/schema/prompt digests, reviewed Gemma/Ling profile, обязательные
ZDR/data controls и no-proxy transport. Adapter и fallback evidence используют
тот же serializer. Manifest не является разрешением: `APPROVAL_REQUIRED`,
`send_allowed=false`; сам preparation artifact по-прежнему ничего не отправляет.

Повторяющийся table header обязан иметь идентичные locator/text; лишний или
переставленный chunk, JSON type substitution и изменение request policy не
проходят повторную deterministic chunking/bytes validation. Request bodies
содержат текст ТЗ, поэтому manifest остаётся только in-memory и не публикуется.
Утверждённая policy теперь материализована отдельными immutable
`persisted-ai-transfer-request-v1` и `persisted-ai-transfer-approval-v1`.
Server-owned request повторно проверяет exact persisted source/extraction и
сохраняет ordered canonical request bytes/digests. Независимый
`AI_TRANSFER_APPROVER` подтверждает digest всего request на один batch в точном
15-минутном окне. Следующий persisted слой теперь атомарно потребляет approval в
owner-only execution admission и может выдать внутреннему worker ровно один
permanent claim для первого chunk. Claim commit-ится до любой будущей сети и
остаётся `DELIVERY_UNKNOWN`; повтор не возвращает dispatch authority. Второй
chunk закрыт до доверенного terminal success receipt. Exact-byte transport
теперь выполняет один вызов без proxy/redirect/retry, ограничивает raw stream и
проверяет HTTP/provider/model/wire-v2. Его результат — только typed metadata и
digests: raw body, assistant content, API key и provider error text наружу не
выходят. Immutable receipt связывается с exact first claim и audit, но public API
не создаёт claim/receipt и по-прежнему не вызывает provider.

Полный bounded raw response теперь хранится отдельно в зашифрованном виде ровно
720 UTC-часов: per-blob DEK, AES-256-GCM, tenant KEK provider protocol и
canonical AAD/digests. Complete receipt, metadata, encrypted blob и audit
записываются атомарно; incomplete/unknown/oversized transport не получает raw
capture. Reviewer/auditor-only точечное чтение возвращает raw без cache, а
operator/approver доступа не имеют.

Cleanup сначала immutable фиксирует deletion receipt, затем удаляет ciphertext и
wrapped DEK, сохраняя metadata, digests, candidates, review и audit. Deferred
anti-resurrection checks запрещают раннее удаление, purge без receipt и повторное
возвращение удалённого blob. Production capture не включается, пока backup/WAL/
restore retention не обеспечивает тот же предел. Код и focused checks среза
готовы, но final gate pending; live external worker и production tenant KEK
остаются отключёнными до инфраструктурного доказательства. Контракт —
в [ADR-0026](../adr/0026-exact-ai-transfer-approval-and-response-retention.md),
исходная граница review — в
[ADR-0023](../adr/0023-persisted-ai-requirement-review.md).

## Сертификатный срез и золотой набор v3 (2026-09-13)

Два узких правила извлекают только явно обязательные разрешительные документы:
`Декларация соответствия ТР ТС` и `Сертификат соответствия ЕАЭС`. Требование
кодируется как `certificate:<вид>`, `operator=EXISTS`, `mandatory=True` и несёт
provenance исходного блока. Модальный якорь обязателен: простое упоминание
сертификата в описании товара остаётся `unmapped/NO_PATTERN_MATCH` и не создаёт
hard gate.

Compliance сопоставляет требование только с `Certificate.kind` того же вида
после нормализации регистра и пробелов. Отсутствующий документ, неизвестная дата
поставки, низкий confidence или неизвестный срок действия дают `UNKNOWN` и
`NEEDS_CLARIFICATION`; просроченный на дату поставки документ даёт `FAIL`,
действующий — `PASS`. Нерелевантный просроченный документ кандидата сам по себе
не создаёт проверку.

`data/goldenset/v1/tz_006.docx` фиксирует полный путь: явное требование
декларации, абсолютная дата поставки и рядом упоминание сертификата-ловушка.
Эталон `tz_006.expected.json` проверяет точный locator и отсутствие ложного
требования; `tests/test_tz006_e2e.py` доводит извлечённый факт до вердикта
compliance. Граница среза: это не проверка подлинности по реестру, не полный
словарь разрешительных документов и не извлечение реквизитов из самого
сертификата. Эти данные остаются `UNKNOWN` до отдельного подтверждённого модуля.

## Роль документа и КП-ловушка (седьмой срез S4, 2026-09-13)

`map_blocks_to_requirements` теперь требует типизированную роль документа:
`UNKNOWN`, `TENDER_REQUIREMENTS` или `SUPPLIER_QUOTE`. Роль приходит из доверенного
контекста workflow и не выводится из текста документа: внешнее содержимое не
может объявить себя ТЗ и изменить политику обработки. `FactMappingResult`
сохраняет роль в типизированном output.

Только `TENDER_REQUIREMENTS` разрешает создавать требования, дату поставки и
флаг эквивалента. Для `SUPPLIER_QUOTE` каждый блок возвращается как
`unmapped/NON_REQUIREMENT_DOCUMENT`; валидатор результата запрещает совместить
роль КП с требованиями или флагами ТЗ. Это отделяет будущий Quote Analyzer от
requirement mapper и устраняет ложные hard gates из коммерческого предложения.
Для `UNKNOWN` блоки получают `unmapped/UNKNOWN_DOCUMENT_ROLE`, поэтому
неподтверждённое назначение документа также не открывает requirement mapping.

`data/goldenset/v1/quote_001.docx` намеренно содержит все опасные совпадения:
гарантию, число портов, требование декларации, запрет эквивалента и дату
поставки. Эталон `quote_001.expected.json` требует ноль требований, ноль mapped
блоков и сохранённый provenance каждого фрагмента. Автоматическое определение
роли, а также извлечение цены и условий КП в `Quote` остаются за отдельными
срезами; при неизвестной роли маппинг не запускается.

## Полнота покрытия требований (двадцать девятый срез S4, 2026-09-16)

Найденные требования и полнота документа теперь разделены. Каждый автоматический
`FactMappingResult` содержит `CompletenessAssessment(status=UNKNOWN)`, включая
полностью mapped и пустой результат. Маппер не может доказать, что extractor не
потерял блок или что неизвестный ему шаблон не содержал обязательный hard gate.

Review полноты привязан к объявленному scope, точным `source_document_ids`,
reviewer, timezone-aware времени и review reference. Для каждого `unmapped`-блока
сохраняется исходный текст/provenance и одно решение: существенное неразобранное
требование, не-требование или обоснованное исключение из scope. `PASS` требует
роли `TENDER_REQUIREMENTS`, хотя бы одного формализованного `Requirement`, решения
по всем unmapped-блокам и отсутствия существенного неразобранного требования.
Одни только срок поставки или режим эквивалента положительный gate не открывают.
`FAIL` указывает на такой
точный блок. Для `SUPPLIER_QUOTE` и `UNKNOWN` полнота требований ТЗ остаётся
`UNKNOWN`.

`evaluate_document_mapping` подключает этот gate к проверке кандидата: известный
mandatory `FAIL` сохраняется, а любой потенциально положительный результат при
`completeness=UNKNOWN|FAIL` становится `NEEDS_CLARIFICATION`. `COMPLIANT`
возможен только после review со статусом `PASS`. Ручной S1 сохраняет свои явно
подтверждённые проверки, но не получает автоматический `PASS` полноты задним
числом. Решения — [ADR-0018](../adr/0018-document-requirement-completeness.md) и
[ADR-0020](../adr/0020-completeness-gates-document-compliance.md).

## Persisted completeness review (тридцатый срез S4, 2026-09-16)

Для одного уже сохранённого native-документа ТЗ оператор может создать immutable
review snapshot. Сервер повторно сверяет SHA-256 source bytes, берёт persisted
`ExtractionResult` и сам строит `FactMappingResult`; extraction, requirements,
текст и provenance из клиентского payload не принимаются. Snapshot связывает
source ID/SHA/role, полный extraction, mapping с исходным `UNKNOWN`, версию
mapper и threshold единым canonical `evidence_sha256`.

Отдельная роль `COMPLETENESS_REVIEWER` записывает единственное решение
`PASS | FAIL | UNKNOWN`. Клиент ссылается на digest и индексы показанных
`unmapped`-блоков, а сервер восстанавливает полные review evidence и повторно
валидирует доменные инварианты. Reviewer ID, timezone-aware время и reference
берутся из аутентифицированного principal и сервера. Self-review, второе решение,
stale digest и изменённый idempotent replay запрещены.

`PASS` доступен только для полного native extraction без unresolved reasons, при
наличии хотя бы одного формализованного требования, решении по всем unmapped и
отсутствии `MATERIAL_REQUIREMENT`. `FAIL` обязан указать material-блок.
Недостаточное evidence сохраняется как reviewed `UNKNOWN` и не становится
допуском. Snapshot/decision, audit и receipt tenant-scoped и append-only;
PostgreSQL применяет RLS/FORCE RLS и composite tenant foreign keys.

`/completeness-review` — server-rendered внутренний reviewer UI. Он показывает
exact digest, извлечение, requirements, unmapped и provenance, не предвыбирает
решения и после terminal decision становится read-only. Bearer остаётся только
на сервере Next.js. До появления настоящей session auth этот UI разворачивается
отдельно с одним reviewer token и не смешивается с operator BFF.

Срез не покрывает OCR derivatives, ZIP/embedded media, комплект из нескольких
файлов и автоматическое включение review в case ingestion. Persisted `PASS`
одного документа не доказывает полноту всей закупки и не разрешает
`PARTICIPATE`. Полный trust boundary — в
[ADR-0021](../adr/0021-persisted-document-completeness-review.md).

## Persisted-роль документа (восьмой срез S4, 2026-09-13)

Клиент обязан передать `document_role` отдельным multipart-полем при
`POST /v1/documents`. FastAPI разбирает его как `DocumentRole` до вызова storage;
пропущенное или постороннее значение даёт `422`. Роль не извлекается из байтов,
имени или текста документа и потому не может быть изменена недоверенным внешним
содержимым.

PostgreSQL хранит роль в immutable tenant-scoped строке `documents` и проверяет
множество значений через `ck_documents_role_allowed`. Миграция `20260913_01`
заполняет прежние строки значением `UNKNOWN`: исторические документы нельзя
доказуемо переименовать в ТЗ или КП. После backfill server default снимается,
поэтому новые прямые записи без роли отклоняются БД.

Публичный `DocumentRecord` возвращает сохранённую роль. Она также записывается в
basis события `document.stored` и включена в digest идемпотентного запроса вместе
с именем, MIME и SHA-256 байтов. Один ключ нельзя повторно применить к тем же
байтам с другой ролью. RLS, append-only trigger и запрет выдачи исходных байтов
сохраняют прежние границы хранения.

## Локальный PP-OCRv5 для русских сканов (девятый срез S4, 2026-09-13)

Production runtime подключает lazy `PaddleOcrRunner`: PaddleOCR 3.7.0,
`PP-OCRv5_server_det` и `eslav_PP-OCRv5_mobile_rec`, язык `ru`, коррекция
ориентации/искажения страницы и строки. Выбор обоснован в
[ADR-0010](../adr/0010-local-russian-ocr.md); проверенные факты рынка записаны в
[research log](../research/07-research-log.md).

Перед inference API получает байты через отдельный tenant-scoped внутренний
метод, сверяет их SHA-256 с immutable snapshot и передаёт только validated PDF.
Отдельный лимит — 200 страниц. Один lazy pipeline защищён lock, чтобы параллельные
HTTP-запросы не использовали один inference object конкурентно. Временный PDF
удаляется в `finally`, наружу не передаётся ни файл, ни распознанный текст.

Каждая строка PaddleOCR становится `OcrCandidate` с `page`, прямоугольным bbox и
официальным `rec_score`. Общий builder применяет порог `0.75`; слабые строки не
становятся фактами, а пустой итог остаётся `UNKNOWN/OCR_REQUIRED`. Некорректный
envelope движка даёт безопасный `503 ocr_unavailable`, неподдержанный источник —
`422 ocr_source_unsupported`. Клиент не может выбрать или подменить engine.

Зависимости вынесены в extra `ocr`. Для локальной разработки:

```powershell
uv sync --extra dev --extra ocr
$env:RUN_PADDLE_OCR_INTEGRATION = "1"
uv run pytest tests/integration/test_paddle_ocr.py -q
```

Реальный regression строит raster-only PDF с русскими требованиями и проверяет
путь PDF → PP-OCRv5 → confidence/provenance → `Requirement`. Для
закрытого контура модели предзагружаются в `PADDLE_OCR_MODEL_ROOT`; ожидаются
каталоги `PP-LCNet_x1_0_doc_ori`, `UVDoc`, `PP-LCNet_x1_0_textline_ori`,
`PP-OCRv5_server_det`, `eslav_PP-OCRv5_mobile_rec`. Репрезентативный набор
реальных разрешённых сканов и калибровка порога остаются обязательными до
production-допуска.

## Калибровка confidence (десятый срез S4, 2026-09-13)

`calibrate_ocr_threshold` принимает типизированные `OcrCalibrationSample`:
у каждого снимка есть уникальные `sample_id`, SHA-256, ручные ожидаемые строки с
номером страницы и сырые `OcrCandidate` с confidence/provenance. Повтор source
digest запрещён, чтобы одна копия файла не раздувала объём evidence.

Для каждого наблюдаемого confidence и базового `0.75` отчёт считает TP, FP, FN,
precision и recall. Текст нормализуется только по Unicode, регистру и пробелам;
цифры и пунктуация сохраняются, поэтому ошибка «24 → 36» считается false positive.
Рекомендуется самый низкий порог с максимальным recall, только если FP равен нулю
и recall не ниже заданного минимума. По умолчанию нужно минимум 20 размеченных
строк и recall `0.9`: меньшая выборка даёт `UNKNOWN/INSUFFICIENT_LABELS`, а
достаточная выборка без безопасного порога — `FAIL/NO_SAFE_THRESHOLD`.

Opt-in integration benchmark строит один трёхстраничный raster-only PDF: чистую
страницу, поворот на 2,5° и низкоконтрастную страницу с blur. PP-OCRv5 распознал
все шесть строк, передал bbox/confidence и на этой синтетике подтвердил `0.75` при
recall `1.0` и нуле FP. Минимум в тесте явно снижен до шести строк; этот результат
проверяет механизм и устойчивость, но не даёт production-калибровку без
разрешённой размеченной выборки реальных закупочных документов.

## Запуск разрешённого набора (одиннадцатый срез S4, 2026-09-13)

Production-калибровка запускается только локально и только из manifest схемы
`ocr-calibration-v1`. Manifest содержит `dataset_id`, ссылку на основание обработки
`authorization_reference`, идентификатор разметчика, timezone-aware `labeled_at`,
явные параметры gate и непустой список образцов. Для каждого образца задаются
уникальные `sample_id`, SHA-256 исходных байтов, безопасный относительный путь к
PDF и **полная** ручная разметка строк с номерами страниц. Само наличие строки
`authorization_reference` не выдаёт разрешение: оператор обязан указать уже
существующее основание, применимое к этому набору.

Пример структуры (значения-заполнители нужно заменить):

```json
{
  "schema_version": "ocr-calibration-v1",
  "dataset_id": "approved-procurement-scans-v1",
  "authorization_reference": "DPA-or-ticket-reference",
  "labeled_by": "reviewer-id",
  "labeled_at": "2026-09-13T12:00:00+03:00",
  "engine": "paddleocr/3.7.0:PP-OCRv5-ru",
  "minimum_expected_lines": 20,
  "minimum_recall": 0.9,
  "baseline_threshold": 0.75,
  "samples": [
    {
      "sample_id": "scan-001",
      "source_file": "pdf/scan-001.pdf",
      "source_sha256": "<64 lowercase hex characters>",
      "expected": [
        {"page_number": 1, "text": "точная строка ручной разметки"}
      ]
    }
  ]
}
```

Файлы набора следует держать под `samples/private/`, который исключён из Git.
Отчёт также содержит чувствительный распознанный текст и сохраняется в игнорируемый
`data/`, например:

```powershell
uv sync --extra dev --extra ocr
$env:PADDLE_OCR_MODEL_ROOT = "C:\path\to\approved\local-models"
uv run python -m procurement calibrate-ocr `
  samples/private/ocr-calibration/manifest.json `
  --output data/ocr-calibration/report-v1.json
```

До OCR runner сверяет digest, лимит 20 МиБ, PDF signature, число страниц и
отсутствие нативного текстового слоя. Разметка за пределами документа отклоняется.
Отчёт `ocr-calibration-report-v1` фиксирует SHA-256 точных байтов manifest, всю
разметку, сырые кандидаты с bbox/confidence и матрицы порогов; исходные пути в него
не входят. Файл публикуется целиком и не перезаписывается. Коды завершения пригодны
для fail-closed automation: `0=PASS`, `3=UNKNOWN`, `4=FAIL`, `2=ошибка входа или
runtime`. Наличие runner не меняет состояние допуска: без фактического отчёта на
разрешённом репрезентативном наборе порог остаётся неподтверждённым, а подключение
мониторинга заблокировано.

## Ручная разметка без самооценки OCR (двенадцатый срез S4, 2026-09-14)

Команда `prepare-ocr-labeling` принимает каталог, где PDF и будущие JSON-артефакты
лежат на одном уровне. Она проверяет каждый PDF теми же лимитами и raster-only
gate, запускает настроенный локальный PP-OCRv5 и атомарно создаёт
`ocr-labeling-draft-v1`:

```powershell
$env:PADDLE_OCR_MODEL_ROOT = "C:\path\to\approved\local-models"
uv run python -m procurement prepare-ocr-labeling `
  samples/private/ocr-calibration-real `
  --dataset-id approved-procurement-scans-v1 `
  --authorization-reference DPA-or-ticket-reference `
  --output samples/private/ocr-calibration-real/labeling-draft.json
```

У каждого образца draft есть `suggestions` с машинным текстом, confidence и bbox,
но отдельный `expected` изначально пуст. Reviewer сверяет PDF визуально, вручную
заполняет **полный** список `expected` с номерами страниц, включая строки, которых
нет в `suggestions`, и только затем меняет `review_status` каждого образца на
`CONFIRMED`. После завершения всего пакета на верхнем уровне задаются:

```json
{
  "review_status": "CONFIRMED",
  "reviewed_by": "reviewer-id",
  "reviewed_at": "2026-09-14T12:00:00+03:00"
}
```

Нельзя трактовать `suggestions` как готовую разметку или механически копировать их
без сверки: иначе false negative исчезнут из эталона и recall станет ложным.
Подтверждённый образец обязан содержать хотя бы одну ожидаемую строку; время review
timezone-aware и не может предшествовать генерации draft. Абсолютные пути, `..`,
повторные source digests/ID, страницы вне документа и подмена PDF отклоняются.

Финализация повторно читает каждый immutable PDF, сверяет SHA-256 и число страниц
и создаёт `ocr-calibration-v1` только при полном человеческом подтверждении:

```powershell
uv run python -m procurement finalize-ocr-labeling `
  samples/private/ocr-calibration-real/labeling-draft.json `
  --output samples/private/ocr-calibration-real/calibration-manifest.json

uv run python -m procurement calibrate-ocr `
  samples/private/ocr-calibration-real/calibration-manifest.json `
  --output samples/private/ocr-calibration-real/calibration-report.json
```

Manifest не содержит `suggestions`: calibration runner заново получает кандидаты
от зафиксированного engine. При этом manifest и report сохраняют
`labeling_draft_sha256`, поэтому решение связано с точными байтами проверенного
человеком пакета. Успех команды не является доменным `PASS`: draft остаётся
`UNKNOWN/HUMAN_REVIEW_REQUIRED`, а созданный manifest —
`UNKNOWN/CALIBRATION_NOT_RUN` до отдельного запуска калибровки. Неподтверждённый
пакет даёт `REVIEW_INCOMPLETE` и не создаёт manifest.

## ZIP-пакеты с PDF/DOCX/XLSX (тринадцатый срез S4, 2026-09-14)

`extract_document_bundle` принимает immutable внешний ZIP и раскрывает только
поддержанные участники `.pdf`, `.docx`, `.xlsx` в памяти. ZIP получает общий
SHA-256, а каждый `DocumentBundleMember` — нормализованный `archive_path`, byte
size, SHA-256, MIME и собственный `ExtractionResult`. Блоки продолжают ссылаться
на ID внешнего ZIP, а locator имеет форму:

```text
archive member "tables/spec.xlsx" :: Spec!A1
```

Так источник факта однозначно связывает внешний snapshot, конкретные байты
участника и ячейку/страницу/абзац. XLSX использует уже существующий безопасный
режим `openpyxl`: только cached/literal values, `keep_links=False`, формулы
исключаются и оставляют `UNKNOWN/FORMULAS_IGNORED`. Макросные `.xlsm/.xltm`,
`.docm` отклоняют весь пакет. Legacy `.xls` и прочие неизвестные форматы не
разбираются, остаются видимыми как `UNKNOWN/UNSUPPORTED_MEMBERS` и не дают текста.

До чтения участников проверяются лимиты внешнего файла, число ZIP entries, общий
expanded size и размер каждого файла. Запрещены абсолютные пути, `..`, пустые и
управляющие сегменты, Unicode/case-insensitive дубликаты, symlink и encrypted
entries. Вложенные ZIP/7z/RAR/TAR/GZip запрещены также по сигнатуре, а не только по
расширению. DOCX/XLSX являются разрешёнными OOXML-контейнерами, но обязаны пройти
свою внутреннюю проверку структуры; переименованный ZIP не принимается за Office.

Для локальной инспекции без persistence:

```powershell
uv run python -m procurement inspect-document-bundle `
  samples/private/incoming/tender.zip `
  --output samples/private/incoming/bundle-report.json
```

Полный отчёт содержит извлечённый текст и потому хранится в приватном каталоге;
stdout содержит только digest, статусы и счётчики. Полностью поддержанный пакет
возвращает exit `0/PASS`; наличие неизвестного участника, scan-only PDF или формул
даёт `3/UNKNOWN`; небезопасный пакет даёт `2` и не публикует частичный отчёт.

Граница среза: прямая загрузка XLSX уже работает через `POST /v1/documents`, но
внешний ZIP пока доступен как доменный и локальный workflow. Его tenant-scoped
API/persistence, immutable связь outer archive → member snapshots и отдельный OCR
scan-only PDF-участников требуют следующего ограниченного среза.

## Tenant-scoped ZIP API (четырнадцатый срез S4, 2026-09-14)

ZIP не маскируется под одиночный `DocumentRecord`, потому что его результат содержит
несколько независимых источников. Для него введён отдельный ресурс:

- `POST /v1/document-bundles` — multipart `file` + обязательный `document_role` и
  `Idempotency-Key`;
- `GET /v1/document-bundles/{bundle_id}` — метаданные внешнего ZIP и полный
  `DocumentBundleResult` без исходных байтов.

Tenant берётся только из проверенного bearer credential. Роль входит в request digest;
точный replay возвращает исходный snapshot, а повтор ключа с другим файлом, MIME,
именем или ролью даёт `409/version_conflict`. Чужой и отсутствующий ID неразличимы и
возвращают одинаковый `404/not_found`.

До persistence API полностью выполняет проверки из предыдущего раздела. Любой
`DocumentBundleRejected` становится безопасным `422` с типизированным code и не
создаёт bundle, audit event или receipt. `UNKNOWN` из-за `.xls`, формул или scan-only
PDF является допустимым честным результатом обработки и сохраняется как `UNKNOWN`,
но не повышается до `PASS`.

PostgreSQL-таблица `document_bundles` хранит immutable внешние байты, их размер и
SHA-256, доверенную роль и типизированный JSON member snapshots. CHECK-ограничения
связывают `result.source_document_id` с `bundle_id`, а `result.source_sha256` — с
точными байтами ZIP. Таблица защищена RLS и append-only trigger. В одной транзакции
создаются bundle, audit `document_bundle.stored` с digest результата и счётчиками
участников, а также idempotency receipt. API никогда не возвращает поле `content`.

Граница среза: результаты участников доступны через bundle API и пригодны для
маппинга нативно извлечённого текста. Отдельное создание OCR-производной версии для
конкретного scan-only PDF-участника ещё не реализовано и остаётся следующим срезом.

## OCR участника ZIP (пятнадцатый срез S4, 2026-09-15)

OCR запускается только для точного участника уже сохранённого tenant-scoped bundle:

- `POST /v1/document-bundles/{bundle_id}/members/{member_index}/ocr`;
- `GET /v1/document-bundles/{bundle_id}/members/{member_index}/ocr/latest`;
- `GET /v1/document-bundle-member-ocr/{ocr_id}`.

Индекс относится к порядку файлов в immutable `DocumentBundleResult`; directory
entries в него не входят. Перед запуском сервер заново получает outer ZIP через
внутренний tenant-scoped storage method и вызывает `read_document_bundle_member`.
Проверяются SHA-256 внешних байтов, безопасная структура ZIP, количество участников,
нормализованный archive path, MIME, размер и SHA-256 выбранного файла. Любое
расхождение считается внутренней потерей evidence, останавливает OCR и наружу даёт
только безопасный `500/internal_error`.

В OCR допускается исключительно `application/pdf` с нативным состоянием
`UNKNOWN/OCR_REQUIRED`. Неподдержанный файл или DOCX/XLSX получает
`422/ocr_source_unsupported`; PDF, которому OCR не требуется, —
`422/ocr_not_required`. Отсутствующий индекс, чужой bundle и отсутствующий bundle
неразличимы (`404/not_found`).

Идентичность производной — `<bundle_id>:member:<index>`, source SHA-256 относится к
точным распакованным PDF-байтам. Locator каждого принятого OCR-блока имеет вид:

```text
archive member "scans/spec.pdf" :: page 1 bbox [...]
```

Таблица `document_bundle_member_ocr_derivatives` хранит отдельные immutable версии с
FK на bundle, member index/path/digest, engine, threshold и typed `OcrDerivative`.
RLS и append-only trigger действуют на саму производную; result, audit
`document_bundle.member_ocr_stored` и idempotency receipt создаются одной
транзакцией. Точный replay возвращает первоначальную версию, а изменение threshold
или источника с тем же ключом даёт `409`. Persisted threshold ограничен шагом `0.01`
в соответствии с PostgreSQL `NUMERIC(3,2)`. Байты ZIP и PDF API не возвращает.

Пустой либо полностью отфильтрованный OCR остаётся `UNKNOWN/OCR_REQUIRED` и не
создаёт фактов. Следующая граница — калибровка этого же PP-OCRv5 workflow на
разрешённых размеченных закупочных сканах; до неё production confidence gate не
считается подтверждённым и мониторинг не запускается.

## Полнота DOCX с вложенными изображениями (шестнадцатый срез S4, 2026-09-15)

Нативный текст DOCX не доказывает полноту документа, если OOXML-пакет содержит
`word/media/*`: требования могут находиться только во вложенном изображении.
Извлекатель не пытается угадать назначение медиа и не объявляет такой документ
полностью обработанным. Он сохраняет безопасно извлечённые абзацы и таблицы с их
provenance, но возвращает `UNKNOWN/EMBEDDED_MEDIA_IGNORED`.

Правило получено при локальном прогоне 13 разрешённых реальных ТЗ: один DOCX
содержал около 2,9 тыс. символов нативного текста и JPEG размером более 8 МиБ, но
до guard ошибочно получал `PASS`. После исправления 9 DOCX дали 5 `PASS` и 4
`UNKNOWN` (два из-за внешних ссылок, два из-за embedded media). ZIP с DOCX,
detached-подписью `.sig` и PDF сохранил все три member snapshots и честно получил
`UNKNOWN`; legacy DOC и RAR остаются неподдержанными. Исходные документы и их
текст не входят в репозиторий, а regression использует только синтетический DOCX.

Этот срез проверяет нативный pipeline, но не является production-калибровкой OCR:
в наборе нет raster-only PDF с полной подтверждённой построчной разметкой.

## OCR связанных изображений DOCX (семнадцатый срез S4, 2026-09-15)

`extract_docx_media` не доверяет простому наличию `word/media/*`. Он читает
relationship XML без DTD/entity и создаёт source только для внутреннего image
relationship, ID которого реально используется в соответствующей Main Document,
Header или Footer части. Непривязанные ZIP entries игнорируются; external/missing,
неподдержанные и битые изображения остаются типизированными issues.
Абсолютная ссылка OPC `/word/media/...` допустима только внутри этой папки
пакета и без `..`; внешний URL или выход из папки отклоняется. На реальном
DOCX ЕИС это позволило корректно классифицировать связанный GIF как
`UNSUPPORTED_MEDIA_TYPE`, не выдавая OCR-source и не повышая статус документа.

Разрешены только PNG/JPEG. До OCR сверяются extension, Pillow format/verify,
SHA-256, лимиты количества и byte size, измерение не более 12000 px и площадь не
более 80 млн пикселей. Decompression bomb warning считается ошибкой. Media source
связан с SHA-256 внешнего DOCX, имеет собственные digest, размеры, archive path,
relationship locator и стабильный ID `<document_id>:media:<index>`; bytes помечены
`exclude=True` и не входят в JSON.

`PaddleOcrRunner` принимает `image/png` и `image/jpeg` после повторной проверки
формата, digest и лимитов. Для одиночного изображения официальный пустой
`page_index` нормализуется в image 1. OCR остаётся отдельной производной, locator:

```text
DOCX media "word/media/image1.jpeg" :: image 1 bbox 10,20,300,60
```

Локальный запуск с полным приватным отчётом:

```powershell
$env:PADDLE_OCR_MODEL_ROOT = "$env:USERPROFILE\.paddlex\official_models"
uv run python -m procurement ocr-docx-media `
  samples/private/incoming/spec.docx `
  --output samples/private/incoming/docx-media-ocr-report.json
```

CLI не выводит распознанный текст в stdout и не перезаписывает отчёт. На реальном
JPEG 9921×7016 размером 8,14 МиБ локальный PP-OCRv5 принял 95 блоков: minimum
confidence `0.827635`, mean `0.958760`; все locators получили media prefix, а
исходные image bytes отсутствуют в JSON. SHA-256 отчёта:
`559eeb242f6f8baececd9b8c01a046faa39881b8d096bdc56e0dc101e2fee4eb`.
Другой реальный PNG не прошёл Pillow verify и остался
`UNKNOWN/INVALID_IMAGE` без OCR-source.

Этот локальный контракт не объединяет OCR с нативными блоками; архитектурное решение —
[ADR-0011](../adr/0011-docx-embedded-media-ocr.md). Технический `PASS` при пороге
`0.75` не подтверждает production quality: до ручной полной разметки и calibration
report мониторинг остаётся заблокированным.

## Tenant-scoped DOCX-media OCR (восемнадцатый срез S4, 2026-09-15)

Для уже сохранённого DOCX доступны:

- `POST /v1/documents/{document_id}/media/{media_index}/ocr`;
- `GET /v1/documents/{document_id}/media/{media_index}/ocr/latest`;
- `GET /v1/document-docx-media-ocr/{ocr_id}`.

Перед inference API получает исходные bytes только через внутреннюю tenant-scoped
границу, сверяет digest с immutable metadata и повторно запускает безопасный
`extract_docx_media`. `media_index` должен указывать на реально используемый
внутренний PNG/JPEG relationship. Digest изображения, archive path, media type и
стабильный ID `<document_id>:media:<index>` повторно проверяются в repository перед
записью. Повреждённые bytes дают закрытый internal error, неподдерживаемый DOCX —
`422`, отсутствующий или чужой source — одинаковый `404`.

`document_docx_media_ocr_derivatives` хранит отдельную typed производную с
SHA-256 внешнего DOCX и изображения, но без исходных bytes. Таблица tenant-scoped,
append-only и защищена RLS/FORCE RLS; FK ведёт к `documents`. Производная, audit
`document.docx_media_ocr_stored` и idempotency receipt создаются атомарно. Exact
replay возвращает прежнюю запись, повтор ключа с другим threshold получает `409`.
Миграция — `20260915_01`.

API/persistence не повышает OCR-текст до подтверждённого факта и не меняет
production gate: ручная полная разметка разрешённых реальных сканов и calibration
report всё ещё обязательны до запуска мониторинга.

## Fail-closed visual review DOCX-media (девятнадцатый срез S4, 2026-09-15)

`docx-media-calibration-review-v1` связывает построчную визуальную разметку с
SHA-256 внешнего DOCX и exact media, `media_index`, archive path, размерами,
reviewer type, временем и authorization reference. Перед запуском те же immutable
bytes читаются повторно, а `extract_docx_media` заново доказывает внутренний OOXML
relationship и digest изображения. Подмена документа, media или пути отклоняется
до OCR.

Статусы review разделены:

- `AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION` разрешает вычислить наблюдаемые
  precision/recall, но итог всегда `UNKNOWN/HUMAN_REVIEW_REQUIRED`;
- `HUMAN_CONFIRMED` требует `reviewer_type=HUMAN` и отсутствие unresolved
  uncertainties; только тогда успешная калибровка может вернуть production
  threshold.

Локальный запуск:

```powershell
$env:PADDLE_OCR_MODEL_ROOT = "$env:USERPROFILE\.paddlex\official_models"
uv run python -m procurement calibrate-docx-media-review `
  samples/private/review.json `
  --output samples/private/calibration-report.json
```

Полный отчёт приватный и содержит expected/candidates; stdout показывает только
digest, статусы, счётчики и пути. На визуальной AI-разметке реального изображения
из 119 строк baseline `0.75` дал `TP=78`, `FP=17`, `FN=41`, precision `0.8211` и
recall `0.6555`. Ни один порог не удовлетворил одновременно `FP=0` и
`recall>=0.9`: внутренняя калибровка — `FAIL/NO_SAFE_THRESHOLD`, внешний gate —
`UNKNOWN/HUMAN_REVIEW_REQUIRED`. Высокий mean confidence исходного OCR поэтому не
считается доказательством качества.

## Локальное human review DOCX-media (двадцатый срез S4, 2026-09-15)

Страница `http://127.0.0.1:3000/ocr-review` принимает AI review JSON и его
исходный DOCX через браузерные file inputs. Обработка полностью client-side:
файлы не передаются в Next.js/FastAPI. Встроенный ограниченный ZIP-reader
извлекает только exact `source_media`, после чего Web Crypto сверяет SHA-256
DOCX и media, а браузер — размеры изображения. Файлы разрешено выбирать в любом
порядке: выбранный первым DOCX сохраняется в состоянии страницы и автоматически
проверяется после загрузки review JSON.

После проверки evidence интерфейс показывает масштабируемый чертёж, все
expected строки и каждую unresolved uncertainty. Любое изменение сбрасывает
финальное подтверждение. Новый JSON получает `HUMAN_CONFIRMED`, `reviewer_type`
`HUMAN`, timezone-aware время, пустой список uncertainties и сохраняет в method
SHA-256 родительского AI review и решения проверяющего. Исходный файл не
перезаписывается. Скачанный JSON остаётся входом существующей команды
`calibrate-docx-media-review`; human confirmation не повышает неудачную
калибровку до `PASS`.

Запуск UI:

```powershell
cd web
npm run dev
```

## Routing небезопасного OCR (двадцать первый срез S4, 2026-09-15)

`route-docx-media-ocr` принимает полный immutable calibration report. При
`FAIL/NO_SAFE_THRESHOLD` он отклоняет только local OCR method:

- disposition — `REJECT_LOCAL_OCR`;
- статус документа — `UNKNOWN`, а не `FAIL`;
- следующие действия — запросить нативный PDF/DWG либо подготовить отправку во
  внешнюю vision-модель.

Маршрут без настроенной внешней системы ничего не отправляет:

```powershell
uv run python -m procurement route-docx-media-ocr `
  samples/private/calibration-report.json `
  --output samples/private/ocr-routing.json `
  --at 2026-09-15T21:30:00+03:00
```

Для vision proposal одновременно обязательны `--vision-provider`,
`--vision-model`, `--vision-endpoint` и `--retention-policy-reference`. Полученный
draft фиксирует SHA-256 exact media, destination, prompt и response contract, но
всегда остаётся `APPROVAL_REQUIRED` с `send_allowed=false`. Это ещё не коннектор и
не разрешение на передачу файла; будущий исполнитель обязан повторно сверить
точные bytes и отдельное approval перед API-вызовом.

Реальный сложный чертёж получил `REJECT_LOCAL_OCR / LOCAL_OCR_NO_SAFE_THRESHOLD`.
Это снимает требование вручную подтверждать его 119 OCR-строк, но не превращает
отсутствующие данные в допуск: до нативного исходника или одобренного vision-пути
документ остаётся `UNKNOWN`.

## Гибридный discovery-поиск (двадцать второй срез S4, 2026-09-15)

Поиск отделён от проверки полноты и соответствия документа. `DocumentSearchEntry`
сохраняет tenant, SHA-256 документа, исходное имя, опциональное название,
нативные блоки и отдельно sourced vision-теги. Даже если DOCX в целом имеет
`UNKNOWN/EMBEDDED_MEDIA_IGNORED`, достоверно извлечённый абзац остаётся доступным
для discovery со своим native provenance. Это не снимает общий `UNKNOWN`.

Источники совпадения типизированы как `TITLE | FILENAME | NATIVE_TEXT |
VISION_TAG`. Название, имя и нативный текст дают `PASS` только для факта
поискового совпадения. Неподтверждённый AI vision-тег даёт `UNKNOWN`; human-
confirmed тег может дать discovery `PASS`, но никогда не становится обязательным
требованием или решением об участии. Сырой OCR автоматически в индекс не входит.

Manifest `vision-search-tags-v1` связан с tenant/document ID, SHA-256 DOCX,
`media_index`, exact archive path и SHA-256 изображения, моделью, producer,
timezone-aware временем, SHA-256 фиксированного безопасного prompt и SHA-256
исходного visual-review artifact. Перед использованием DOCX раскрывается заново:
relationship, media index, path и digest обязаны совпасть. Теги содержат locator,
confidence и review status.

Локальный запуск ничего не сохраняет и не отправляет во внешние API:

```powershell
uv run python -m procurement search-document `
  samples/private/specification.docx `
  --company-id demo-company `
  --query "кондиционирование" `
  --vision-tags samples/private/vision-search-tags.json
```

На реальном DOCX запросы «ремонт» и «выполнение работ» найдены в нативных
источниках, а «кондиционирование» — в имени, нативном тексте и AI vision-теге.
Код `GW-G140W/N1D3` найден только в AI-теге и потому имеет `UNKNOWN`. `General`
не найден: бренд нельзя вывести из кода модели без отдельного каталожного
evidence. Решение зафиксировано в
[ADR-0012](../adr/0012-hybrid-document-discovery.md). Persistence/API, полноценная
морфология, синонимы и ранжирование остаются следующими поисковыми срезами.

## Persisted search index и API (двадцать третий срез S4, 2026-09-15)

`document_search_indexes` хранит append-only версии `DocumentSearchEntry` с
tenant, собственным ID, FK на immutable source document, его SHA-256 и
timezone-aware временем. PostgreSQL применяет RLS/FORCE RLS, runtime-роль имеет
только `SELECT, INSERT`, а trigger запрещает `UPDATE/DELETE`.

`POST /v1/documents/{document_id}/search-indexes` принимает опциональные title и
`vision-search-tags-v1`. До записи сервер читает сохранённые bytes и extraction,
проверяет SHA-256 и полностью перестраивает entry. Для vision повторно
проверяются linked DOCX media index/path/digest. Индекс, audit
`document.search_index_stored` и idempotency receipt записываются одной
транзакцией; exact replay возвращает прежнюю версию, изменённая нагрузка с тем же
ключом конфликтует.

`GET /v1/document-search?query=...&limit=...` читает только последнюю версию
каждого документа текущего tenant и возвращает typed results/hits с provenance.
Исходные document/media bytes не входят в ответ. Чужой и отсутствующий source
одинаково дают `404`; RLS дополнительно блокирует межтенантное чтение.

Текущий bounded backend фильтрует до 200 последних typed entries в Python. Это
доказательный API-срез, но ещё не production-scale полнотекстовый индекс,
синонимы или ранжирование. Решение описано в
[ADR-0013](../adr/0013-immutable-document-search-index.md).

## Пользовательский поиск (двадцать четвёртый срез S4, 2026-09-16)

Страница `/document-search` вызывает persisted search API из server component.
`PROCUREMENT_API_TOKEN` остаётся в server-only модуле и не попадает в browser
JavaScript или query string; пользовательский запрос передаётся URL-encoded и
ограничен 200 символами. Исходные document/media bytes не запрашиваются.

Карточка результата всегда показывает immutable `document_id`, общий status и
все hits с точным locator, extractor и confidence. Источники визуально разделены
на название, имя файла, нативный текст и чертёж. Неподтверждённый vision-тег
остаётся `UNKNOWN` с явной пометкой AI suggestion; human-confirmed vision evidence
отмечается отдельно. Discovery-совпадение прямо не называется соответствием или
решением об участии.

Маршрут различает начальное, загрузочное, пустое и ошибочное состояния. Ссылки
соединяют его с экраном дел и локальной OCR-review страницей. Acceptance evidence:
ESLint и production build Next.js 16.3.4 прошли; синтетический server-side smoke
вернул страницу и все 9 CSS/JS assets с HTTP `200`, одновременно отобразив native
`PASS` и AI vision `UNKNOWN`. Временный fake API после проверки удалён.

## Доказательный model→brand (двадцать пятый срез S4, 2026-09-16)

`model-brand-catalog-v1` — immutable tenant-scoped reviewed manifest. Он содержит
catalog ID, reviewer/approval reference, timezone-aware creation time и записи с
exact model, canonical brand и полуоткрытым effective interval. Evidence каждой
записи — официальный HTTPS source, SHA-256 точного документа, locator и время
получения. JSON bounded до 2 МиБ, запрещает неизвестные поля, duplicate keys,
`NaN`/`Infinity` и naive datetime.

Lookup нормализует Unicode, регистр и пробелы, но сохраняет пунктуацию модели.
Prefix/fuzzy matching запрещён. Нет записи, другой tenant, неактивный interval
или несколько активных брендов для одной модели дают `UNKNOWN` без выбранного
brand.

При brand-query discovery ищет exact model в title/filename/native blocks и
отдельных vision tags. `MODEL_BRAND_CATALOG` hit содержит provenance модели и
полный официальный catalog evidence. Нативная модель даёт discovery `PASS`;
AI-suggested модель остаётся `UNKNOWN`, даже если catalog relation подтверждена.
Hit не является проверкой соответствия, эквивалентности или допуска.

CLI принимает `--model-brand-catalog` и timezone-aware `--at`; каталог и документ
не загружаются и не сохраняются. Проверенное официальное руководство содержит
`GW-G140/N1A1`, но не подтверждает exact `GW-G140W/N1D3`, поэтому спорная связь
не создана. Persistence/API и управляемая запись reviewed manifest реализованы в
следующем датированном срезе.
Решение — [ADR-0014](../adr/0014-evidence-backed-model-brand-catalog.md).

```powershell
uv run python -m procurement search-document `
  samples/private/specification.docx `
  --company-id demo-company `
  --query "General Climate" `
  --model-brand-catalog samples/private/model-brand-catalog.json `
  --at 2026-09-16T12:00:00+03:00
```

## Persisted reviewed model→brand (двадцать шестой срез S4, 2026-09-16)

`model_brand_catalogs` хранит append-only tenant-scoped версии полного
`model-brand-catalog-v1`. Колонки tenant/catalog ID согласованы с typed JSON;
RLS/FORCE RLS и runtime grants разрешают только `SELECT/INSERT`, trigger запрещает
`UPDATE/DELETE`.

Публичная публикация выполняется только через model-brand review
proposal/decision: `APPROVED` атомарно создаёт каталог, audit events и
idempotency receipt после повторной сверки evidence. Прямой
`POST /v1/model-brand-catalogs` удалён, поэтому reviewer также не может обойти
разделение автора и принимающего решение. `GET /v1/model-brand-catalogs/latest`
возвращает последнюю доступную утверждённую версию текущего tenant на
timezone-aware `effective_at`; чужая/отсутствующая версия не раскрывается.

`GET /v1/document-search` фиксирует `effective_at`, загружает соответствующий
последний каталог и использует его в exact brand discovery. UI различает
`MODEL_BRAND_CATALOG`, показывает catalog ID, модель, источник модели и официальный
source title/locator. Native model может дать discovery `PASS`; AI suggestion
остаётся `UNKNOWN`. Это не проверка соответствия или допуск.

Manifest содержит reviewed SHA-256 официального документа, но этот срез не
принимает и повторно не сверяет его exact bytes. Source-artifact ingestion
реализован следующим датированным срезом; полноценный review UI/workflow остаётся
открытой границей. Решение —
[ADR-0015](../adr/0015-immutable-reviewed-model-brand-catalog.md).

## Official-source artifact ingestion (двадцать седьмой срез S4, 2026-09-16)

`model_brand_source_artifacts` хранит exact PDF bytes до 20 МиБ вместе с tenant,
server-generated ID/times, HTTPS source URL, title, filename, media type, size и
SHA-256. Таблица append-only, защищена RLS/FORCE RLS; runtime может только читать
свой tenant и вставлять новые версии.

`POST /v1/model-brand-source-artifacts` проверяет filename/media type/PDF signature,
вычисляет digest и атомарно пишет artifact, audit и idempotency receipt. Exact
replay возвращает прежнюю metadata, изменённый payload получает `409`. GET по ID
не возвращает source bytes; чужой и отсутствующий ID одинаково дают `404`.

API catalog evidence обязано содержать `source_artifact_id`. Repository повторно
вычисляет SHA-256 persisted bytes в транзакции catalog insert и сверяет ID, title,
URL, digest и `retrieved_at`. Любое расхождение даёт `422` без частичной записи.
Локальный CLI сохраняет backward-compatible manifest без artifact ID, но такой
manifest нельзя persisted-утвердить до ingestion.

Upload не выполняет сетевой fetch и сам по себе не доказывает происхождение bytes
с указанного URL; reviewer отвечает за эту связь. Автоматический fetch отложен до
SSRF/redirect allowlist и retention policy. Решение —
[ADR-0016](../adr/0016-immutable-model-brand-source-artifacts.md).

## Role-aware model→brand review (двадцать восьмой срез S4, 2026-09-16)

Bearer API key хранит `OPERATOR` или `MODEL_BRAND_REVIEWER`; authentication
function возвращает роль вместе с tenant/actor, поэтому payload не может повысить
authority. Existing keys получают fail-closed `OPERATOR`. Для локального reviewer
ключа bootstrap принимает `--access-role MODEL_BRAND_REVIEWER`.

Proposal API создаёт immutable `DRAFT` с server tenant/submitter/time и уже при
submit повторно сверяет source artifacts. Decision API принимает только
`APPROVED/REJECTED`, требует reviewer role и запрещает автору решать собственный
draft. Approval повторяет exact-bytes verification и атомарно публикует catalog;
rejection оставляет catalog отсутствующим. Decision, audit и receipt append-only.

`GET /v1/model-brand-reviews?limit=...` возвращает derived state только текущего
tenant. Второе или изменённое terminal decision конфликтует. Публичного прямого
catalog POST больше нет: единственный путь публикации проходит через независимые
proposal и terminal decision. `GET /v1/model-brand-catalogs/latest` остаётся
read-only путём получения утверждённой версии. Решение —
[ADR-0017](../adr/0017-role-aware-model-brand-review.md).

## Evidence manifest комплекта документов (сороковой срез S4, 2026-09-17)

Несколько файлов ТЗ больше не требуется неявно сводить в один source. Оператор
может явно зафиксировать упорядоченный комплект из 2–10 уже сохранённых native
completeness review snapshots. Каждый member содержит exact review/evidence,
source document/SHA и mapper projection; полный extraction остаётся связанным
через digest выбранного review и не копируется в manifest.

Перед записью repository повторно сверяет tenant, source bytes, extraction и
роль `TENDER_REQUIREMENTS`; duplicate source через другой review запрещён.
Logical JSON size всех выбранных snapshots проверяется до materialization и не
может превышать 20 МиБ. Manifest, ordered members, audit и actor-bound receipt
записываются атомарно в append-only RLS/FORCE RLS таблицы. Deferred constraint
trigger запрещает неполные rows и подмену source/mapper projection.

API предоставляет только OPERATOR POST и tenant-scoped GET by ID. POST читает
strict JSON потоково до 16 КиБ; ответы `no-store`. Manifest всегда остаётся
`UNKNOWN/MULTI_DOCUMENT_REVIEW_REQUIRED`: он доказывает состав, но не полноту.
Автоматический latest/PASS, объединение конфликтующих фактов, terminal review,
case ingestion и UI оставлены следующему отдельному срезу. Решение —
[ADR-0024](../adr/0024-document-set-evidence-manifest.md).

## Терминальный review комплекта документов (сорок первый срез S4, 2026-09-17)

Отдельный reviewer с ролью `COMPLETENESS_REVIEWER` проверяет exact manifest как
единый заявленный комплект. Evidence endpoint серверно восстанавливает каждый
constituent snapshot вместе с его terminal single-document decision и digest;
клиент не может заменить эти проекции или удалить server findings.

Решение содержит ordered attestation для каждого member, оценку inventory,
совместную оценку документов и findings с точными ссылками на source blocks либо
mapping fields. Разные непустые сроки поставки автоматически создают
`UNRESOLVED_CONFLICT`. `PASS` требует constituent `PASS`, полного покрытия
members, подтверждённого inventory и отсутствия findings. Подтверждённый
существенный пропуск/отсутствующий документ даёт `FAIL`; все недоказанные пробелы
и конфликты остаются `UNKNOWN`.

Reviewer независим от автора manifest и создателей constituent snapshots.
Repository при чтении и записи заново проверяет tenant, bytes/extraction, exact
decision digests и вычисленные findings. Decision, member attestations, audit и
receipt атомарны и append-only; RLS/FORCE RLS скрывает чужой tenant. API принимает
strict JSON до 256 КиБ и возвращает только `no-store` responses.

Срез не объединяет mappings, не выбирает latest review и не передаёт результат в
case/compliance/sourcing. Решение —
[ADR-0025](../adr/0025-terminal-document-set-completeness-review.md).

## UI review комплекта документов (сорок второй срез S4, 2026-09-17)

Внутренний маршрут `/document-set-review?manifest_id=<exact-manifest-id>`
рендерит только явно выбранный manifest и использует выделенный server-only
`PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN`. List/latest и fallback на operator
credential отсутствуют; bearer и API URL не передаются браузеру. Экран показывает
полный exact evidence, server findings и terminal decision, если оно уже создано.

При отправке server action повторно загружает evidence и отклоняет изменившийся
manifest digest либо constituent review/decision reference. `PASS` выводится
только из свежего evidence при `PASS` каждого constituent, полном
`REVIEWED_IN_SCOPE`, подтверждённом inventory, закрытом cross-document check и
нулевом числе server findings; остальные незавершённые случаи остаются
`UNKNOWN`. Первый вариант экрана не создавал `FAIL` из свободного текста;
следующий срез добавил отдельный typed editor, описанный ниже. Production
sessions/RBAC/MFA остаются отдельной границей.

## Typed FAIL editor комплекта документов (сорок третий срез S4, 2026-09-17)

Reviewer UI поддерживает оба доменно допустимых пути агрегатного `FAIL`: уже
принятый constituent `FAIL` либо новый confirmed reviewer finding. Для нового
finding разрешены только `CONFIRMED_MATERIAL_OMISSION` и
`CONFIRMED_MISSING_DOCUMENT`; reviewer выбирает source block из exact evidence,
а server action сам создаёт finding ID и origin. Произвольный ID, server origin,
mapping path или block вне свежего snapshot отклоняются.

Перед выводом статуса action повторно получает evidence, сверяет manifest и все
ordered constituent decision references, затем проверяет source-block range и
assessment contradictions. Server и reviewer findings объединяются для
`OPEN_ISSUES | CHECKED_NO_OPEN_ISSUES`; missing document несовместим с confirmed
inventory. Constituent `FAIL` не требует выдумывать дополнительный finding, а
`UNRESOLVED_CONFLICT | UNRESOLVED_GAP` не превращаются в `FAIL`. Первая UI-версия
ограничена одним новым confirmed finding за terminal decision; API сохраняет
полный typed контракт.
## Server-managed AI transfer worker: S48 local pilot boundary

Срез S48 добавляет server-managed first-chunk worker поверх persisted exact
request/approval. Worker повторно валидирует claim, source/chunk binding, exact
bytes и 15-minute approval expiry по server/database clock; после durable claim
делает ровно одну попытку без retry или redirect. Legacy `analyze-tz-ai` теперь
отключён: он не извлекает документы и не вызывает provider.

Для local pilot используется только явный env-gated adapter:
`AI_TRANSFER_RAW_ROOT_KEK_B64`, `AI_TRANSFER_RAW_KEK_ID` и
`AI_TRANSFER_LOCAL_PILOT_ENABLED=1`. Это HKDF/AES-GCM pilot implementation, а не
production KMS. Complete response сохраняется как encrypted raw blob ровно 720
UTC-часов; execution detail раскрывает только безопасные metadata/digests
reviewer/auditor, а ciphertext и wrapped DEK удаляются purge после immutable
deletion receipt. Production capture остаётся disabled до managed KMS/rotation и
проверяемых backup/WAL/restore retention evidence.
## S49: materialization AI requirement result после capture (историческая граница)

Этот раздел фиксирует исходный single-chunk контракт S49. Его multi-chunk
ограничения и старые gate numbers superseded последующими разделами S50–S60;
текущий объединённый контракт описан в S60.

После terminal `SUCCESS` transport worker отдельным server-managed шагом
материализует только уже сохранённый single-chunk response. Шаг выполняется без
сетевого вызова и без retry: decrypt raw доступен только внутри bounded
materialization transaction, а в очередь reviewer попадает raw-free
`persisted-ai-requirement-run-v2` с typed candidates, provenance и digest chain.
`completeness` остаётся `UNKNOWN`, пока отдельный reviewer не подтвердит полноту.

Ресурс materialization доступен owning operator через `POST
/v1/ai-transfer-executions/{execution_id}/requirement-materializations`; повторный
вызов возвращает тот же append-only результат. Multi-chunk capture и response с
невалидными candidate evidence получают terminal `REJECTED` receipt и не создают
run. Reviewer queue совместима с persisted v1 и v2, но ни один queue endpoint
не раскрывает raw provider response; raw остаётся отдельным reviewer/auditor-only
ресурсом с no-store и 30-дневным encrypted retention.

Срез закрыт targeted `146 + 17` тестами и recent `134` тестами; полный no-DB
набор собрал `843` теста (`760 passed`, `83 PostgreSQL/integration skipped`),
fresh PostgreSQL 16 gate — `82 passed`, doctest — `10 passed`. Mypy по 55
source-файлам, Ruff, `uv lock --check`, Alembic head `20260917_08` и offline SQL
прошли; Astra final review — `APPROVED`. Global Ruff format drift в 40
pre-existing несвязанных файлах не объявляется исправленным, формат S49-файлов
проверен отдельно. Production остаётся заблокирован до внешних managed
KMS/rotation и backup/WAL/restore retention evidence, а multi-chunk остаётся за
пределами поддержанного контракта.

## S50: preparation-only multi-chunk aggregate contract

Pure-domain граница теперь умеет проверять результат отдельного successful chunk
по его ordinal, exact request digest и подмножеству source blocks. Полный
`ai-transfer-requirement-batch-v1` строится только при наличии всех ordered
chunk-results одного execution; missing/reordered chunk, повтор durable evidence,
другая source identity или изменённая derived projection отклоняются даже при
пересчитанном внешнем digest.

Aggregate не содержит provider response/ciphertext и всегда остаётся
`UNKNOWN` до независимого review. Этот контракт не включает второй сетевой
dispatch, persistence, API или reviewer queue: действующие S48/S49 gates всё ещё
fail-closed ограничивают исполнение и materialization первым chunk. Их расширение
требует отдельного SQL/RLS/recovery среза и не выводится из наличия pure модели.

## S51: durable ordered next-chunk claim

Persistence теперь может записать permanent claim следующего chunk, но только
через внутренний no-network boundary. PostgreSQL сам проверяет contiguous ordinal,
актуальное 15-minute approval и exact успешную историю всех предыдущих chunks,
включая terminal receipt и encrypted raw metadata. Advisory lock и уникальные
ключи дают одного победителя при concurrency; любой незавершённый или
неуспешный предыдущий chunk навсегда останавливает batch.

Execution loader повторно валидирует всю ordered history и наружу возвращает
только текущий последний claim/receipt. Raw metadata не может быть склеена с
другим ordinal: без terminal receipt текущего claim API возвращает
`raw_response = null`.

Срез не подключает `claim_next_ai_transfer_dispatch` к worker, CLI или public
API. Поэтому второй сетевой вызов по-прежнему невозможен в поддержанном workflow;
следующая граница должна отдельно реализовать один generic worker invocation для
уже committed next claim и per-chunk materialization persistence.

## S52: один worker invocation следующего chunk

Внутренний `NextChunkAiTransferWorker` связывает S51 claim boundary с уже
проверенным exact-byte transport: permanent claim следующего contiguous ordinal
commit-ится до сети, после чего выполняется максимум одна попытка. Worker не
запускает цикл по batch и не имеет public route/CLI; очередной invocation возможен
только после exact `SUCCESS/VALIDATED_RESPONSE` предыдущего chunk с complete raw
capture.

Успешный next-chunk outcome помечается `requirement_batch_pending=true` и не
вызывает single-chunk materializer S49. Это явное `UNKNOWN`-подобное техническое
состояние: оно подтверждает capture, но не полноту требований и не создаёт
reviewer-visible run. Ошибка, timeout или crash после permanent claim запрещают
повтор и последующие ordinals. Полный persisted aggregate и reviewer snapshot
для multi-chunk остаются выключены до отдельного среза.

Encrypted raw metadata теперь допускает ordinal `1..9999` через миграцию
`20260917_10`, сохраняя unique `(company_id, execution_id, ordinal)` и exact FK
на terminal receipt. Финальный gate: `765` no-DB и `85` fresh PostgreSQL тестов;
production prerequisites не изменены.

## S53: persisted chunk results и reviewer snapshot v3

После successful capture внутренний storage boundary может без сети
материализовать все доступные chunks. Каждый raw-free result сохраняется отдельно
и exact-связан с claim, receipt, encrypted raw metadata, source и parser version.
Если batch ещё неполон, возвращается только ordered progress; reviewer run не
создаётся и полнота не повышается.

Только полный ordered набор размером ровно `admission.chunk_count` образует
`ai-transfer-requirement-batch-v1` и атомарный
`persisted-ai-requirement-run-v3`. Aggregate содержит typed candidates,
unresolved coverage и digest chain всех chunks, но не provider transcript,
ciphertext или ключи. Его `completeness_status` остаётся `UNKNOWN` до отдельного
human review. SQL/RLS запрещают orphan run, пропуск/reorder chunk result,
cross-tenant доступ и мутацию.

Срез не запускает следующий chunk автоматически и не публикует новый recovery
endpoint. Невалидный semantic chunk блокирует aggregate; durable multi-chunk
rejection receipt и orchestration полного batch остаются следующей границей.
Проверки: `765` no-DB, `86` fresh PostgreSQL и `10` doctest.

## S54: terminal semantic rejection и batch recovery

Semantic-invalid ответ уже успешно captured chunk теперь получает отдельный
immutable raw-free rejection receipt. Он exact-связан с request, claim, terminal
receipt и encrypted raw metadata, сохраняет `INVALID_CANDIDATE_EVIDENCE` и
остаётся воспроизводимым после recovery без повторного decrypt или provider
вызова. Успешный transport receipt не меняется: semantic rejection — отдельный
слой обработки результата, а не подмена факта доставки.

PostgreSQL запрещает одновременно хранить result и rejection одного
`(tenant, execution, ordinal, parser_version)`, запрещает aggregate после
rejection и блокирует claim следующего ordinal. Повреждение ciphertext,
provenance, provider envelope или digest chain не превращается в semantic
rejection и остаётся integrity error.

Owning operator может вызвать только no-network recovery через `POST
/v1/ai-transfer-executions/{execution_id}/requirement-batch-materializations`.
Ответ показывает `PENDING`, полный `MATERIALIZED` run или typed `REJECTED`; raw
provider bytes не раскрываются. Route не запускает следующий chunk, не выдаёт
approval и не создаёт автоматический batch-loop. Gate: `765` no-DB, `87` fresh
PostgreSQL и `10` doctest; Alembic head — `20260917_12`.

## S55: post-capture materialization внутри one-attempt worker

Server-prepared dispatch включает immutable `chunk_count`, поэтому worker после
complete successful capture выбирает правильную raw-free materialization
границу. Single-chunk execution создаёт persisted run v2; multi-chunk execution
материализует доступные ordered results, оставляет `PENDING` до полного покрытия,
создаёт run v3 после последнего chunk либо возвращает typed terminal rejection.

Materialization начинается только после commit receipt/raw capture. Ошибка этого
шага не меняет transport outcome и не разрешает повторный HTTP-вызов; recovery
выполняется S54 endpoint без сети. Один invocation по-прежнему соответствует
ровно одному permanent claim и максимум одной provider attempt. Автоматического
claim следующего ordinal, batch-loop и public dispatch API нет. Gate: `767`
no-DB, `87` fresh PostgreSQL, `10` doctest; Alembic head `20260917_12`.

## S56: bounded coordinator одного следующего шага

Внутренний `AiTransferBatchCoordinator` по durable execution state выполняет не
более одного шага: first chunk, ровно один next chunk, финальный no-network
recovery либо terminal stop. Permanent claim без receipt никогда не повторяется;
failed/unknown transport также останавливает execution.

Coordinator не запускает цикл и не обходит exact approval. Один invocation
означает максимум один новый claim и один provider HTTP-вызов через существующий
one-attempt worker. Результат raw-free и типизирован как `PENDING`,
`MATERIALIZED`, `REJECTED` или `STOPPED`. Public API/CLI для запуска coordinator
не добавлены. Gate: `770` no-DB, `87` fresh PostgreSQL, `10` doctest; схема и
Alembic head остаются `20260917_12`.

## S57: явный local-pilot coordinator step

Env-gated команда `dispatch-approved-ai-transfer` выполняет один
`AiTransferBatchCoordinator.run_once`. Повторные ручные запуски могут по одному
продвигать ordered chunks, но один запуск никогда не выполняет больше одного
provider вызова. Terminal execution получает recovery/stop без сети.

CLI печатает только безопасные IDs и typed status; secret и provider body не
выводятся. Local-pilot opt-in, database, API key и pilot KEK по-прежнему
обязательны. Это не production scheduler и не public dispatch API. Gate: `772`
no-DB, `87` fresh PostgreSQL и `10` doctest; Alembic head `20260917_12`.

## S58: конкурентный coordinator и безопасный recovery

Coordinator outcome валидируется как замкнутый typed contract: `PENDING` не
может содержать terminal evidence, `MATERIALIZED` требует run ID,
`REJECTED` — materialization ID, а `STOPPED` не смешивается с semantic
materialization. Поэтому вызывающий код не может принять противоречивый статус
за завершённый результат.

Два одновременно начатых шага от одного durable состояния проверены на fresh
PostgreSQL: SQL claim serialization создаёт только один следующий ordinal и до
provider доходит только один invocation. Complete batch при повторном запуске
идёт по no-network `RECOVERY`, возвращая прежний persisted run. Gate: `27`
worker unit и `88` fresh PostgreSQL тестов; схема и Alembic head не менялись.

## S59: восстановление после commit capture

Если процесс завершился после сохранения terminal receipt и encrypted raw, но
до materialization, повторный bounded coordinator step не отправляет документ
снова. Он читает durable state и выполняет только локальный parse/validation и
append-only materialization. Валидный ответ создаёт прежний reviewer workflow с
`UNKNOWN`; semantic-invalid ответ создаёт `REJECTED`, сохраняя transport
`SUCCESS` отдельным фактом.

Оба пути идемпотентны по execution/parser и возвращают те же IDs при следующем
recovery worker. Проверка использует transport, который падает при любом вызове,
поэтому отсутствие повторной сети доказано непосредственно. Fresh PostgreSQL
gate: `90 passed`; Alembic head `20260917_12`.

## S60: единый no-network recovery CLI

`materialize-ai-transfer` читает persisted admission и по immutable
`chunk_count` маршрутизирует single execution в S49, а multi execution — в
S53/S54. Команда больше не может ошибочно пометить поддерживаемый multi batch как
`UNSUPPORTED_MULTI_CHUNK`.

Результат одинаково описывает `PENDING`, `MATERIALIZED` и `REJECTED`, ordered
ordinals и безопасные digest/IDs. Команда не создаёт transport client и не
использует provider API key. Проверены четыре recovery-ветки; схема не менялась.
