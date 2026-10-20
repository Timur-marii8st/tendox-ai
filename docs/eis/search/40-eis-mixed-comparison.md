# Общее сравнение выбранных закупок 44-ФЗ и 223-ФЗ

## Контракт S160

`POST /v1/tender-discovery/eis-mixed-comparison` принимает 2–3 exactref:
`law: "44" | "223"`, `purchase_number`, `version_number`, `notice_xml_sha256`.
Номер проверяется по закону: 19–23 цифры для44,11 для223. Пара law+номер
уникальна; нельзя сравнивать две версии одной закупки как разных кандидатов.
Tenant задаётся авторизацией, дополнительные поля запрещены. Аудитор может
выполнять эту read-only операцию. No-store;404 для недоступной версии,409 для
противоречия evidence,422 для невалидного контракта. Частичного ответа нет.

Все выбранные строки читаются в одной tenant-scoped READ ONLY REPEATABLE READ
транзакции с одним aware checked_at. Порядок выбора сохранён. Скачивания,
создание job, native analysis, audit writes и перечитывание ZIP/XML архивов
не выполняются. Используются только сохранённые typed metadata и native cache.
Статусы обновления исходной ЕИС и полнота охвата остаются UNKNOWN.

Строки — discriminated union по `law`, исходные модели не смешиваются:

-44 сохраняет evidence bridge: НМЦК в RUB, позиции и их locators, deadline,
  текущую известную версию, документы/условия/контекст, procedure events.
  Полная официальная XSD quality пока UNKNOWN. В общем быстром сравнении
  критерии электронного конкурса UNKNOWN: архив здесь не разбирается.
  Существующий отдельный44 evidence endpoint продолжает извлекать критерии.
-223 сохраняет каждый лот отдельно: его цена/валюта/количество/единицы/XML
  provenance, текущую известную версию, manifest/queue/receipts/условия,
  exact official XSD quality. Ошибка source XSD не подменяет supplier gate.

Нет суммирования НМЦК с ценами лотов, курсовой конвертации, единичной цены из
непроверенного деления или вывода о сопоставимости предметов. Существующие
Decimal значения сериализуются строками. `economic_comparability=UNKNOWN`,
`profit_order_status=UNKNOWN`, `coverage=UNKNOWN`. Допуск, полнота ТЗ и КП
не утверждаются; для рекомендации нужны проверенные требования, полное
действующее КП, налоговая модель и base/realistic/conservative.

Stale/expired и подтверждённая отмена44 сохраняют BLOCKED и источник причины.
При отсутствии подтверждённого препятствия — NEEDS_ANALYSIS, никогда PASS.
Для223 неподтверждённый timezone/стадия/отмены остаются UNKNOWN.

## Интерфейс

Над двумя разделами поиска находится общая корзина. Кнопки «В общее сравнение
44/223» у каждой найденной карточки добавляют exact version, максимум3.
Можно выбрать любую комбинацию законов. Закон явно показан в корзине и
результате. Новая отправка поиска снимает выбор только для своего закона;
вторая часть корзины сохраняется. Изменение выбора скрывает старое сравнение.
Generation guard отбрасывает поздний ответ для уже изменённой корзины.

Сравнение в2или3 колонках показывает цены/позиции/готовность документов.
XML locators раскрываются отдельно; условия документов показывают SHA/locator
и явное сокращение preview. Максимум18 фрагментов на документ; native44
сводка ограничивает каждую группу условий, native223 — первые18/600символов.
Полный извлечённый текст сохраняется на сервере. Роли документов не утверждены.
Сравнения внутри одного закона остаются доступны.

## Проверка

S160 завершён; подробное deployment evidence находится в
[плане реализации](../../15-implementation-plan.md). Интеграционные тесты используют
только синтетические44/223 источники и явно изолированную PostgreSQL БД.
Проверяются валюты/лоты, один read-only snapshot, cached document evidence,
stale/expired/cancellation, tenant/digest conflicts, запрет ложного profit rank,
сохранность существующего отдельного44 competition-criteria endpoint.

183 local/55 isolatedPG/117 Linux tests, Ruff/mypy/web build/ESLint прошли.
Развёрнуто на VPS, HEAD20261002_10, изолированная testDB удалена.
Реальный mixedPOST:0.268618s,repeat0.048526s,no-store, counts/audit/jobs/analyses
не изменились. Proof только на VPS:
`s160-mixed-proof-20261002T194357460903Z.json`,
SHA `71902c2e9f6d80587b58b186705bd4c9a499e39a770e861ccc57132e2581f37e`.

CUA подтвердил basket limit3, сохранение другого закона/reset своего при
новом поиске, side-by-side real equipment44/223. Скриншот emitted; итоговый
таб сохранён. НМЦК bundle44 и цена лота223 не объявлены сопоставимыми, никакого
PARTICIPATE/экономического рейтинга/полного охвата ЕИС не выдано.

## S162: позиции и характеристики

В том же tenant READ ONLY REPEATABLE READ snapshot добавлен position_set.
44 bridge и223 comparison также получают это additive поле. Каждая позиция
содержит отдельно имя, количество, исходную единицу, коды, цену единицы/сумму/
валюту и provenance каждого значения. В223 сохраняются lot_index/исходный
ordinal; сумма всего лота не превращается в цену позиции. В44 валютаRUB
показывается только при подтверждённой parser НМЦКRUB; иначе UNKNOWN.

Характеристики44 сохраняют source names, filling instruction code, quality
description, min/max с исходными math notation и единицей. Правило соответствия
из них автоматически не активируется.223 characteristics UNKNOWN: текущий
metadata reader не извлекал эти поля, отсутствие не считается отсутствием ТЗ.
Максимум25positions/24characteristics/8values; totals/truncation видны.

Из cached native analysis полученных DOCX показаны реальные строки/ячейки
таблиц, максимум12rows/8cells/400characters per cell. Полные blocks сохранены
на VPS. Имя файла не утверждает роль; строки не назначаются позиции, association
UNKNOWN. Native extraction UNKNOWN остаётся UNKNOWN при external links/media.
ZIP-member tables требуют отдельной parent/member цепочки и здесь не прикрепляются
к SHA родителя. Рисунки/сканы/XLS/formulas не интерпретируются этим превью.
Никакого нового разбора исходных bytes/HTTP/job/analysis/audit write.

position_links — максимум24 предложения связи между карточками по равенству
нормализованного имени,КТРУ или кода классификации. Порядок соответствует выбору
пользователя, не прибыли. Отдельно видны различия исходных количеств/единиц,
наборов и значений одноимённых характеристик, missing/truncated evidence.
Код классификации не доказывает одинаковый товар; равенство label/value также
не доказывает полную эквивалентность. Equivalence/price_comparability всегда
UNKNOWN. Никакой FX/сложения лотов, supplier PASS или profit rank.

## S163: конкретные числовые значения и исправление старого разбора

XML44 `valueSet/concreteValue` читается отдельно от min/max: сохраняются все
известные значения, порядок, исходная строка и locator каждого элемента.
Signed finite Decimal применяется к физическим характеристикам (например,
температура−40); денежные факты и количества сохраняют прежний nonnegative
контракт. Zero является значением. Invalid/empty/nonfinite/чрезмерно длинные
числа остаются UNKNOWN; исходный concrete text виден (preview≤400characters).
До8 concrete values на вариант, total и truncation показаны. Для смешанных
reference/text характеристик locator использует порядковый номер своего тега.

Существующие notice_versions неизменяемы. Новый bounded cache
`eis_notice_position_projections` хранит производную позиции по tenant,
purchase/version/XML SHA и parser_version `eis-position-v2-concrete`.
Это отдельная immutable RLS таблица, FK к исходной версии, DB trigger проверяет
точный XML digest; JSON identity/UNKNOWN и projection SHA проверяются при чтении.
Selected server job читает ровно один сохранённый archive/member (≤50MiB/32MiB),
проверяет оба SHA и идентичность, безопасный XML reader запрещает DTD/entities.
Сетевых запросов нет. Повтор не разбирает bytes, не пишет новую projection/audit.
Успешное новое извлечение записывает tenant audit EIS_POSITION_PROJECTED.

В comparison сохраняется общий read-only snapshot. Cached position_set
заменяет старый metadata preview, native tables берутся из прежних exact receipts;
необработанные legacy версии пока показывают UNKNOWN. Новые импорты получают
concrete values непосредственно из обновлённого source reader. Автоматическое
переизвлечение всей истории не входит в этот bounded selected slice. Его наличие
не подтверждает полноту ТЗ, эквивалентность товара или право участия.

Server operator CLI: `scripts/server-eis-position-project.py --company-id ...
--purchase-number ... --version-number ... --notice-xml-sha256 ...`.
Исходные данные и projection остаются на VPS. Parser version/facts имеют
technical provenance; они не являются новым юридическим правилом.

## S164: предварительная экономика выбранной версии и лота

Операторский `POST /v1/tender-discovery/eis-source-estimate` принимает точный
`notice` (law, purchase_number, version_number, notice_xml_sha256) и `costs`.
Для 223-ФЗ обязателен явный `lot_index` (индекс с единицы в сохранённом XML,
исходный ordinal возвращается отдельно); для 44-ФЗ этот параметр запрещён.
Цена берётся только из сохранённой рублёвой НМЦК44 или initial_sum_rub одного
выбранного лота223. Суммирования лотов, деления на количество и FX нет.
Нерублёвая или противоречивая валюта оставляет рублёвый предел UNKNOWN.

Товар и прочие затраты задаются на весь объём без НДС; expenses включает
логистику, финансирование, гарантии и все известные налоги кроме выходного
НДС. Ставка выходного НДС и основание вводятся оператором, ставки не угадываются.
Все суммы/доли используют существующий Decimal engine. Три сценария:
base без снижения; realistic с заданным снижением; conservative с заданными
снижением и ростом затрат. Сценарные предположения явно показаны и редактируемы.
Известные stale/deadline/procedure blockers и отмена выбранного лота запрещают
расчёт. Нет рублёвого предела или strict costs_complete_ack — UNKNOWN.

Результат содержит опубликованный ceiling с XML SHA/locator, ручной ввод,
tenant/actor-bound input digest и manual provenance, timezone-aware checked_at.
Расчёт эфемерный: одна consistent read tenant transaction, cached evidence,
никаких сетевых запросов, повторного разбора XML/файлов, jobs или audit writes.
Он не заменяет подтверждённое полное КП: quote/requirements/full_cost_review/
eligibility/profit_order_status всегда UNKNOWN; PARTICIPATE невозможен.

В смешанной корзине у каждой карточки есть форма «Предварительная экономика».
Затраты, ставка и основание пусты, ack не отмечен; лот223 выбирается явно даже
при единственном лоте. При редактировании ввода результат сбрасывается;
смена выбора или обновление сравнения пересоздаёт форму, stale responses
не применяются. Вывод денег не использует JavaScript float для пересчёта.
Синтетические затраты live proof служат проверкой расчёта, не доказательством
действительной прибыли поставщика. Полный охват ЕИС этим этапом не подтверждён.
