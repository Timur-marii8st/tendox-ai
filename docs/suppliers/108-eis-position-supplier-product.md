# S226 — условия выбранного товара рядом с позицией ЕИС

Статус: COMPLETE в описанных границах, установлен на VPS 2026-10-06.

## Контракт

Источник — точный сохранённый S225 PRODUCT и его HTML, текущая позиция ЕИС.
Новых HTTP-запросов нет. Парсер читает одну активную основную карточку «Бумага-С»,
связывает её видимое название с Product metadata и сохраняет исходные поля.
Рекомендованные товары и скрытые/inert блоки не подмешиваются в характеристики.
Неоднозначные/незакрытые выбранные блоки не получают EXTRACTED.

Содержимое товара, обозначение упаковки, единица цены и параметры формы заказа
разделены. «500 листов», «5/100» и `data-package=5` не доказывают цену за пачку,
минимальный заказ или шаг заказа. Отсутствующее условие остаётся UNKNOWN.
Каждое опубликованное поле имеет raw value, HTML SHA256 и DOM locator.

Интерфейс показывает «характеристика ЕИС / записано заказчиком / опубликовано
у товара / проверка». Связь по ограниченному словарю названий сохраняет исходные
индексы обеих сторон, включая дубликаты. Она не подтверждает соответствие.
В этом срезе все строки UNKNOWN: публичный XML и связи фрагментов пока не являются
проверенным полным составом mandatory-требований. Проценты и допуск не выводятся.

POST `eis-supplier-product/prepare` и `read` принимают `{request}`. Request:
`catalog` — exact S225 PRODUCT request, `product_run_id` — UUID его сохранённого
результата. Нет caller URL/query/tenant/сырого HTML/чисел стоимости. Prepare —
OPERATOR, read — аутентифицированный tenant, request 4096 байт, ответ no-store.

## Хранение и ресурсы

Отдельный immutable tenant report, parent composite FK, unique tenant cache и
audit. Привязаны current position SHA, parent report/body SHA и parser/mapping
revision. Размеры проверяются до hydration: parent/report до256KiB, HTML до2MiB.
Повторный prepare/read не загружают raw HTML и не запускают parser. Raw HTML
не копируется в новую таблицу и остаётся на VPS. Глобальный slot ограничивает
параллельные разборы, tenant lease предотвращает дублирование записи.

Техническое соответствие, полнота ТЗ, единичная себестоимость, стоимость партии,
НДС, доставка, прибыль, полное КП и участие не подтверждены.

## Реальные сохранённые данные

ЕИС: `0107300009526000178` v2, позиция1, 400 пачек. Публичные характеристики:
листов >=500, марка «Не ниже С», формат А4, масса бумаги >=80 и <90 грамм/м².
Legacy range completeness=false; это не основание вычислять технический PASS.

SvetoCopy ECO: А4, «80 +/- 3г/кв.м», «Сэ», «500 листов», упаковка «5/100».
Price basis в сохранённом HTML не заявлен. При цене299.6RUB нельзя автоматически
считать 299.6×400 стоимостью необходимой партии.
HTML SHA256: `82b4393608fa9402dbeef32676a875c116d40d182c59230566b73f93c75af411`.
Основание: exact S225 PRODUCT snapshot, [предыдущий этап](107-eis-position-supplier-catalog.md).

## Acceptance и следующий этап

Проверены source ambiguity/hidden/conflict/limits, exact tenant/current/hold,
parent/body digest, immutable/cache noHTML/noHTTP, isolated PG, production build,
installed API/Next Actions и SSR. 437 Python/API/PG тестов PASS, zero skips;
94 Node wire/render теста, TypeScript, ESLint и production build PASS.
Astra source review и отдельный backend closure review: блокеров не осталось.

Installed API: `47fa1294-0c17-4896-ad3b-ec63a07f947e`, шесть полей поставщика,
четыре строки публичной позиции, все UNKNOWN. Упаковка `5/100`, содержимое
`500 листов`, control `data-package=5`, price basis отсутствует. Первоначальное
создание сохранено и проверено; его время не сохранено из-за ошибки проверки
Decimal в исследовательском helper. Сам отчёт не изменялся. Read163мс и cached
prepare142мс; source0/jobs0. Отрицательные API проверки:401/413/422/404.
Next Actions read260мс/cachedprepare156мс и compiled SSR PASS, источник0/записи0;
подмена caller URL/tenant и SEARCH вместо PRODUCT отклонены. Визуальная проверка
браузером NOT_PERFORMED.

Tenant census: product1/audit1, page8/audit8, catalog4/audit4; сохранённые тела
каталога242753 байт остались прежними. Новых supplier HTML/архивов на ноутбуке нет.
Schema `20261006_07`; health200, testDB0, sourcehelpers0, OOMfalse.
DB5991701527 байт, свободно250369658880; API122.1MiB/1GiB, web64.88MiB/768MiB.
Обычный intake продолжался; SHA cron не изменён.

### Evidence и pins

Все proof приватны на VPS: `/home/syurai/vibe-seller-state/` и
`/var/lib/eis-browser/research/rejected/`. Контрольные суммы:

| Основание | SHA256 |
| --- | --- |
| Python/API/PG log | `d49225806788231f0cf7c9b4742d14fd6caa0e5780c33081c58ebc53afae0bc1` |
| Проверенный src/tests/migrations manifest | `0eda2c23ec7eb82226e84bfc5e03982b1124ef05492eec2b349dba01c481182f` |
| Node/production build log | `c80b3d9e4268b6e8dc3a36e96b8dad0f089d44ffdcac848d733d9047586aa59c` |
| Installed API live proof | `e9f7b5707287b72a3b34c070c3f31ac9b4045e4879d9a3ff28a85635ae7d2f3a` |
| Installed Next Actions/SSR proof | `d6a0c0ef177297624b8e0c25f4594e86a5a0fe1ae928274b3b01e1831275379b` |
| Operations proof | `7dc599baba9158e81867a10b673bb6f7bfd9c0de15a97cd7d0537865ea71fd85` |
| Tenant/helper census | `c34196c76c14a50ea0f878fbc670078f9db8adfb0de9c9b6f3af342ce9a6cf3e` |

API image `sha256:8c2b8f3df74e109030b1dfc9aef5632568f610e0e7012be5900ce82c82b819a5`.
Worker image `sha256:bd9beaba022ebb39ecd474db658e250489881a6e51b87f4789c7c3e35f7abb91`.
Web image `sha256:20176ea33bdac7f2e4d05eff2bd746f07ade7615ad4ee0dc59d8943fa0817535`.

### Как проверить

В `/tender-discovery`: выбранная позиция ЕИС → сохранённый поиск поставщиков →
выбранный сайт → поиск в каталоге → выбранный товар → «Сопоставить условия и характеристики».
Если PRODUCT уже сохранён, новый отчёт разбирает его HTML без скачивания.
«Открыть сохранённое сопоставление» восстанавливает тот же отчёт без HTML/parser/HTTP.
Сейчас source adapter подтверждён для основной карточки «Бумага-С»; это не
универсальный разбор любых сайтов и не полный автоматический допуск по ТЗ.

Далее — проверенные требования из ТЗ, семантика единицы цены и упаковки, данные
поставщика о партии/НДС/доставке. После этого используется существующий
детерминированный compliance engine: mandatory FAIL блокирует, missing UNKNOWN.
PARTICIPATE требует действительного полного КП и трёх сценариев экономики.
