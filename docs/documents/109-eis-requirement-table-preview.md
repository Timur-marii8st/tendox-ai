# S227 — сохранённая таблица DOCX рядом с товаром

Статус: COMPLETE в описанных границах, установлен на VPS 2026-10-06.

## Контракт

Read-only source0 preview связывает exact S226 report/current позицию, один
полученный DOCX, receipt/SHA, authoritative `eis-native-review-v1` и номер
таблицы. Existing prepareReview выполняется отдельно и явно. Preview не
скачивает документы, не читает source HTML/DOCX bytea, не создаёт analysis,
audit, jobs или новую persisted сущность.

POST `/v1/tender-discovery/eis-requirement-preview/preview`: `{request}`;
request содержит `product` (S226 request), `document` (ReviewDocumentRequest),
`table_index`1..100. Caller URL/tenant/строки/mandatory/цены запрещены. Same notice
обязателен. Одна readonly repeatable-read tenant transaction с15s timeout;
metadata limits до hydration, ответ≤256KiB/no-store. Preview SHA связывает весь
результат: product/report digest, analysis digest, receipt/time, request,
parser revision. Current/hold/tenant guards проверяются при каждом запросе.

Парсер поддерживает наблюдённые пять колонок: наименование, тип, значение,
единица, инструкция. Все сохранённые text cells, section rows и инструкции
сохраняются с block index, Unicode character count, locator и SHA. Caps:
24data rows/2kcell/16kchars. Duplicate coordinates/labels, nested tables, gaps,
неподдержанный header отклоняются без усечения.

Старое extraction не хранит пустые/merged cells и spans. Missing column —
`NO_RETAINED_TEXT`, структура исходной таблицы UNKNOWN. Полнота retained
extracted text не равна полноте DOCX или ТЗ.

Hints не являются исполняемыми Requirement. `≥80 и <90` — две границы GE80 и
LT90, не inclusive BETWEEN. Марки C/С/Сэ, A4/А4 и80±3 не получают автоматическую
эквивалентность. Связь по названию помогает просмотру; mandatory/approval/
document role/position association/fullTS/technical/participation UNKNOWN.

## Реальное основание

Старые S221 associations у бумаги — обоснование цены КУМС (название объекта и
сумма). Их нельзя повышать в требования. В извещении0107300009526000178v2 уже
получен POD `ОПИСАНИЕ ОБЪЕКТА ЗАКУПКИ - КУМС.docx`, UID
`01A0E7C8D54B7D0FA7D7FFBA773CBE16`, SHA
`727bf17ff7b085e150ace59cab5016512ff6ba16026e890393ee7fb85e5863c2`.
Review сохранил55blocks. Таблица2: Формат/A4, Марка бумаги/не ниже С,
Количество листов в пачке/≥500/Штука, контекст «Дополнительные характеристики*»,
Масса бумаги площадью1м2/≥80 и <90/Грамм. Инструкции различают неизменяемое и
конкретное значение. Explicit prepareReview1808мс/source0 записал одну
analysis+audit; это отдельная операция, не readonly preview. Нормативная роль
документа и связь с выбранной позицией остаются UNKNOWN.

## Acceptance и следующий этап

474 Python/API/PG PASS/zero skips, 106 Node wire/render+TypeScript+ESLint+production
build PASS. Source24tests, preview/API8tests и5realPGtests включены в общий gate.
Independent source/backend review: блокеров не осталось. Исправлено только
ожидание foreign-tenant отказа в PG тесте; runtime доступ не менялся.

Installed API13:47:17UTC: table2/5rows/4characteristics/1context/24cells/4instructions.
GE80/LT90 и GE500 сохранены отдельно. Повторный preview215–268мс,34593байт,
одинаковый hash; source0/jobs0/write0. Негативные проверки401/413/422/404.
Installed Next Actions230–338мс и compiled SSR PASS: все четыре характеристики
имеют опубликованное поле товара, инструкции и provenance видны. Подмена
URL/tenant/booltable/unsupportedtable отклонена. Browser visual NOT_PERFORMED.

Preview SHA `eab4d371d8b7037bff6fd26ca58f5de9a1b9e0d664ae4a2e9cf35a0f6493ccbb`;
exact product report SHA `337110fcad60a0fbd259f6150de0e9af3f6304124f5ec52e41a5fe3d18afe044`;
review analysis SHA `79ad0ce4d2a8ba651e973358dc4a78e88f12c8413284f5b7f8ddad607b89da17`.
Это digest draft-просмотра, не независимое одобрение требований.

Preview/NextActions не увеличили source bytes/derivedrows/analysis/receipts.
Во время exact API before/after: product1/catalog4/catalogbytes242753,
analysis142/receipt95/blobbytes5181668/audits198634 без изменений.
Позже обычный intake добавил8audit events (4schema/2window/2sync223); они
проверены отдельно и не приписываются preview. Cron/intake продолжаются.
Sourcehelpers0/OOMfalse/testDB0/health200, schema07 без новых миграций.
DB6001007639/free250253279232 байт; API123.4MiB/1GiB, web64.27MiB/768MiB.
Новых source HTML или архивов на ноутбуке нет.

### Evidence и pins

Proof приватны на VPS `/home/syurai/vibe-seller-state/` и
`/var/lib/eis-browser/research/rejected/`.

| Основание | SHA256 |
| --- | --- |
| Python/API/PG log | `84dd5d9d617be476dbd58dd8431969a77f1d34d22dc0d616a04dd238fb8623a7` |
| Проверенный src/tests/migrations manifest | `14964b7336c3be777dafc7d467c651a18efd74cbd959da6ace80a28ee8083ba4` |
| Node/production build log | `37588ba7eb93a605830677b005710e1135cb8ecc9e5111b45c231b5d760882ed` |
| Installed API live proof | `70b6eaa7ef5db1e5c2b45c1a9b279ced7be8154391b8a87076f77d661e547d24` |
| Installed Next Actions/SSR proof | `c75442b2358c0e156afaf8fcc7787cdc7ec820571ee01cecac91be3bd8957dd7` |
| Operations proof | `929edbeaa82fcf270dddcd9e774a213e3dcb7557e080f460aeee324ae5c5b0d6` |
| Cleanup/intake audit census | `95891faa462d8ed665f981303ae61f1eed3f18850e80c020946652d4ccba6581` |

API image `sha256:93ed4a1c98ec98a78f10b9c5c5819f8090795b72ce4711a26898bd74fd9d6efe`.
Worker image `sha256:aeadf68674fe4712eaa2896f14c28875f2fb5d101f78e46e46b4524ceac93db0`.
Web image `sha256:90270ec634327f652022cc36e51eec8270f4f1cb06944777f4b16cfe562f6fb9`.

### Как проверить

В `/tender-discovery` откройте сохранённое S226 сопоставление выбранного товара.
В «Характеристики из документа закупки» нажмите «Показать полученные DOCX»,
выберите описание объекта. Откройте/разберите его сохранённый текст, укажите
номер нужной таблицы и нажмите «Показать таблицу рядом с товаром».
Для тестовой бумаги КУМС это таблица2. Preview читает authoritative reviewv1,
не смешивая block indices со старым native-v3 или с другим документом.
Неподдержанные layouts отказывают явно. Это просмотр источников и hints;
исполняемые требования и независимый review ещё не реализованы в этом пути.

S228: exact-digest proposal/review интерпретации и нормативной роли, независимый
reviewer, нормализация атрибутов и существующий compliance engine. Preview и
filename/native PASS не создают reviewer PASS. Mandatory FAIL блокирует;
полный допуск требует полноты ТЗ, действующего КП и трёх сценариев экономики.
