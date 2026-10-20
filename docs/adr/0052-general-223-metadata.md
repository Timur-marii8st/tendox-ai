# ADR-0052 — явный metadata contract purchaseNotice

Статус: принято, DEPLOYED (S169, 2026-10-03).
Дата/effective date: 2026-10-03. Владелец решения: Astra; rollout — root.

## Контекст

ADR-0050/0051 разрешают immutable metadata projection и независимую полную
XSD quality для AESMBO/ZKESMBO. Они намеренно не разрешали общее семейство.
[Исследование S169](../eis/ingestion/47-eis-223-general-notice-contract.md) установило
отдельный официальный `RI223/purchaseNotice`, NSI item62, namespaces и
qualified paths. Evidence основан на сохранённых официальных NSI/XSD16.2/16.3
и архиве S152; exact hashes приведены в исследовании. Этот ADR не утверждает,
что сегодня источник был повторно запрошен.

Сохранённый sample содержит 25 XML-версий: 24 XSD PASS и одну XSD FAIL в каждой
из двух releases. Ошибка дополнительного placingProcedure не равна отсутствию
безопасной business identity/price projection. Отбросить один member и назвать
остальной архив полным нельзя. Старое наблюдение S152 SOURCE_REJECTED неизменно.

## Решение

Разрешить **только явное семейство purchaseNotice** для bounded typed metadata
reader; это расширение списка ADR-0051, не универсальное разрешение generic XML.
Метаданные допускаются независимо от полного XSD PASS при выполнении следующих
условий:

1. Каждый XML каждого returned archive полностью проходит безопасный metadata
   reader: exact root/Data family и namespace, единственная business identity,
   номер из 11 цифр, положительная версия, exact SHA/locator, лимиты ZIP/XML и
   запрет unsafe XML. Нельзя брать номер из имени файла/GUID или молча пропустить
   member. Identity/namespace/unsafe/version conflict отклоняют весь window.
2. Сохраняются immutable исходные bytes и все metadata records полного
   prepared/returned archive set. Tenant isolation, composite FK, replay и
   атомарность остаются прежними. Source SYNCED означает завершённый transport
   и metadata ingestion этого набора; не XSD PASS, полноту ЕИС или допуск.
3. Full-XSD выполняется отдельно по pinned complete official schema trees,
   offline, без external schemaLocation. FAIL/UNKNOWN отображаются на точном
   XML и не исправляются в исходнике. Новая версия не наследует старую quality.
   Наличие известной XSD FAIL не требует ложного partial metadata import:
   полнота returned set и качество содержимого — отдельные поля/состояния.
4. Ретроспективный offline parser proof не меняет S152 SOURCE_REJECTED.
   Production source window возникает из нового разрешённого запроса после
   reader/model/SQL/consumer deployment; old probe evidence не переписывается.

### Цена и идентичность лота

Сохранять GUID лота, source ordinal и позицию массива отдельно; optional lotData
даёт UNKNOWN fields, не искусственный лот/нулевую цену. Лоты не объединяются.
Рублёвый итог всех лотов и деление цены лота на количество здесь не вычисляются.

Цена получает явный source kind:
`INITIAL_SUM | MAX_CONTRACT_PRICE | TEXT_ONLY | UNKNOWN` и exact fact/locator.
`maxContractPrice` не записывается как initialSum; formula/initialSumInfo и
commodityPrice не подменяют цену всего лота. Отдельный source RUB equivalent
не является рассчитанным FX. Деньги finite nonnegative Decimal, conflict
currency codes сохраняет UNKNOWN.

Для первого rollout существующий `initial_sum_rub` разрешён только при
настоящем initialSum и согласованной RUB валюте. Для max/formula/unknown — None;
existing economics unavailable/UNKNOWN. Эти лоты остаются discoverable и
показывают известный исходный amount/kind. Отсутствующая сумма не равна нулю.
Старые persisted snapshots читаются совместимо без UPDATE history; новые поля
не должны создавать вымышленные факты для прежних bytes.

### Сроки, статус и документы

Naive/missing deadline остаётся UNKNOWN; customer offset не исправляет его.
Aware общий deadline сохраняется как факт извещения. `isLotOriented=true`
не позволяет объявить общий срок подтверждённым сроком конкретного лота;
lot schedule review UNKNOWN. P не означает SUBMISSION_OPEN; I означает source
invalid, а не автоматически legal cancellation. True hidden/notPlacement
не даёт разрешения public discovery/download; consumers обязаны исключать
непубличное действие и показывать источник ограничения. Отсутствующие флаги
не превращаются в положительный допуск. Отмена лота остаётся отдельным blocker.

Manifest сохраняет явные признаки и provenance для documentFS, prevDocument,
additionalDocumentsCount и notPlacement. При unresolved ветке status UNKNOWN,
даже если число обычных document совпало с totalDocumentsCount. FS/GUID не
превращаются в синтезированный download URL, prevDocument не считается уже
полученным. Скачивание скрытых references запрещено. Limits и official HTTPS
UID allowlist прежние. COUNT_CONSISTENT не доказывает полноту требований.

### Quality и предварительные расчёты

Проверен текущий код: `read_comparison223_row` добавляет reason при schema FAIL,
но blocking_reasons получает из document status. `_blocked` проверяет stale
version/deadline, а `get_source_estimate` принимает эти blockers. Следовательно,
**XSD FAIL сейчас не блокирует предварительный estimate автоматически**.

Сохранить это разграничение: source schema FAIL не supplier hard FAIL. Для
поддержанного initialSum допустим только явно предварительный ручной расчёт с
видимыми source quality/status и UNKNOWN requirements/quote/eligibility.
Consumer rollout должен донести quality warning до результата/формы расчёта;
не представлять скрытую XSD FAIL как проверенную экономику. Unsupported price
kind не использует этот calculation path. PARTICIPATE/ranking по прибыли
по-прежнему требуют reviewed requirements, полного действительного КП и трёх
сценариев; source quality uncertainty не исчезает из domain review.

## Последствия

Расширяется наблюдаемый публичный спрос без скрытия проблем XML. Реализация
обязана обновить family whitelist/SQL guards/quality consumers последовательно
до live admission. Никакого автоматического расширения регионов, cron scope,
source budgets или новых семейств. Новый event store для rejection/cancellation
остаётся отдельным срезом.

## Альтернативы

- Требовать full-XSD PASS для всех metadata: теряет безопасно наблюдаемые факты
  и отличается от уже принятого ADR-0051.
- Отбросить failing member: нарушает полноту и атомарность returned set.
- Исправить XML или ослабить XSD: нарушает provenance.
- Положить maxContractPrice в initialSum: меняет экономический смысл и locator.

## Проверка решения

Acceptance и ownership milestones — [S169 implementation](../eis/ingestion/48-eis-general-223-implementation.md).
Production admission подтверждён evidence root: новое окно region50/2026-10-02,
один ZIP/40 XML versions атомарно сохранены, full-XSD отдельно 38 PASS/2 FAIL
в каждой release. Проверки, replay и fingerprints — в итоговом разделе
[S169 implementation](../eis/ingestion/48-eis-general-223-implementation.md).
Это не подтверждает полноту рынка или XSD PASS всех исходников.
