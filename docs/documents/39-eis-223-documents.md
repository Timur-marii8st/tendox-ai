# Документы223-ФЗ: exact manifest и native preview

## S157: контракт

Отдельный11digit ref:number/version/XMLSHA. Manifest строится только из
сохранённого typedXML; каждый reference имеет ordinal,UID,filename,publicURL,
исходный XML locator. max32 references, UID уникален; count consistency,
unsafe filename/private URL/missingUID дают UNKNOWN_MANIFEST до скачивания.
XML не сообщает размер — declared_byte_count=null. Это не контроль наличия
всех требуемых юридических документов или полноты ТЗ.

Operator command scripts/server-eis-223-document.py принимает exactref+UID;
tenant фиксирован local-eis-supplier. Один файл максимум20MiB/100MiB exactset,
DB100GiB/free40GiB guard. Stale/expired known state проверяются до I/O и после.
Download только exact official223public path/UID, Chromium validTLS и shared
60s host lease; redirect/HTML вместо download/unsafeURL не принимаются.
Нативный existing v3-doc analyzer, без внешнего LLM/макросов/OCR approvals.

Immutable eis_223_document_receipts: original bytes+fullSHA, exactrefFK,
UID/URL/filename/source locator, nativeanalysis/parser version/time. FORCE RLS,
INSERT-only, original SHA/byte count/analysis identity constraints; manifest
trigger сопоставляет единственный UID/URL/filename/locator с exact sourceXML.
Receipt+audit атомарны. Tenant advisory lock сериализует one-file operations.
Replay ранее полученного exactUID не скачивает/не анализирует/не пишет audit.
Downgrade с receipt history запрещён. Migration20261002_09.

GET /v1/tender-discovery/eis-223-documents/{number}?version=...&xml_sha256=...
только читает, tenant из bearer, доступен auditor, Cache-Control:no-store.
UI «Показать сохранённые документы223-ФЗ»: число полученных/listed, manifest
UNKNOWN, extraction result, actualbytes/SHA, до18conditions/600chars each,
locators и видимые ограничения. Full retained analysis вreceipt; bodyне содержит
original bytes. COMPLETE_LISTED_SET означает получение перечисленных файлов;
review/eligibility/economics всегда UNKNOWN. ExtractionPASS не допуск.

Этот milestone не создаёт пользовательскую background queue223. Следующий
milestone добавляет persisted request/worker/API/UI для выбора документов.
Пример запуска наVPS под eis-import.lock, без передачи API/source token вCLI:

```bash
python scripts/server-eis-223-document.py --number NUMBER --version VERSION \
  --xml-sha256 XML_SHA256 --uid EXACT_CONTENT_UID
```

## Проверка

Synthetic manifests/unsafeURL/count/duplicateUID, APItenant/auth/read-only,
isolatedPG immutable receipt/replay/other tenant/FK/SHA/manifest guard,
stale/deadline/resource guard; webbuild/ESLint иlivefile evidence дополняются
после server deployment. Реальные source bytes хранятся только наVPS.

S157 live:32616419658v2,393665bytes/DOCX/243blocks/90conditions,1of8files.
ExactSHA27c82fe85895fe628b3fdce98fa390b510fafd5af2eeefdb75d22fa84e3eb557.
124local/48PG/64Linux/build/ESLint/Ruff/mypy/deploy passed; API0.101792s,
GETno mutations/replay0network. Sourcequality/extraction != eligibility.

## S158: persisted очередь по кнопке

POST /v1/tender-discovery/eis-223-document-jobs принимает exactref; только
operator, tenant из auth. Журнал запросов immutable/RLS/FK, idempotent replay,
max10active jobs и10new requests/hour. Stale/expired/ambiguousmanifest отклонён.
GETstatus не пишет/не скачивает, показывает requested/queue_status/last_failure.
Worker выбирает самый ранний eligiblejob/file SQLпроверкой receipt/latest/time/
retrylimit до чтения большогоpayload. Одна операция/file за проход, receipt
использует S157путь. Safe append-onlyattempt/status/explicit reason+audit;
RECEIVED требует exactreceipt, UID проверяется по sourceXML. Максимум5actualfailure attempts
на exactUID; ROBOTS_CRAWL_DELAY/SOURCE_BUSY — deferrals, не расходуют этот лимит. Cooldown/SOURCE_BUSY60s, прочие sourceerrors30min; задержка учитывает
сохранённые попытки. При исчерпании всех оставшихся файлов ATTENTION_REQUIRED.
Completed/stale/exhausted jobs не отнимают выбор у новых, UNKNOWN не становитсяPASS.

Штатный minutecron scripts/server-eis-documents.sh чередует44/223 по
сохранённому tenant cursor вstate/eis-documents/local-eis-supplier/next-law.
Cooldown сохраняет ход той же очереди; успех/idle/реальная ошибка переключает
семейство. Общий importlock иhost60sdelay сохраняются. Один файл суммарно
за проход, pending223конкурирует со штатными sourcewindows. Без дополнительных
browsers/concurrency/heap и без загрузки документов на ноутбук. Ошибка источника
видна вUI; файлы иистория не удаляются. Queue продолжает работать при закрытомUI.

UI «Собрать документы на сервере» ставит запрос; «Показать сохранённые документы
223-ФЗ» обновляет текущий статус. Request не отправляет заявку/КП и не даёт допуск.
Source requests, original bytes иnativeparser остаются наVPS. Migration20261002_10.

S158 pre-final gates:132focused local/50isolatedPG/72Linux+5router tests,
Ruff/mypy/webbuild/ESLint. Linux router tests simulate sourcebusy/cooldown,
actualfailure/progress/idle and verify fairness cursor without any HTTP.
Live UIrequest persisted1job; worker downloaded specification18770bytes,
SHA9c74b69ede01779973219192fd9d56186c9b7aa14b73a455295130b168ca0dd7,
nativePASS. ExactUID6DE72CBF94EC402BA785772DEE5EF661, same32616419658v2.
Replay0HTTP/0audit; proof s158-queue-proof-20261002T182440521940Z.json,
SHA614db3d8fdd907adaf4c2def599c5a1eb10b0230bada8d1ffc96399f985c9ab5.
Source persistedqueue continues whileUIclosed; contention may delay files.

## S158 завершение

FinalAPI0.170771s; GET and repeatPOST do not change receipts/jobs/attempts/audit.
Proof s158-api-proof-20261002T183652653719Z.json,
SHA42cf510370a42605a22728620baa503976ecff89de5d7efed31f3edf4c8dc829.
CUA verifiedrealrequest and automaticprogress5of8/QUEUED, remaining3 pending.
5Linuxroutercases validate deferredsamefamily/success/idle/actualerrorrotation.
132local/50PG/72Linuxsource+5router tests and finaldeploy confirmed. TestDBremoved.
Migration20261002_10. WholeEIS coverage/completeness/review/profit remainUNKNOWN.

## Сравнение выбранных карточек (S159)

`POST /v1/tender-discovery/eis-223-comparison` принимает `notices` с 2–3
разными exactref: 11-значный номер, версия, полный XML SHA-256. Это read-only
операция, разрешённая аудитору; tenant берётся из авторизации. Все данные
сравнения читаются в одной READ ONLY REPEATABLE READ транзакции с единым
timezone-aware `checked_at`. Ответ no-store; скачивания, задачи, audit writes
и пересчёт native analysis не выполняются. Недоступная карточка даёт404 всей
операции; конфликт digest/evidence409. Порядок ответа соответствует выбору.

Каждая строка сохраняет исходные лоты/валюты/Decimal суммы/количество/единицы
и XML provenance, окно/ответ/архив, отдельные XSD проверки, статус очереди и
полученных документов. Preview: максимум18 условий на файл,600символов на
условие; `snippets_total` и `preview_truncated` явно показывают сокращение.
Сохраняются UID/URL/SHA файла и locator каждого фрагмента, включая ZIP members.
Полный текст остаётся в receipt, отдельный просмотр карточки доступен.

Устаревшая известная версия или подтверждённый истёкший срок дают `BLOCKED`.
Неподтверждённый timezone остаётся UNKNOWN. В остальных случаях
`NEEDS_ANALYSIS`: отмены/стадия/полнота ТЗ/роль документов/допуск/экономика
ещё не подтверждены. Source XSD FAIL показан как ошибка источника и не
подменяет supplier hard gate. НМЦ лота не является оценкой прибыли;
`profit_order_status=UNKNOWN`, никакого рейтинга или PARTICIPATE.

В разделе223 выбираются максимум3 карточки, кнопка становится доступна от2.
Новый поиск сбрасывает выбор и сравнение; смена выбора убирает старый результат.
Сбор документов остаётся отдельным явно заказанным действием пользователя.

### Проверка S159, 02.10.2026

143 local/51 isolatedPG/83 Linux tests, Ruff/mypy/web build/ESLint прошли.
Развёрнуто на VPS без миграции; HEAD20261002_10. Реальный POST сравнил
32616419658v2 и32616383798v2 за0.239507s, повтор0.047623s; counts/audit/jobs
не изменились. Полный proof хранится только на VPS в research/223 tenant path:
`s159-comparison-proof-20261002T191123480405Z.json`,
SHA `eae1477681962aa83ccc2399bc646a12ad535fb2e5b383d16a6ccf76eb1591b1`.
Разные предметы в техническом тесте не становятся экономически сопоставимыми.

CUA подтвердил три колонки, максимум3 выбора и reset при новом поиске,
цены/позиции/8из8 документов стабилизатора/conditionSHA+locator, отдельный
source XSD FAIL у32616432455v1. XML locators доступны в сворачиваемых блоках.
Никакого вывода о полноте ТЗ, допуске или прибыли не сделано. TestDB удалена.

