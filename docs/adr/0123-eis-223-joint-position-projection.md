# ADR123: отдельная проекция позиций совместной закупки223

Дата2026-10-27. Решение принято для реализации; production PENDING.

Сохранённый XML ZP содержит header lotData и jointLotData с двумя покупателями.
Canonical parser исторически сохранил0позиций. Переписывание snapshot или новая
фиктивная версия нарушают immutable source/replay. Таблица44 имеет другой law/FK.

Создаётся отдельная tenant/version/parser projection223, exact XML FK, immutable
trigger/RLS/audit. Вывод только при intake новой canonical строки или явном
source0 backfill старой; GET гидратирует bounded JSON без ZIP. Canonical parser и
search_keys не меняются. Header+joint разрешены; direct items+joint items конфликт.

Customer scopes никогда не объединяются по меткам. Количество и единица остаются
в позиции своего заказчика. Whole-lot сумма и прежние quote inputs неизменны;
включение проекции в экономику требует отдельного доменного контракта.

Следствие: отображение исправляется для номер/title matches, item recall прежний.
Подробности и приёмка — [V55](../eis/ingestion/143-eis-223-joint-positions.md).


## Расширение V59, 27 октября 2026

Независимая native сверка обнаружила ту же jointLotData/customer topology в
purchaseNotice, purchaseNoticeKESMBO, purchaseNoticeAESMBO:106items/6refs.
Whitelist расширяется ровно на эти три типа, с exact document_type в projection
и provenance. Прежний ZP JSON/digest/parser_versionv1 сохраняется.
Migration27_03 расширяет identity CHECK; downgrade запрещён при non-ZP данных
любого tenant. Совместимые API/worker/collector/WEB pins устанавливаются до
записи новых типов; откат старого Literal[ZP] consumer после записи запрещён,
при смешанной конфигурации старый consumer изолируется. Отсутствующие qty/unit/
additionalInfo остаются UNKNOWN даже при наличии commodityItemPrice/lot header.
Canonical/searchkeys/quote и остальные границы ADR прежние.
Подробности — [V59](../eis/ingestion/147-eis-223-joint-families.md).
