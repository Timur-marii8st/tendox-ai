> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

# Последовательная разработка

Источник требований — [ТЗ](../../product/11-product-requirements.md), распределение обязанностей
разработчиков — [AGENTS.md](../../../AGENTS.md). Этот файл хранит актуальный порядок
и статус этапов. Аудит 13 — исторический снимок до начала реализации.

S223 COMPLETE и установлен — поиск сайтов снабжения через поисковики.
S224 COMPLETE и установлен — чтение выбранного сайта и опубликованные ценовые наблюдения.
S225 COMPLETE и установлен — подтверждённый поиск товара на сайте и цена выбранной карточки.
S226 COMPLETE и установлен — условия товара и публичные характеристики рядом с ЕИС.
S227 COMPLETE и установлен — точная таблица сохранённого DOCX рядом с товаром.
S228 COMPLETE и установлен — механизм независимого review и проверка формата.
Production independent review PENDING; полного технического допуска нет.
Следующий этап S229 — подтверждённые единицы и количество листов в упаковке.
Результаты и границы: [S227](../../documents/109-eis-requirement-table-preview.md).
S222 завершён — восстановление сохранённых связей позиции.
S220 завершён и установлен — поиск снабжения из exact позиции ЕИС.
Контракт нового поиска и проверки: [S223](../../suppliers/105-eis-position-supplier-serp.md).
Фиксированный каталог: [S220](../../suppliers/102-eis-position-supplier-search.md).
S219 завершён — сохранённый текст DOCX доступен в карточке ЕИС.
S218 завершён — отдельный immutable анализ с lossless страницами и явным body scope.
Проверки, ограничения и точные evidence: [S219](../../documents/101-eis-document-review-ui.md),
[S218](../../documents/100-eis-document-review-capture.md). Полный охват ЕИС и всего нативного ТЗ UNKNOWN.
Срез S220 — поиск поставщиков и публичных ценовых наблюдений из одной точной
позиции ЕИС; этот отдельный этап не требует ручного прайса пользователя.
После этого — сопоставление с ТЗ, RFQ/КП и три сценария экономики. Исходящие RFQ
требуют exact-payload approval. Исторические результаты приведены ниже.

## S1 — проверяемое решение по вручную собранному кейсу

Статус: **завершён 2026-09-08 в описанных ниже границах**.

Результат: `Quote`, `ProcurementCase`, ручная оценка точного снимка, именованные
обязательные проверки, полнота расходов и три сценария, локальный CLI с записью
расчёта. Инструкция и пример — [локальный workflow](../../operations/16-local-case-workflow.md).
Проверки: **296 pytest-тестов, 9 doctests, ruff и mypy домена проходят**.
В тестах сохранены прежние ограничения recommendation; API заменён со скалярных
утверждений вызывающего кода на проверку целого кейса.

Вход: профиль компании, процедура, подтверждённое КП на весь комплект поставки,
именованные обязательные проверки с источниками и три сценария экономики.
Выход: типизированная рекомендация с основаниями и ценой остановки.
Локальный CLI позволяет загрузить JSON и повторить расчёт на указанное время.

Критерии завершения:

- КП принадлежит компании и процедуре, имеет источник, срок и подтверждённые условия;
- пропущенный обязательный фильтр и неполная экономика не дают зелёное решение;
- отсутствие расхода отличается от явно указанного нуля, в том числе после JSON roundtrip;
- НДС не угадывается, денежные float и нечисловые значения отвергаются;
- изменение профиля, процедуры или КП требует нового анализа их точного снимка;
- просроченная подача/КП, межтенантная подмена и FAIL покрыты негативными тестами;
- пример запуска проверяется вместе с unit-тестами, doctests, ruff и mypy;
- документация прямо отделяет ручные подтверждения от будущего автоматического извлечения.

Граница: одна компания на кейс, рубли, одно КП на весь комплект, введённые человеком
затраты на единой базе НДС. Никакой отправки писем, заявки, заказа или подписи.
Юридические проверки в S1 вводит проверяющий; действующего автоматического
нормативного ruleset нет. Автоматическая рекомендация shelf sales будет подключена
отдельно после доказуемой связи процедуры с контекстом платформы.

## S2 — хранение и API

Статус: **завершён 2026-09-08 для первого серверного среза**.

PostgreSQL, миграции, tenant-scoped репозитории, идентификация пользователя,
версии профиля/кейса/КП, audit и тонкий FastAPI. Изоляция проверяется реальной
БД и негативными API-тестами. Мок tenant header не считается авторизацией.
Результат: кейс сохраняется, загружается и пересчитывается через API без потери
неизвестных данных и истории. Выбор очереди не блокирует этот этап.

Реализован immutable-снимок `ProcurementCase`, который хранит точные версии
профиля, процедуры, КП, проверок и экономики внутри aggregate. Отдельные таблицы
профиля и КП пока не выделены: второго независимого write workflow для них ещё
нет. Добавлены Alembic, PostgreSQL RLS/FORCE RLS, runtime-роль без доступа к
digest API-ключей, bearer identity, cursor pagination, append-only audit,
атомарная evaluation + audit + idempotency receipt и FastAPI endpoints.

Проверки: **303 unit/API-теста**, **12 integration-тестов на PostgreSQL 16**,
9 doctests, ruff и mypy домена проходят. Сквозной тест выполняет bearer auth,
create/replay/conflict, межтенантный `404`, серверную оценку и audit через
HTTP → PostgreSQL. Контракт и локальный запуск — в [документе S2](../../operations/17-storage-api.md),
решение об изоляции — [ADR-0007](../../adr/0007-postgres-rls-and-bearer-tenant.md).

## S3 — первый пользовательский экран

Статус: **завершён 2026-09-09 для внутреннего пилота одного tenant**.

Профиль → ручной импорт процедуры/КП → обязательные проверки → карточка решения
и очередь неизвестных. Видны источники, сроки, расходы и основания. Ошибки
API объясняются без показа трассировок. Демоданные явно помечены.

Реализован внутренний пилот одного настроенного tenant. Next.js
использует server-side bearer token и не передаёт его браузеру; пользователь
работает со списком последних версий, импортом полного `ProcurementCase`,
карточкой и последней сохранённой evaluation. Production multi-user auth,
ingestion, аналитика и любые внешние действия в S3 не входят. Контракт и
локальный запуск описаны в [документе S3](../../operations/18-first-screen.md).

Экран показывает сводку только по фактически загруженной выборке, карточки,
deadline и часовой пояс, provenance, gates, три сценария расходов, рейтинг с
факторами, основания и следующий шаг. Импорт и пересчёт идут через server actions
с новым idempotency key; bearer secret не попадает в browser bundle.
Проверки: Next.js lint/build, 318 Python-тестов с включёнными 13 PostgreSQL
integration, 9 doctests, Ruff и mypy проходят; desktop layout проверен headless
Edge через реальный BFF → FastAPI → PostgreSQL workflow.

## S4 — документы и разрешённый мониторинг

Статус: **в работе; текущие технические срезы и ограничения перечислены ниже**.

Immutable snapshots, native parsing/OCR, извлечение в строгую схему, полнота ТЗ,
золотой набор. Затем один согласованный источник с checkpoint, rate limit,
дедупликацией и видимой свежестью. Фактическое покрытие показывается пользователю.

Первый срез принимает PDF/DOCX/XLSX через tenant-scoped API, проверяет MIME,
сигнатуру и ресурсные лимиты, нативно извлекает текст с provenance и атомарно
сохраняет исходные байты, результат, audit event и idempotency receipt в PostgreSQL.
Пустой или сканированный PDF получает `UNKNOWN/OCR_REQUIRED`; макросы, формулы и
внешние ссылки не исполняются. PostgreSQL RLS, межтенантный `404`, append-only
trigger, конкурентный replay и полный HTTP → PostgreSQL путь проверены тестами.
Контракт и ограничения описаны в [документе S4](../../documents/19-document-pipeline.md), решение
о пилотном `BYTEA` — в [ADR-0009](../../adr/0009-postgres-document-snapshots.md).

Оставшаяся работа S4 включает независимые проверки: калибровку OCR на
разрешённых реальных сканах и read-only подключение одного согласованного
источника. Получение метаданных извещения и исходных bytes не зависит от
калибровки OCR; автоматический вывод требований из сканов остаётся `UNKNOWN`
до неё. Мониторинг ещё не реализован.

Второй срез S4 завершён 2026-09-09: immutable OCR-производные версии
(`document_ocr_derivatives`, миграция `20260909_02`) с FK на исходник, RLS,
append-only trigger, audit `document.ocr_stored` и idempotency; домен
`procurement.documents.ocr` с порогом `0.75` и provenance `extractor=ocr`;
API `POST /v1/documents/{id}/ocr`, `GET .../ocr/latest`,
`GET /v1/document-ocr/{ocr_id}`. Пилотный engine честно возвращает
`UNKNOWN/OCR_REQUIRED` без синтеза фактов. Проверки: 333 unit/API-теста
(12 доменных OCR + 5 API OCR), doctests, ruff и mypy домена проходят;
Alembic имеет единственный head `20260909_02`; PostgreSQL integration-тесты
требуют `DATABASE_URL` и в этой среде пропускаются.

Третий срез S4 завершён 2026-09-10: детерминированный маппер блоков в строгие
факты (`procurement.documents.facts`, правила `warranty`/`ethernet_ports`,
порог `0.75`, непокрытое — честный `unmapped` без синтеза) и золотой набор v0
(`data/goldenset/v1/tz_001.docx` + ручной эталон `tz_001.expected.json`,
тест `tests/test_goldenset_v1.py` запрещает ложный PASS). Проверки: 344
unit/API-теста (9 маппера + 2 golden), doctests, ruff и mypy проходят; миграций
не требовалось, head прежний. Золотой набор v1 (2026-09-10): негативные пути
`tz_002` (скан → `UNKNOWN/OCR_REQUIRED`, пустой маппинг) и `tz_003` (XLSX:
литерал `Spec!A1` → `warranty >= 12`, формула исключена,
`UNKNOWN/FORMULAS_IGNORED`); набор версионируется через исключение
`!/data/goldenset/` в `.gitignore`. Проверки: 346 unit/API-тестов. Четвёртый срез
S4 (2026-09-10): правила R1–R4 и e2e `факты tz_001 → evaluate`
(`tests/test_tz001_e2e.py`, 6 вердиктов, флаг эквивалента всегда явно).
Проверки: 363 unit/API-теста, ruff и mypy проходят. Пятый срез S4 (2026-09-10):
словарь стран + `country NE` (неизвестное — в unmapped), R2 терпит двоеточие,
золотой набор v2 (`tz_004` бан+дата, `tz_005` числовые+страна как файлы).
Проверки: 372 unit/API-теста, ruff и mypy проходят. Шестой срез S4 (2026-09-13):
явные требования `Декларация соответствия ТР ТС` / `Сертификат соответствия ЕАЭС`
маппятся в `certificate:<вид> EXISTS` с provenance; простое упоминание остаётся
`unmapped`. Compliance проверяет документ совпадающего вида на дату поставки:
отсутствие, низкий confidence и неизвестные даты дают `UNKNOWN`, просрочка —
`FAIL`, действующий документ — `PASS`. Золотой набор v3 добавляет `tz_006` и
сквозной путь DOCX → факты → evaluation. Остаток S4: репрезентативные сканы с
реальным локальным OCR, КП-ловушки и расширение типов документов; затем
мониторинг одного согласованного источника. Проверки среза: 382 unit/API-теста,
9 doctests, ruff и mypy домена проходят; 19 PostgreSQL integration-тестов без
`DATABASE_URL` пропущены. S4 ещё не завершён.

Седьмой срез S4 (2026-09-13): `map_blocks_to_requirements` требует роль
`TENDER_REQUIREMENTS | SUPPLIER_QUOTE`, а `FactMappingResult` сохраняет её и
запрещает противоречивый output. Все блоки КП остаются
`unmapped/NON_REQUIREMENT_DOCUMENT`, даже когда текст совпадает с шаблонами
гарантии, портов, сертификатов, даты или запрета эквивалента. Золотой набор v4
добавляет `quote_001.docx` с этими ловушками. Граница среза: доверенное назначение
роли пока передаёт вызывающий workflow; persistence роли и Quote Analyzer ещё не
реализованы в границах этого среза. Проверки: 386 unit/API-тестов, 9 doctests,
ruff и mypy домена и document-модулей проходят; 19 PostgreSQL integration-тестов
без `DATABASE_URL` пропущены.

Восьмой срез S4 (2026-09-13): доверенная роль стала обязательным полем
multipart-загрузки и сохраняется вместе с immutable source document. Контракт
`DocumentRole` содержит `UNKNOWN | TENDER_REQUIREMENTS | SUPPLIER_QUOTE`;
`UNKNOWN` блокирует requirement mapping и безопасно присваивается существующим
строкам миграцией `20260913_01`. Роль возвращается API, входит в idempotency
digest и audit `document.stored`, а PostgreSQL ограничивает значения `CHECK`.
Проверки: 389 unit/API-тестов проходят, 19 PostgreSQL integration-тестов без
`DATABASE_URL` пропущены; 10 doctests, ruff, mypy, Next.js lint/build проходят;
Alembic имеет единственный head `20260913_01`. S4 ещё не завершён: локальный OCR
на репрезентативных сканах и мониторинг согласованного источника остаются впереди.

Девятый срез S4 (2026-09-13): production runtime получил локальный русский OCR
`paddleocr/3.7.0:PP-OCRv5-ru` с server detection, `eslav` recognition,
коррекцией ориентации/искажения и сохранением `rec_score` + bbox в provenance.
Сервер сам выбирает engine; исходные байты читаются tenant-scoped, сверяются по
SHA-256, ограничены 200 страницами и удаляются из временного файла после inference.
Зависимости изолированы в extra `ocr`, решение записано в ADR-0010. Реальный
raster-only regression подтверждает путь PDF → OCR → `warranty`/`ethernet_ports`.
До production-допуска остаются реальные разрешённые сканы и калибровка порога;
после них — мониторинг одного согласованного источника.
Проверки: обычный gate — 400 passed, 20 skipped (19 PostgreSQL без DB URL и
1 opt-in OCR); реальный PP-OCRv5 с локальным model root — 1 passed; 10 doctests,
ruff, mypy, Next.js lint/build проходят. Alembic head — `20260913_01`.

Десятый срез S4 (2026-09-13): добавлен типизированный `OcrCalibrationReport` с
evidence по sample ID и SHA-256, матрицей TP/FP/FN для наблюдаемых confidence и
решением `PASS | FAIL | UNKNOWN`. Порог выбирается только при нуле принятых
ложных строк и recall не ниже цели; недостаточная разметка остаётся `UNKNOWN`,
а отсутствие безопасного порога даёт `FAIL`. Повтор одного source digest не может
искусственно увеличить выборку. Реальный opt-in benchmark теперь содержит три
raster-only страницы: обычную, повёрнутую на 2,5° и низкоконтрастную размытую;
PP-OCRv5 распознал все шесть строк, а синтетическая калибровка сохранила порог
`0.75`. Этот результат не заменяет калибровку на разрешённых реальных ТЗ.
Проверки: обычный gate — 405 passed, 20 skipped (19 PostgreSQL без DB URL и
1 opt-in OCR); реальный трёхстраничный PP-OCRv5 benchmark — 1 passed; 10 doctests,
ruff, mypy по 33 source-файлам, Next.js lint/build и `uv lock --check` проходят;
Alembic head — `20260913_01`.

Одиннадцатый срез S4 (2026-09-13): добавлен воспроизводимый локальный запуск
`python -m procurement calibrate-ocr`. Версионированный manifest связывает каждый
raster-only PDF с относительным путём, immutable SHA-256, полной построчной ручной
разметкой и evidence разрешения на обработку; время разметки обязательно содержит
timezone. Абсолютные/выходящие из каталога пути, повтор source digest, подменённые
байты, текстовые PDF, страницы разметки вне документа и другой OCR engine
отклоняются до расчёта. В итоговый `OcrCalibrationRunReport` входят SHA-256 самого
manifest, полная разметка, сырые строки PP-OCRv5 с confidence/bbox и типизированное
решение; исходные пути не сохраняются и не печатаются. Отчёт публикуется атомарно
без перезаписи, а CLI возвращает код `0` только для `PASS` (`UNKNOWN=3`, `FAIL=4`).
Разрешённых реальных сканов в репозитории нет, поэтому production calibration
остаётся `UNKNOWN` и мониторинг источника не начинается. Проверки среза: обычный
gate — 414 passed, 20 skipped (19 PostgreSQL без DB URL и 1 opt-in OCR), 10
doctests, ruff, strict mypy по 34 source-файлам, Next.js lint/build,
`uv lock --check` проходят; Alembic имеет единственный head `20260913_01`.

Дополнительный локальный robustness-прогон (2026-09-13) выполнен на семи
предоставленных пользователем разнородных изображениях: каждое без ресэмплинга
преобразовано в одностраничный raster-only PDF, повторно отрендерено через PDFium
и визуально проверено. Локальный PP-OCRv5 обработал все 7/7 PDF без runtime-ошибок:
360 сырых строк-кандидатов, 320 строк с confidence `>= 0.75`; каждый OCR derivative
получил текст на единственной странице. На сложном фотографическом образце с
рукописным текстом порог прошла 21 из 46 строк против 299 из 314 на остальных
печатных/графических образцах. Это evidence работоспособности и ожидаемого риска
рукописного ввода, но не production-калибровка: набор не состоит из закупочных ТЗ
и не имеет полной независимой построчной разметки, поэтому calibration status
остаётся `UNKNOWN/NON_PROCUREMENT_UNLABELED_SAMPLES`.

Двенадцатый срез S4 (2026-09-14): добавлен fail-closed workflow ручной разметки
`prepare-ocr-labeling → finalize-ocr-labeling → calibrate-ocr`. Подготовка строит
типизированный `ocr-labeling-draft-v1`: immutable SHA-256 и число страниц каждого
raster-only PDF, сырые OCR `suggestions` с confidence/bbox и отдельное пустое поле
`expected`. Подсказки никогда автоматически не становятся эталоном. Reviewer
может исправлять строки и добавлять полностью пропущенные OCR строки; подтверждение
требуется для каждого образца и всего пакета вместе с reviewer ID и timezone-aware
временем. Финализация повторно сверяет исходные байты/страницы, отказывает при
неполном review и записывает SHA-256 точных байтов draft в calibration manifest и
report. JSON публикуются атомарно без перезаписи и только рядом с PDF, чтобы
безопасные относительные пути сохраняли смысл.

Реальный локальный прогон нового CLI на семи non-production образцах сформировал
draft с 360 подсказками, нулём ожидаемых строк и статусом
`UNKNOWN/HUMAN_REVIEW_REQUIRED`; попытка финализации вернула
`REVIEW_INCOMPLETE` и не создала manifest. Эти документы остаются robustness
набором, а не закупочной calibration evidence. Проверки среза: обычный gate —
424 passed, 20 skipped (19 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests,
ruff, strict mypy по 35 source-файлам, Next.js lint/build и `uv lock --check`
проходят; Alembic имеет единственный head `20260913_01`.

Тринадцатый срез S4 (2026-09-14): добавлено безопасное раскрытие внешнего ZIP с
PDF, DOCX и XLSX. Архив остаётся immutable source с SHA-256; каждый участник имеет
отдельные byte size/SHA-256/status, а локаторы извлечённых блоков включают
нормализованный archive path. Литеральные ячейки XLSX проходят существующий
нативный parser, формулы не исполняются и дают `UNKNOWN/FORMULAS_IGNORED`.
Неподдержанные участники, включая legacy `.xls`, видимы как
`UNKNOWN/UNSUPPORTED_MEMBERS` и не создают блоков. Zip-slip, абсолютные и
управляющие пути, case-insensitive дубликаты, symlink, шифрование, макросные
форматы, вложенные/замаскированные архивы, превышение числа участников и expanded
size отклоняют пакет целиком до использования фактов.

Локальная команда `inspect-document-bundle` атомарно сохраняет полный
типизированный JSON и печатает только агрегаты; `PASS` даёт exit `0`, неполный
`UNKNOWN` — `3`, rejection — `2` без частичного отчёта. Сквозной тест подтверждает
ZIP → DOCX/XLSX → provenance участника → строгие `warranty`/`ethernet_ports`.
Прямая загрузка XLSX уже поддерживается `POST /v1/documents`; tenant-scoped
публикация ZIP и его участников через API/persistence остаётся отдельным следующим
срезом и пока не объявляется готовой. Проверки среза: обычный gate — 448 passed,
20 skipped (19 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests, ruff, strict
mypy по 36 source-файлам, Next.js lint/build и `uv lock --check` проходят;
Alembic имеет единственный head `20260913_01`.

Четырнадцатый срез S4 (2026-09-14): ZIP стал отдельным tenant-scoped API-ресурсом.
`POST /v1/document-bundles` принимает обязательную доверенную `DocumentRole`,
проверяет пакет существующим fail-closed extractor и только после успешной проверки
атомарно сохраняет immutable байты внешнего архива и типизированные member snapshots.
`GET /v1/document-bundles/{bundle_id}` возвращает метаданные и результаты участников,
но не исходные байты. SHA-256 результата обязан совпадать с внешним ZIP, а каждый
member сохраняет собственный digest и archive provenance.

Миграция `20260914_01` добавляет `document_bundles` с RLS, append-only trigger,
ограничениями размера/MIME/роли и проверками связи JSON result с `bundle_id` и
SHA-256. Запись bundle, audit `document_bundle.stored` и idempotency receipt выполняется
в одной транзакции; повтор точного запроса возвращает прежний snapshot, смена payload
даёт conflict. Небезопасный ZIP не достигает storage. Чужой и отсутствующий bundle
одинаково возвращают `404`. Проверки среза: 452 passed, 23 skipped (22 PostgreSQL без
DB URL и 1 opt-in OCR), 10 doctests, ruff, strict mypy по 36 source-файлам и
Next.js lint/build, `uv lock --check` проходят; Alembic имеет единственный head
`20260914_01`, а полная цепочка миграций компилируется в offline SQL.
OCR scan-only PDF внутри ZIP остаётся следующим отдельным срезом.

Пятнадцатый срез S4 (2026-09-15): добавлен OCR конкретного scan-only PDF-участника
ZIP. `POST /v1/document-bundles/{bundle_id}/members/{member_index}/ocr` принимает
только участника с `application/pdf` и `UNKNOWN/OCR_REQUIRED`; DOCX/XLSX,
неподдержанный member и PDF с нативным текстом не отправляются в OCR. Перед inference
сервер tenant-scoped читает immutable outer ZIP и повторно сверяет его digest,
структуру, индекс, archive path, размер и SHA-256 выбранного участника. Стабильный
source ID имеет вид `<bundle_id>:member:<index>`, а каждый OCR locator сохраняет
префикс archive member.

`GET .../ocr/latest` и `GET /v1/document-bundle-member-ocr/{ocr_id}` возвращают
производную без исходных байтов. Миграция `20260914_02` добавляет отдельную таблицу с
FK на bundle, RLS, append-only trigger и DB-проверками source ID/SHA, engine/status.
OCR result, audit `document_bundle.member_ocr_stored` и idempotency receipt пишутся
атомарно. Порог persisted OCR имеет шаг `0.01`, совпадающий с `NUMERIC(3,2)`, поэтому
БД не округляет evidence молча. Пустой результат остаётся `UNKNOWN/OCR_REQUIRED`.
Проверки среза: 458 passed, 26 skipped (25 PostgreSQL без DB URL и 1 opt-in OCR),
10 doctests, ruff, strict mypy по 36 source-файлам, Next.js lint/build и
`uv lock --check` проходят; Alembic имеет единственный head `20260914_02`, полная
цепочка миграций компилируется в offline SQL.

Шестнадцатый срез S4 (2026-09-15): разрешённый локальный набор из 13 реальных ТЗ
прогнан без публикации их текста и добавлен fail-closed guard полноты DOCX.
До исправления DOCX с крупным вложенным JPEG получал `PASS` по небольшому объёму
нативного текста, хотя содержимое изображения не извлекалось. Теперь наличие
`word/media/*` сохраняет нативные блоки и provenance, но даёт
`UNKNOWN/EMBEDDED_MEDIA_IGNORED`. Синтетический regression фиксирует запрет
ложного `PASS`, а локальный каталог набора исключён из Git.

После исправления 9 DOCX дали 5 `PASS` и 4 честных `UNKNOWN`: два из-за внешних
ссылок и два из-за вложенных изображений. ZIP с DOCX, detached-подписью `.sig` и
PDF остался `UNKNOWN` с видимыми `UNSUPPORTED_MEMBERS` и
`MEMBER_EXTRACTION_UNKNOWN`; PDF-участник обработан нативно. Два legacy DOC и RAR
остались явно неподдержанными. Проверки среза: 459 passed, 26 skipped (25
PostgreSQL без DB URL и 1 opt-in OCR), 9 doctests, ruff, strict mypy по 36
source-файлам, Next.js lint/build и `uv lock --check` проходят; Alembic имеет
единственный head `20260914_02`, полная цепочка миграций компилируется в offline
SQL.

Семнадцатый срез S4 (2026-09-15): добавлен отдельный локальный OCR связанных
PNG/JPEG внутри DOCX. Извлекатель следует только реально используемым внутренним
OOXML image relationships, проверяет DTD/entity, безопасный path, MIME/format,
SHA-256, byte/pixel/dimension limits и Pillow verify. Внешнее, отсутствующее,
неподдержанное или битое media не становится OCR-source. Стабильный ID имеет вид
`<document_id>:media:<index>`, а locator OCR —
`DOCX media "word/media/..." :: image 1 bbox ...`; image bytes исключены из JSON.

`PaddleOcrRunner` теперь принимает проверенные PNG/JPEG, повторно сверяет digest и
лимиты непосредственно перед inference и нормализует отсутствующий `page_index`
одиночного изображения. CLI `ocr-docx-media` публикует полный приватный отчёт без
перезаписи, но не печатает распознанный текст. Реальный JPEG 9921×7016 размером
8,14 МиБ обработан локальными PP-OCRv5-моделями: 95 принятых блоков, minimum
confidence `0.827635`, mean `0.958760`, report SHA-256
`559eeb242f6f8baececd9b8c01a046faa39881b8d096bdc56e0dc101e2fee4eb`; все
locators имеют media prefix, bytes не сериализованы. Второй реальный PNG не прошёл
verify и остался `UNKNOWN/INVALID_IMAGE`. Решение —
[ADR-0011](../../adr/0011-docx-embedded-media-ocr.md). Проверки среза: 467 passed,
26 skipped (25 PostgreSQL без DB URL и 1 opt-in OCR), 9 doctests, ruff, strict
mypy по 37 source-файлам, Next.js lint/build и `uv lock --check` проходят;
реальный DOCX-media OCR выполнен отдельно.

Восемнадцатый срез S4 (2026-09-15): OCR одного проверенного связанного изображения
DOCX доступен через tenant-scoped API:
`POST /v1/documents/{document_id}/media/{media_index}/ocr`,
`GET .../ocr/latest` и `GET /v1/document-docx-media-ocr/{ocr_id}`. Сервер повторно
раскрывает сохранённые immutable DOCX bytes, сверяет SHA-256 внешнего документа и
точного PNG/JPEG, проверяет OOXML relationship и передаёт движку только этот media
source. Ответ содержит typed derivative, оба digest, archive path и locator, но не
исходные байты.

Миграция `20260915_01` добавляет append-only
`document_docx_media_ocr_derivatives` с tenant FK, RLS/FORCE RLS и DB-проверками
идентичности typed result. Производная, audit `document.docx_media_ocr_stored` и
idempotency receipt записываются одной транзакцией; повтор exact request возвращает
тот же результат, другая нагрузка с тем же ключом конфликтует, чужой tenant видит
`404`. Проверки среза: 469 passed, 27 skipped (26 PostgreSQL без DB URL и 1 opt-in
OCR), 9 doctests, ruff, strict mypy по 37 source-файлам, Next.js lint/build и
`uv lock --check` проходят; Alembic имеет единственный head `20260915_01`, полная
цепочка миграций компилируется в offline SQL.

Девятнадцатый срез S4 (2026-09-15): добавлен типизированный fail-closed workflow
калибровки OCR связанного изображения DOCX по визуальной разметке. Review хранит
SHA-256 DOCX и media, безопасный относительный путь, media index, размеры,
построчный expected text, reviewer provenance и неоднозначности. Перед inference
`run_docx_media_calibration_review` повторно проверяет точные исходные bytes и
OOXML relationship. CLI `calibrate-docx-media-review` публикует приватный полный
отчёт, не выводя текст в stdout.

`AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION` может дать наблюдаемые метрики, но
production status всегда остаётся `UNKNOWN/HUMAN_REVIEW_REQUIRED` и recommended
threshold не публикуется. Только `HUMAN_CONFIRMED` без unresolved uncertainties
может передать `PASS` существующего calibration engine. На реальном JPEG создана
визуальная AI-разметка из 119 строк с тремя явно отмеченными неоднозначностями.
При baseline `0.75` получено 78 true positive, 17 false positive и 41 false
negative: precision `0.8211`, recall `0.6555`. Ни один наблюдаемый порог не дал
нулевых false positive при recall не менее `0.9`, поэтому внутренний результат —
`FAIL/NO_SAFE_THRESHOLD`, внешний gate — `UNKNOWN/HUMAN_REVIEW_REQUIRED`.
Review SHA-256 `ff2699daceaad97e92caf21c731e28e327da1650a2aafbf94e7b5fe39755c36a`,
report SHA-256 `f8e613fc15506ff634a5834ad3ebe38451dbb0f452aa237b87d1e70e11d5883a`.
Проверки среза: 473 passed, 27 skipped (26 PostgreSQL без DB URL и 1 opt-in OCR),
9 doctests, ruff, strict mypy по 38 source-файлам, Next.js lint/build и
`uv lock --check` проходят; Alembic head остаётся `20260915_01`.

Двадцатый срез S4 (2026-09-15): добавлена статическая локальная страница
`/ocr-review` для человеческого подтверждения AI-разметки DOCX-media. Браузер
принимает review JSON и исходный DOCX, локально проверяет схему, лимиты, SHA-256
документа, exact `word/media/*`, SHA-256 и размеры изображения; исходные файлы не
отправляются в Next.js или FastAPI. Чертёж показывается рядом со всеми expected
строками и явными uncertainties. Скачать новый `HUMAN_CONFIRMED` JSON можно
только после разрешения всех неоднозначностей, непустого reviewer ID и явного
подтверждения полной построчной сверки. Исходный AI review не изменяется, а его
SHA-256 и решения человека входят в method нового evidence. ZIP-reader имеет
ограничения размера/числа entries, отклоняет encryption, ZIP64, неизвестное
сжатие, дубликат exact media path и лишний decompressed output. Next.js lint/build
проходят; реальный DOCX дал совпадение document/media SHA-256 и exact media size
8 143 862 bytes. Полный gate: 473 passed, 27 skipped (26 PostgreSQL без DB URL и
1 opt-in OCR), 10 doctests, ruff, strict mypy по 38 source-файлам, Next.js
lint/build, `uv lock --check`, единственный Alembic head `20260915_01` и offline
SQL проходят. Автоматический browser click-through недоступен в текущей сессии:
computer-use вернул пустой список браузеров.
После ручной проверки UX поле DOCX разблокировано до загрузки review: два файла
можно выбирать в любом порядке, а ранее выбранный DOCX проверяется автоматически.

Двадцать первый срез S4 (2026-09-15): небезопасный OCR отделён от статуса самого
документа. Новый typed routing принимает immutable calibration report и при
`FAIL/NO_SAFE_THRESHOLD` возвращает `REJECT_LOCAL_OCR`, но сохраняет документ в
`UNKNOWN`; закупка или кандидат этим решением не отклоняются. Следующие действия —
`REQUEST_NATIVE_SOURCE` и `PREPARE_VISION_API_APPROVAL`. Опциональный vision draft
фиксирует provider, model, HTTPS endpoint, retention-policy reference, SHA-256
DOCX/media, неизменяемый безопасный prompt и response contract в exact payload
digest. Draft всегда имеет `APPROVAL_REQUIRED` и `send_allowed=false`; image bytes
не отправляются и не входят в routing artifact. Смена модели, destination или
prompt меняет digest и требует нового approval.

На реальном calibration report создан приватный routing artifact с disposition
`REJECT_LOCAL_OCR`, reason `LOCAL_OCR_NO_SAFE_THRESHOLD`, document status
`UNKNOWN` и без vision draft, поскольку поставщик и retention policy ещё не
выбраны. Его SHA-256 —
`b8c2d5229001b4cd06d9503e9c710ccccb0046968d070b38b4872974783a82e8`.
Полный gate: 478 passed, 27 skipped (26 PostgreSQL без DB URL и 1 opt-in OCR),
10 doctests, ruff, strict mypy по 39 source-файлам, Next.js lint/build,
`uv lock --check`, единственный Alembic head `20260915_01` и offline SQL проходят.
Production UI перезапущен после build; страница и 9 клиентских JS assets отвечают
`200`.

Двадцать второй срез S4 (2026-09-15): уточнение владельца продукта сведено в
локальный hybrid discovery contract. Поиск использует название процедуры,
исходное имя файла и каждый нативный блок; полезный нативный текст доступен для
поиска даже при общем `UNKNOWN/EMBEDDED_MEDIA_IGNORED`, не снимая неполноту
документа. Vision-теги остаются отдельным evidence: AI suggestion даёт
discovery `UNKNOWN`, human-confirmed тег — `PASS` только для совпадения, но ни
один тег не влияет на требования, hard gates или участие.

`vision-search-tags-v1` фиксирует tenant/document, SHA-256 DOCX и exact linked
media, media index/path, producer/model, timezone-aware время, prompt digest,
исходный review artifact, confidence и locator. Перед поиском relationship и
digest изображения повторно проверяются; сырой OCR автоматически не
индексируется. CLI `search-document` работает локально и ничего не отправляет.
На реальном ТЗ найдены «ремонт», «выполнение работ» и «кондиционирование»; модель
`GW-G140W/N1D3` найдена только в AI-теге (`UNKNOWN`), а `General` не найден без
доказательного каталога model→brand. Приватный manifest имеет SHA-256
`07ab53c7d5a9d946ca262b55af732c251075df4b583457fc9e86484ab1eb9a87`.
Решение — [ADR-0012](../../adr/0012-hybrid-document-discovery.md). Полный gate:
488 passed, 27 skipped (26 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests,
Ruff, strict mypy по 40 source-файлам, Next.js lint/build и `uv lock --check`.
Production UI перезапущен после build; страница и 9 JS assets отвечают `200`.

Двадцать третий срез S4 (2026-09-15): hybrid discovery получил immutable
tenant-scoped persistence и API. Миграция `20260915_02` добавляет append-only
`document_search_indexes` с FK на source document, SHA-256, typed JSON entry,
RLS/FORCE RLS, runtime `SELECT/INSERT` и запретом `UPDATE/DELETE`. Перед записью
repository повторно читает exact bytes/extraction и перестраивает entry; linked
DOCX media evidence сверяется повторно.

`POST /v1/documents/{document_id}/search-indexes` атомарно сохраняет index, audit
`document.search_index_stored` и idempotency receipt. Exact replay возвращает
исходную версию, изменение title/vision payload с тем же ключом даёт `409`, а
чужой/отсутствующий source одинаково даёт `404`. `GET /v1/document-search`
фильтрует только последние версии документов текущего bearer tenant и возвращает
typed hits с исходным status/provenance без document bytes. Решение —
[ADR-0013](../../adr/0013-immutable-document-search-index.md). Полный gate: 490 passed,
29 skipped (28 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests, Ruff, strict
mypy по 40 source-файлам, Next.js lint/build и `uv lock --check`; единственный
Alembic head `20260915_02`, полная цепочка компилируется в offline SQL.

Двадцать четвёртый срез S4 (2026-09-16): `GET /v1/document-search` подключён к
server-rendered странице `/document-search`. Bearer token остаётся только в
Next.js server module; запрос ограничен 200 символами и URL-encoded. Экран имеет
отдельные idle/loading/empty/error состояния, показывает immutable document ID,
status и provenance каждого hit и различает «найдено в названии / имени файла /
тексте / на чертеже». AI-suggested vision hit остаётся заметным `UNKNOWN`, а
страница прямо отделяет discovery-совпадение от compliance и решения об участии.
Исходные document/media bytes UI не запрашивает.

Навигация связывает экран с делами и локальной OCR-review страницей. ESLint и
production build Next.js 16.3.4 прошли; `/document-search` и все 9 CSS/JS assets
вернули `200` на синтетической smoke-выдаче с одновременными native `PASS` и
vision `UNKNOWN`. Временный fake API и его конфигурация после проверки удалены.

Двадцать пятый срез S4 (2026-09-16): добавлен локальный reviewed
`model-brand-catalog-v1`. Immutable manifest фиксирует tenant/catalog ID,
reviewer/approval reference, timezone-aware creation time и exact model→brand
entries с effective interval. Каждая запись несёт официальный HTTPS source,
SHA-256 точного документа, locator и время получения. Lookup нормализует только
Unicode, регистр и пробелы: fuzzy/prefix inference запрещён; отсутствующее,
неактивное, межтенантное или конфликтующее evidence даёт `UNKNOWN` без бренда.

Discovery по бренду создаёт отдельный `MODEL_BRAND_CATALOG` hit с полной цепочкой
model provenance + official catalog evidence. Status наследуется от источника
модели: native даёт discovery `PASS`, AI-suggested vision model остаётся
`UNKNOWN`. CLI `search-document` принимает `--model-brand-catalog` и explicit
`--at`; ничего не загружает и не сохраняет. Официальное руководство General
Climate подтвердило только отличающуюся модель `GW-G140/N1A1`, поэтому
`GW-G140W/N1D3 → General Climate` намеренно не добавлена. Решение —
[ADR-0014](../../adr/0014-evidence-backed-model-brand-catalog.md). Полный gate: 498
passed, 29 skipped (28 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests, Ruff,
strict mypy по 41 source-файлу и `uv lock --check`.

Двадцать шестой срез S4 (2026-09-16): reviewed model→brand получил immutable
tenant-scoped persistence и API. Миграция `20260916_01` добавляет append-only
`model_brand_catalogs` с typed JSON, RLS/FORCE RLS, runtime `SELECT/INSERT` и
запретом `UPDATE/DELETE`. В исходном срезе `POST /v1/model-brand-catalogs` атомарно сохранял
catalog, audit `model_brand.catalog_stored` и idempotency receipt; tenant,
reviewer и `created_at` задаются bearer principal и сервером, а не payload.
Exact replay возвращает исходную версию, изменённый payload или занятый catalog
ID давали `409`; публичный POST позднее удалён ADR-0019. `GET /v1/model-brand-catalogs/latest` выбирает версию tenant на
timezone-aware момент.

Persisted `GET /v1/document-search` возвращает использованный `effective_at` и
автоматически применяет последний доступный каталог того же tenant. Native exact
model даёт доказательный `MODEL_BRAND_CATALOG` hit; AI suggestion остаётся
`UNKNOWN`. UI показывает catalog/model/official-source provenance. Решение —
[ADR-0015](../../adr/0015-immutable-reviewed-model-brand-catalog.md). Полный gate: 500
passed, 30 skipped (29 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests, Ruff,
strict mypy по 41 source-файлу, Next.js lint/build и `uv lock --check`;
единственный Alembic head `20260916_01`, полная цепочка компилируется в offline SQL.

Двадцать седьмой срез S4 (2026-09-16): официальный catalog source получил
immutable tenant-scoped ingestion. `POST /v1/model-brand-source-artifacts`
принимает bounded PDF, HTTPS URL и title, сохраняет exact bytes/SHA-256 вместе с
audit `model_brand.source_artifact_stored` и idempotency receipt. Ответ и
tenant-scoped GET возвращают только metadata без bytes. Миграция `20260916_02`
добавляет RLS/FORCE RLS, runtime `SELECT/INSERT` и запрет `UPDATE/DELETE`.

Persisted catalog entry теперь обязан ссылаться на `source_artifact_id`. Перед
insert repository в той же транзакции заново хеширует сохранённые bytes и сверяет
artifact ID, title, URL, digest и server retrieval time. Отсутствующий, чужой или
изменённый artifact одинаково отклоняет весь catalog; локальный CLI manifest без
persisted ID не повышается до API evidence. Search UI показывает artifact ID и
digest. Решение — [ADR-0016](../../adr/0016-immutable-model-brand-source-artifacts.md).
Полный gate: 500 passed, 30 skipped (29 PostgreSQL без DB URL и 1 opt-in OCR),
10 doctests, Ruff, strict mypy по 41 source-файлу, Next.js lint/build и
`uv lock --check`; Alembic head `20260916_02`, offline SQL компилируется.

Двадцать восьмой срез S4 (2026-09-16): backend model→brand review получил
persisted роли `OPERATOR | MODEL_BRAND_REVIEWER` и append-only workflow.
Миграция `20260916_03` добавляет роль API key, обновляет security-definer auth и
создаёт tenant-scoped `model_brand_review_proposals/decisions` с RLS/FORCE RLS и
запретом мутаций. Отсутствие decision означает `DRAFT`; единственное терминальное
решение — `APPROVED` или `REJECTED`.

`POST /v1/model-brand-reviews` доступен оператору и повторно проверяет exact
artifact evidence. `POST /v1/model-brand-reviews/{id}/decision` требует reviewer
role и запрещает self-approval. Approval атомарно создаёт searchable catalog,
decision, audit и receipt; rejection catalog не создаёт. Exact replay стабилен,
изменённое/второе решение даёт `409`, чужой/отсутствующий proposal — `404`.
`GET /v1/model-brand-reviews` возвращает только текущий tenant. Публичный прямой
catalog POST удалён: новые searchable catalog публикуются только независимым
решением по proposal. Решения — [ADR-0017](../../adr/0017-role-aware-model-brand-review.md)
и [ADR-0019](../../adr/0019-mandatory-independent-model-brand-review.md). Полный gate: 501 passed,
30 skipped (29 PostgreSQL без DB URL и 1 opt-in OCR), 10 doctests, Ruff, strict
mypy по 42 source-файлам, Next.js lint/build и `uv lock --check`; Alembic head
`20260916_03`, offline SQL компилируется.

Двадцать девятый срез S4 и стабилизация (2026-09-16): числовые `EQ/NE` используют
нормализацию единиц и сохраняют `UNKNOWN` для отсутствующих, неизвестных и
несопоставимых размерностей. `FactMappingResult` получил отдельный review-backed
`CompletenessAssessment`; автоматический mapping всегда `UNKNOWN`, а
`evaluate_document_mapping` не разрешает `COMPLIANT` без completeness `PASS`.
Известный mandatory `FAIL` при этом не скрывается. `tz_001` теперь проходит
настоящий путь DOCX bytes → extraction → mapping → compliance.

Публичный прямой POST model→brand catalog удалён; публикация возможна только
после независимого proposal/decision. Добавлен mandatory PostgreSQL gate:
изолированный PostgreSQL 16, миграции с нуля, owner/runtime separation, запрет
skip и CI service. Локальная проверка: 526 unit/API/e2e тестов без integration,
30/30 PostgreSQL integration, 9 doctests, Ruff, strict mypy по 43 source-файлам, lockfile,
Next.js lint/build. Один opt-in PaddleOCR integration остаётся отдельным и не
считается пройденным.

Следующая проверка S4 — полный human-reviewed пилот на 10–20 разрешённых
комплектах по [протоколу](../../operations/20-stabilization-pilot.md). Приватная папка ТЗ уже
есть, но её файлы ещё не сгруппированы в независимые закупочные комплекты и не
имеют human ground truth, поэтому quality metrics остаются `UNKNOWN`.

Тридцатый срез S4 (2026-09-16): persisted completeness review поддерживает один
immutable native-документ ТЗ. Оператор создаёт server-derived snapshot exact
bytes/extraction/mapping с canonical evidence digest; отдельная роль
`COMPLETENESS_REVIEWER` принимает единственное `PASS | FAIL | UNKNOWN` решение.
Self-review, stale digest, подмена role/extraction, второе решение и изменённый
idempotent replay запрещены. Snapshot/decision/audit/receipt tenant-scoped,
append-only и защищены RLS/FORCE RLS; composite FK связывает decision с exact
evidence digest. Миграция — `20260916_04`.

Изолированный server-rendered `/completeness-review` показывает requirements,
unmapped и provenance, не предвыбирает dispositions и оставляет bearer только на
сервере. До production session auth он разворачивается отдельным reviewer pilot,
а не как скрыто привилегированная часть общей operator BFF. Проверка: 535
unit/API/e2e тестов без integration, 32/32 PostgreSQL integration на чистой
PostgreSQL 16, 9 doctests, Ruff, strict mypy по 44 source-файлам, lockfile и
Next.js lint/build. Решение —
[ADR-0021](../../adr/0021-persisted-document-completeness-review.md).

Тридцать первый технический срез S4 (2026-09-16): выполнен воспроизводимый
локальный machine-only прогон корневой приватной папки ТЗ. Из 13 source-файлов
pipeline напрямую обработал 9 DOCX и 1 ZIP; 2 legacy DOC и RAR честно отмечены
неподдержанными. Устранено ложное расхождение completeness guard: пустые
DOCX/XLSX units теперь учитываются как проверенные пустые, а не как потерянный
текст, без ослабления защиты mixed/scan PDF. В результате 5 native DOCX доступны
для persisted review. Дедупликация DOCX-ячеек больше не использует временный
Python `id()`: одинаковые bytes дважды дали одинаковые 2 853 блока вместо
недетерминированной потери ячеек.

Из 2 853 блоков mapper распознал один блок и создал 3 требования `power`; 2 852
блока получили `NO_PATTERN_MATCH`. Техническое block coverage около 0,035% —
это не extraction failure и не оценка recall, а evidence того, что текущий
детерминированный mapper покрывает слишком узкий набор формулировок и не
соединяет связанные ячейки таблиц. Automatic completeness — 11 `UNKNOWN`,
processing errors — 0. Приватные manifest/report/summary сохранены
под `tz_files_for_tests/pilot-results-20260916/` и исключены из Git; публичные
агрегаты и ограничения записаны в протоколе. Полный пилот не принят: human
ground truth, группировка в document sets, semantic metrics и end-to-end
case/recommendation ещё отсутствуют. Регрессия: 537 unit/API/e2e тестов прошли,
33 integration/opt-in теста штатно исключены; обязательный PostgreSQL gate —
32/32, Ruff и strict mypy по 44 source-файлам прошли.

Тридцать второй технический срез S4 (2026-09-16): regex mapper демотирован до
узкого legacy extractor; добавлен реальный semantic-analysis path через
OpenRouter и `google/gemma-4-31b-it:free`. Native blocks группируются без разрыва
строк таблиц, header повторяется между chunks. Модель возвращает только строгие
`AiRequirementCandidate`, а server-owned source blocks восстанавливают exact
document ID, locator и текст evidence. Выдуманный block ID, лишнее поле,
невалидный JSON/operator/value, provider error или timeout дают `UNKNOWN`.

Кандидаты намеренно не являются `Requirement`, не входят в compliance и не
запускают sourcing: даже технически завершённый model run сохраняет
`completeness=UNKNOWN/HUMAN_REVIEW_REQUIRED`. CLI `analyze-tz-ai` требует явный
tenant `company_id` и authorization reference на внешнюю передачу; ключ читается
только из `OPENROUTER_API_KEY`. Endpoint фиксирован, redirects/proxy environment отключены,
а routing требует `data_collection=deny`, ZDR и поддержку параметров. Решение —
[ADR-0022](../../adr/0022-openrouter-semantic-requirement-candidates.md).

Live smoke 2026-09-17 выявил две реальные provider-границы: бесплатный Gemma
endpoint не поддерживает ZDR, а Nemotron free отклоняется при запрете обучения
на free-model prompts. ZDR-профиль `inclusionai/ling-3.0-flash-vl:free` успешно
обработал один разрешённый DOCX через explicit environment proxy: 20/20 blocks,
3 source-bound кандидата, completeness остаётся `UNKNOWN/HUMAN_REVIEW_REQUIRED`.
Невалидный provider output теперь сохраняется как приватное response evidence;
единственный JSON code fence нормализуется без ослабления strict schema.
Evidence SHA-256 успешного run:
`54d48d45c1866385aba36882206f3439ec891a866fe7b0624828ab86029a618b`.
Проверка среза: 558 unit/API/e2e тестов прошли, 33 integration/opt-in теста
штатно исключены; 9 doctests, Ruff, strict mypy по 45 source-файлам и
`uv lock --check` прошли.

Тридцать третий технический срез S4 (2026-09-17): добавлены отдельные immutable
v2 schema/prompt без изменения v1 digest. `AiProcurementItemCandidate` разделяет
наименование, ОКПД2, КТРУ, единицу и точное Decimal-количество; каждое поле и
каждый код имеют собственные server-owned evidence blocks. Коды обязаны буквально
присутствовать в evidence, quantity не принимает JSON number/bool, NaN/Infinity,
неоднозначную запись, ноль или отрицательное значение. Candidate ID связан с
tenant, source document/SHA, значениями и field-level evidence; порядок citations
канонизируется, неопределённости объединяются, конфликтующие количества не
перезаписываются. Неизвестная schema version отклоняется, v1/v2 проходят только
свои ветки validation.

Финальное архитектурное ревью закрыло атомарность чанка: при любой невалидной
позиции ни требования, ни позиции этого чанка не попадают в aggregate. Проверка
literal evidence теперь требует полный числовой/классификационный token, поэтому
`2` не принимается из `12`, `-2`, `.2` или `1e3`, а ОКПД2 — из префикса КТРУ.
Decimal identity не зависит от текущей precision контекста.

Live Ling/ZDR rerun того же DOCX дал одну нормализованную позицию с названием,
ОКПД2 `17.12.14.119`, КТРУ `17.12.14.110-00000005`, `150.00 ПАЧ`, точными
blocks `b000018`–`b000020` и нулём псевдотребований. Completeness остаётся
`UNKNOWN/HUMAN_REVIEW_REQUIRED`; conversion в `LineItem`, persistence и sourcing
запрещены до независимого review. Evidence SHA-256:
`05bfe658362e9e1c25a845bab5821e717e20299eb324757a8e605ccd740d78c8`.
Проверка среза: 579 unit/API/e2e тестов прошли, 33 integration/opt-in теста
штатно исключены; 10 doctests, Ruff, strict mypy по 45 source-файлам,
Next.js lint/build и
`uv lock --check` прошли.

Тридцать четвёртый технический срез S4 (2026-09-17): добавлен import-only
persisted workflow AI-отчётов. Недоверенный v1/v2 report повторно связывается с
exact tenant document, SHA-256, полным native extraction и каждым server-owned
evidence block; дополнительно проверяются response digest и provider model.
`IMPORTED_REPORT` не выдаётся за server-managed вызов. Snapshot, решение по всем
requirement/item candidates и audit append-only; self-review, stale digest,
неполный/повторный/конкурирующий terminal review запрещены. Каждое решение имеет
`ACCEPTED | REJECTED | NEEDS_CLARIFICATION`, но completeness всегда остаётся
`UNKNOWN`, а `Requirement`, `LineItem`, compliance и sourcing не создаются.
Миграция `20260917_01` добавляет tenant RLS/FORCE RLS, composite source/evidence
FK, immutable triggers и роль `AI_REQUIREMENTS_REVIEWER`. HTTP-вызов провайдера
не добавлен: exact-payload approval и retention полного provider response требуют
отдельного продуктового решения по [ADR-0023](../../adr/0023-persisted-ai-requirement-review.md).

Проверка среза: 591 unit/API/e2e тест прошли, 34 integration/opt-in теста штатно
исключены из-за отсутствия PostgreSQL/DATABASE_URL и opt-in OCR; 10 doctests,
Ruff, strict mypy по 46 source-файлам, `uv lock --check`, единственный Alembic
head `20260917_01` и offline SQL прошли. Новый PostgreSQL integration test
собирается, но реальный runtime/RLS gate в этой среде не выполнен из-за
недоступного Docker server.

Тридцать пятый технический срез S4 (2026-09-17): подключён санитизированный
read/review API без import и provider call. `GET /v1/ai-requirement-runs`
возвращает оператору/reviewer только metadata, counts и terminal state;
reviewer-only detail показывает exact candidates/evidence. Полный extraction,
chunks, provider request/response/ID и `authorization_reference` не входят ни в
один публичный response; list/detail/decision имеют `Cache-Control: no-store`.
`POST /v1/ai-requirement-runs/{run_id}/decision` требует отдельную роль
`AI_REQUIREMENTS_REVIEWER`, exact evidence digest, полное типизированное решение
и actor-bound idempotency. Чужой и отсутствующий run одинаково дают `404`,
self/stale/second/changed replay — `409`; результат остаётся `UNKNOWN`.
High-risk review завершён с `NO MUST-FIX`.

Проверка среза: 593 теста прошли, 35 PostgreSQL/opt-in тестов штатно пропущены;
10 doctests, Ruff, strict mypy по 46 source-файлам, lockfile, Alembic single head
и offline SQL прошли. Новый real-PostgreSQL API test собран, но не запущен без
`DATABASE_URL`/`DATABASE_ADMIN_URL` и доступного Docker server.

Тридцать шестой технический срез S4 (2026-09-17): добавлен изолированный
server-rendered reviewer UI `/ai-requirement-review`. Он использует отдельный
server-only `PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN` без fallback на operator
credential, показывает очередь, exact candidates/evidence и terminal state, но не
раскрывает provider transcript, полный extraction, approval reference и не даёт
import/provider-run controls. Форма требует disposition и основание по каждому
кандидату, exact evidence digest передаётся без изменения, idempotency key создаёт
сервер. Reviewed и незавершённый run становятся read-only. COMPLETE-run без кандидатов допускает
пустое terminal review, при этом интерфейс явно сохраняет completeness `UNKNOWN`.

Проверка среза: Next.js ESLint и production build проходят; маршрут отмечен как
dynamic server-rendered. Python/storage/API gate не менялся после предыдущего
полного прогона: 593 passed, 35 skipped, 10 doctests, Ruff и strict mypy прошли.

Тридцать седьмой технический срез S4 (2026-09-17): принят import-only HTTP bridge
`POST /v1/documents/{document_id}/ai-requirement-runs`. Только `OPERATOR` может
передать ранее полученный v1/v2 report; endpoint не вызывает провайдера, а tenant,
actor, run ID и время назначает сервер. Exact JSON читается потоково с лимитом
20 МиБ, требует `application/json`, запрещает duplicate keys, non-finite numbers,
лишние поля и любую молчаливую нормализацию. Repository повторно связывает report
с точными stored bytes/extraction/text/provenance. Ответ содержит только
санитизированную metadata, помечен `no-store` и не раскрывает extraction, chunks,
provider transcript/ID или `authorization_reference`. Replay actor-bound;
ошибки разделены на безопасные `401/403/404/409/413/415/422`.

Проверка среза: 597 passed, 35 PostgreSQL/opt-in тестов штатно пропущены в обычном
локальном прогоне; 9
doctests, Ruff, strict mypy по 46 source-файлам, `uv lock --check`, Alembic single
head и offline SQL проходят. Отдельный обязательный gate на свежем PostgreSQL 16
применил все миграции и выполнил 34/34 integration/RLS теста; import report прошёл
через HTTP с replay. Изолированные container, network и volume после проверки
удалены. High-risk review
нашёл и закрыл silent nested-extra/coercion, oversized model projection и
recursive JSON ошибки; повторная проверка завершена с `NO MUST-FIX`.

Тридцать восьмой технический срез S4 (2026-09-17): усилен общий контракт
exact-payload approval перед проектированием внешней AI-передачи. Payload теперь
принимает только строгий JSON-объект со строковыми ключами, типочувствительным
детерминированным digest и ограниченной вложенностью; non-finite числа, Python-
объекты, циклы и silent coercion отклоняются. `ActionRequest`, `Approval` и
`AuditEvent` запрещают лишние поля и требуют timezone-aware время. Проверка
authorization повторно валидирует текущие request/approval, fail-closed
отклоняет повреждение и сравнивает окно как UTC instants, поэтому DST fold не
может продлить истёкший approval. Новые AI action type, роль approver, persistence
или право отправки этим срезом не введены.

Проверка среза: 29 focused action/OCR routing тестов, Ruff и mypy проходят.
High-risk review обнаружил и закрыл DST-fold bypass, пропуск повторной проверки
личности approver и нормализацию вложенного Python-объекта до JSON; повторная
проверка завершена с `NO MUST-FIX`.

Тридцать девятый технический срез S4 (2026-09-17): добавлен чистый
`ai-requirements-transfer-manifest-v1`, который детерминированно готовит, но не
отправляет OpenRouter-запросы. Manifest связывает tenant, явный document ID,
source/extraction SHA-256, reviewed model profile, prompt/schema/chunking
versions, canonical response schema и её digest, system-prompt digest, privacy
controls, fixed HTTPS endpoint/non-secret headers/no-proxy transport и точные
UTF-8 bytes/digest каждого упорядоченного chunk. Статусы всегда
`APPROVAL_REQUIRED`, `send_allowed=false`, approval/retention — `UNRESOLVED`.
Секрет, время, случайный ID, persistence, HTTP route и право исполнения не
добавлены. Adapter, manifest и analyzer fallback теперь используют один
canonical request serializer.

Manifest повторно строит chunking из единого ordered набора source records;
разрешено только предусмотренное повторение идентичного table header. Подмена
типов `true/false` на `1/0`, конфликтующий повтор block, duplicate chunk,
изменение model/prompt/schema/privacy/transport/body или digest отклоняются.
Pure builder не доказывает соответствие source SHA реальным tenant bytes и
поэтому явно помечает source binding как in-memory unverified. Проверка среза:
50 focused AI-тестов, Ruff, format и mypy проходят; adversarial high-risk review
после закрытия двух обходов завершён с `NO MUST-FIX`.

Сороковой технический срез S4 (2026-09-17): добавлен immutable
`document-set-evidence-manifest-v1` для явного выбора комплекта из 2–10 exact
single-document completeness reviews. Порядок, scope, source document/SHA,
mapper version/confidence и review/evidence digest входят в
server-owned manifest digest; duplicate source через другой review запрещён.
Repository заново проверяет stored bytes/extraction, а status всегда остаётся
`UNKNOWN/MULTI_DOCUMENT_REVIEW_REQUIRED`: constituent `PASS` не превращается в
доказательство полноты комплекта.

`POST /v1/document-set-evidence-manifests` доступен только `OPERATOR`, требует
actor-bound idempotency и читает strict JSON потоково с лимитом 16 КиБ, запретом
duplicate keys и non-finite values. Точечный GET tenant-scoped; оба ответа
`no-store`. List/latest, terminal multi-document decision, case ingestion, UI и
external AI отсутствуют. Миграция `20260917_02` добавляет две append-only
RLS/FORCE RLS таблицы; exact review/evidence FK и deferred trigger проверяют
полное совпадение JSON/rows и source/mapper binding; сам exact review digest
связывает extraction без дублирования производного хеша.
Aggregate logical snapshot budget — 20 МиБ до materialization.

Проверка среза: 41 focused domain/API тест прошёл; fresh PostgreSQL 16 применил
все миграции и выполнил 35/35 integration/RLS тестов, включая откат неполной и
подменённой direct-SQL записи. Ruff, scoped format, strict mypy, Alembic single
head `20260917_02` и offline SQL проходят. Контракт —
[ADR-0024](../../adr/0024-document-set-evidence-manifest.md). Три раунда adversarial
high-risk review закрыли direct-SQL source projection, body/resource limits,
logical-size budget и OpenAPI contract; финальный verdict — `SAFE/NO MUST-FIX`.

Сорок первый технический срез S4 (2026-09-17): добавлен terminal
`document-set-completeness-decision-v1` для независимой проверки exact manifest.
Reviewer получает заново восстановленные constituent snapshots и terminal
decisions, обязан подтвердить каждый member, inventory и cross-document review,
а findings связываются с точными source blocks/mapping fields. Разные непустые
сроки поставки автоматически создают `UNRESOLVED_CONFLICT`; удалить или подменить
server finding/digest через payload нельзя.

Статус выводится fail-closed: доказанный материальный пропуск/отсутствующий
документ даёт `FAIL`, полный exact scope без findings — `PASS`, любой недоказанный
пробел или конфликт — `UNKNOWN`. Reviewer независим от manifest/snapshot authors.
Решение не объединяет mappings, не выбирает latest, не подключается к case и не
разрешает `PARTICIPATE`.

Миграция `20260917_03` хранит decision и ordered member attestations в двух
append-only RLS/FORCE RLS таблицах. Exact FKs и deferred trigger проверяют
manifest member count/scope и review/evidence binding. Repository выполняет
scalar-only preflight размера до загрузки JSON (40 МиБ), повторно проверяет stored
bytes/extraction/decision digests и реконструирует решение при чтении. Reviewer
API предоставляет evidence GET, strict streamed POST до 256 КиБ и decision GET;
ответы `no-store`, OpenAPI полностью описывает вложенные strict contracts.
Контракт —
[ADR-0025](../../adr/0025-terminal-document-set-completeness-review.md). Несколько
раундов Astra high-risk review закрыли подмену server projections/digests,
cross-tenant binding, strict nested-model bypass, неполный direct-SQL набор,
preflight materialization и неполный OpenAPI; финальный verdict — `SAFE`.

Совокупный gate после срезов 38–41: 639 passed, 37 PostgreSQL/opt-in тестов
штатно пропущены без внешней БД/моделей; 10 doctests, Ruff, strict mypy по 48
source-файлам, `uv lock --check`, Alembic single head `20260917_03` и offline SQL
проходят; Next.js lint/production build также успешны. Отдельный fresh PostgreSQL
16 gate применил все миграции и выполнил
36 integration/RLS тестов; один opt-in PaddleOCR тест штатно пропущен. Scoped
format-check изменённых Python-файлов проходит; несвязанный массовый rewrite
существующего worktree не выполнялся.

Сорок второй технический срез S4 (2026-09-17): добавлен изолированный
server-rendered экран `/document-set-review?manifest_id=<exact-manifest-id>` для
терминального review конкретного комплекта. Экран не имеет очереди, выбора
`latest` или fallback на operator credential; API URL и выделенный
`PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN` остаются только в серверном процессе
Next.js. Перед записью server action повторно получает exact evidence, сверяет
manifest digest и все ordered constituent references, а затем заново выводит
`PASS` только при constituent `PASS`, полном `REVIEWED_IN_SCOPE`, подтверждённом
inventory, закрытом cross-document check и отсутствии server findings. При
constituent `UNKNOWN` записывается только `UNKNOWN`; constituent `FAIL` блокирует
первую версию формы, потому что она намеренно не подменяет обязательный typed
confirmed finding свободным текстом. Уже принятое terminal decision показывается
read-only; FastAPI остаётся единственным authority для всех gates.

Проверка среза: Next.js ESLint, TypeScript и production build проходят; маршрут
собирается как dynamic server-rendered. Повторный Astra high-risk review после
исправления constituent-status semantics дал `SAFE/NO MUST-FIX`. Python/storage/API
gate не менялся после полного прогона среза 41: 639 passed, 37 skipped, 10
doctests, Ruff, strict mypy, lockfile, Alembic/offline SQL и fresh PostgreSQL 16
integration gate прошли.

Сорок третий технический срез S4 (2026-09-17): тот же exact-manifest reviewer
получил ограниченный typed `FAIL` editor. Агрегатный `FAIL` выводится либо из уже
принятого constituent `FAIL`, либо из нового
`CONFIRMED_MATERIAL_OMISSION | CONFIRMED_MISSING_DOCUMENT`, связанного с выбранным
source block свежего evidence. Произвольные finding ID, origin, mapping path и
source reference не принимаются: server action строит их сам, повторно загружает
evidence и сверяет manifest/constituent digests и границы блока. Server findings
не выдаются за reviewer findings, но участвуют в общей проверке
`OPEN_ISSUES | CHECKED_NO_OPEN_ISSUES`; confirmed missing document несовместим с
подтверждённым inventory. `UNRESOLVED_*` не повышается до `FAIL`.

Next.js ESLint и production build после изменения проходят. Astra проверил 216
комбинаций доменных состояний и семь tampering-сценариев; verdict —
`SAFE/NO MUST-FIX`. UI намеренно создаёт не более одного нового confirmed finding
за terminal decision; API сохраняет полный typed contract до 20 evidence refs.

Сорок четвёртый технический срез S4 (2026-09-17): владелец продукта утвердил
одноразовый exact-payload approval независимого `AI_TRANSFER_APPROVER` с окном
ровно 15 минут и 30-дневное защищённое хранение полного provider raw response.
Решение закреплено в
[ADR-0026](../../adr/0026-exact-ai-transfer-approval-and-response-retention.md).

Добавлены immutable `persisted-ai-transfer-request-v1` и
`persisted-ai-transfer-approval-v1`. Server-owned request повторно связывает
exact stored source bytes/extraction с endpoint, model, privacy controls,
prompt/schema/chunking versions, ordered canonical request bytes и digest каждого
chunk. Approval подписывает digest всего request, требует другого actor,
timezone-aware UTC-интервалы и действует только в точном 15-минутном окне;
DST-fold, self-approval, predating, stale digest и изменённый replay отклоняются.

Миграция `20260917_04` добавляет append-only RLS/FORCE RLS таблицы request,
ordered chunks и approval, composite exact-source FKs и deferred projection
triggers. `POST /v1/documents/{document_id}/ai-transfer-requests` доступен только
`OPERATOR`; exact GET доступен владельцу request или `AI_TRANSFER_APPROVER`;
approval endpoint принимает только exact request digest. JSON читается потоково
до 16 КиБ и fail-closed отклоняет duplicate keys, non-finite/deep/oversized
значения и silent normalization. Ни один endpoint этого среза не вызывает
провайдера и не выдаёт execution authority.

Совокупный gate после среза 44: 649 passed, 40 PostgreSQL/opt-in tests skipped в
обычном прогоне; 9 doctests, Ruff, scoped format-check, strict mypy по 49
source-файлам, `uv lock --check`, Alembic single head `20260917_04` и полный
offline SQL проходят. Fresh PostgreSQL 16 применил все миграции с нуля и выполнил
39 integration/RLS тестов; один opt-in PaddleOCR test штатно пропущен. Astra
high-risk review завершён с `SAFE/NO MUST-FIX` для request/approval-only границы.

Сорок пятый технический срез S4 (2026-09-17): добавлен durable execution
admission, который атомарно и одноразово потребляет exact approval, но ничего не
отправляет. Admission создаёт только тот `OPERATOR`, который подготовил request;
другой idempotency key или actor не создаёт второе право. Server time берётся
через PostgreSQL `clock_timestamp()` после locks и полной source revalidation,
а replay после expiry возвращает только тот же исторический admission.

Внутренний worker boundary умеет создать permanent claim только первого chunk.
Claim фиксирует exact admission/request/chunk digests, `attempt=1`,
`PERMANENTLY_CLAIMED` и `DELIVERY_UNKNOWN` до сети. Он commit-ится до возврата
fresh claim вызывающему worker; чтение или повторный вызов никогда не возвращают
новое право dispatch. Второй chunk намеренно запрещён на уровне migration
`20260917_05`: без доверенного terminal success receipt первый claim не доказывает
успешную доставку.

Две новые таблицы append-only, защищены RLS/FORCE RLS, composite FKs, one-run и
one-claim uniqueness, exact JSON projections, actual-clock expiry/freshness
triggers и runtime `SELECT/INSERT` grants. Public API предоставляет только
owner-only admission POST и exact metadata GET для владельца/approver; public
claim endpoint, очередь, HTTP transport, success status и raw response отсутствуют.

Проверка среза: full no-DB gate — 662 passed и 41 PostgreSQL/opt-in skipped; 9
doctests, Ruff, scoped format-check, strict mypy по 50 source-файлам,
`uv lock --check`, Alembic single head `20260917_05` и offline SQL проходят.
Fresh PostgreSQL 16 применил все миграции с нуля и выполнил 40/40 обязательных
integration/RLS тестов, включая concurrency, forged/backdated/expired direct SQL,
ordinal skip, immutable rows и HTTP roundtrip. Astra high-risk review —
`SAFE/NO MUST-FIX` для admission + first-claim-only границы.

Сорок шестой технический срез S4 (2026-09-17) завершил безопасную границу
первой попытки без включения live worker. `ExactAiTransferHttpClient` отправляет
ровно сохранённые UTF-8 bytes одним HTTP-вызовом, не использует environment proxy,
redirect или retry, потоково ограничивает raw capture и валидирует HTTP 200,
provider envelope, exact model и wire-v2. Полностью полученная ошибка становится
`FAILED`, а timeout, disconnect, compression, incomplete или oversized response —
`DELIVERY_UNKNOWN`; тело, assistant content, API key и provider error text не
покидают transport boundary.

Миграция `20260917_06` добавила immutable tenant-scoped terminal receipt первого
claim с exact composite FK, outcome/reason-specific CHECK, exact JSON projection,
RLS/FORCE RLS и минимальными grants. Внутренняя repository-транзакция связывает
receipt с claiming worker, request/claim digests и audit; public receipt POST и
live OpenRouter execution отсутствуют. Execution GET показывает только безопасную
metadata. Второй chunk по-прежнему запрещён.

Проверка среза: 695 no-DB тестов и 42/42 обязательных PostgreSQL 16 integration/RLS
теста прошли; узкий transport/execution набор — 33/33. Ruff, strict mypy,
Alembic single head `20260917_06` и полный offline SQL проходят. Fresh PostgreSQL
gate создал базу с нуля, проверил concurrency, forged receipt, append-only и RLS,
затем удалил временные container/network/volume.

Историческая граница предыдущего среза закрыта следующим bounded slice. Exact
reviewed mapping явно связывается с case ingestion позднее; production
sessions/RBAC/MFA для reviewer UI остаются отдельной задачей. Выбирать
«последний PASS» автоматически запрещено. Отдельно остаются маркировка/повторный
review legacy catalogs, политика разрешённого fetch URL, vision provider/retention
policy и production calibration. Мониторинг источника не начинается без
завершённого доказательного пути.

Сорок седьмой технический срез S4 (2026-09-17): bounded complete provider
response сохраняется отдельно от terminal receipt в tenant-scoped зашифрованном
хранилище. Для каждого blob генерируется отдельный случайный DEK; DEK
оборачивается tenant KEK через явный provider protocol, тело шифруется
AES-256-GCM с отдельным nonce, а canonical metadata/AAD и envelope получают
точные SHA-256. Plaintext response, ключи, authorization и provider error text
не попадают в SQL, API или audit.

`persist_captured_ai_transfer_result` принимает только complete bounded attempt и
одной транзакцией записывает immutable receipt, raw metadata, encrypted blob и
audit. Схема `20260917_07` использует exact FK к terminal receipt, deferred
projection checks, RLS/FORCE RLS и минимальные grants. Неполный, unknown или
oversized transport остаётся без raw capture. Reviewer и auditor получают
точечное no-store чтение raw; оператор и approver его не читают, каждый доступ
аудируется.

После `received_at + ровно 720 часов` raw недоступен независимо от задержки
cleanup. Purge сначала immutable записывает deletion receipt, затем удаляет
ciphertext и wrapped DEK; metadata, digests, candidates, review и audit остаются.
Deferred anti-resurrection checks запрещают удалить blob без receipt, вставить
его обратно или подменить projection. `UNKNOWN`/`FAIL` не превращаются в
положительный исход.

Focused checks passed; final gate pending. Live external worker по-прежнему
отключён: production tenant KEK provider и доказательства backup/WAL/restore
retention ещё не готовы и не должны считаться готовыми. До их подтверждения
capture в production не включается.

## S5 — поставщики, логистика и финансовый график

Статус: **запланировано**.

Supplier discovery, RFQ drafts, разрешённая отправка после exact approval,
Quote Analyzer, несколько поставщиков/позиций, плечи/адреса и cash-flow.
Налоги и расходы, зависящие от ставки, пересчитываются при изменении цены.
Для платформ — импорт каталогов и оферт, допуск канала, отдельные действия продаж.

## S6 — заявки, исполнение и post-award

Статус: **запланировано**.

ApplicationPackage, гарантии и договоры, транзакционная одноразовость approvals,
Local Executor, receipts, контроль поставки/приёмки/оплаты и прогноз-факт.
Параллельные попытки исполнить одно действие не приводят к повторной отправке.

## S7 — история, обучение и масштабирование SaaS

Статус: **запланировано**.

Аналоги и калибровка прогнозов, аналитика по событиям, предпочтения отдельно
от hard policy, тарифы и ограничения ресурсов. Базовая tenant isolation
реализуется в S2, а не откладывается на этап масштабирования.

## Правило перехода

Следующий этап начинается после проверяемого результата предыдущего. Приоритет
можно изменить по фактической зависимости или решению владельца, обновив этот
файл. Для каждой итерации фиксируются результат, проверки и оставшиеся ограничения;
не создаются дублирующие списки задач в нескольких документах.
