# ADR-0112 — ограниченные большие извещения223-ФЗ

Дата решения: 2026-10-22. Статус: INSTALLED22Oct21:41МСК; bounded3window production PASS.
Effective date: 2026-10-22T18:41:19Z, exact payload8764ff9d, operation52bd5e1d.

## Контекст

R3 воспроизводит три source-failed окна223 в полном официальном наборе:
77/19Oct/purchaseNoticeAESMBO:117XML, максимальный XML4511001B;
77/20Oct/purchaseNotice:459XML, compressed33840461B;
78/19Oct/purchaseNotice:76XML, максимальный XML9471478B и5874lotItems.
Прежние4MiB/XML,32MiB/window и5000positions не принимают эти наборы.
Это измерения официальных incoming getDocsIP/RI223 и verified prepared URLs,
не предположение о допустимости произвольного входа. Исходные ответы/ZIP
сохранены tenant-scoped на VPS; токен и outgoing SOAP не сохранялись.
Evidence: tmp/eis-223-archive-recovery-20261022-v27/capture-summary.json и
collection-diagnostic.json. Source response SHA соответственно53d88c06,
73aa2d6a,41edf284; полный capture на VPS:
/var/lib/eis-browser/research/223/local-eis-supplier/r3-20261022-v27-capture2.

## Решение

Только для notice223: XML12MiB, aggregate compressed40MiB, позиции6000.
В eis_223_archive новый MAX_NOTICE_XML_BYTES отделён от прежнего shared
MAX_XML_BYTES4MiB, который сохраняется для событий и отмен лотов. Preflight
window и notice reader используют один notice XML cap; парсер сохраняет все
позиции и их provenance. Превышение6000 не обрезается и остаётся отказом.
Остальные пределы прежние:8ZIP/800members/window,128MiB expanded/window,
16MiB compressed/32MiB expanded/200members perZIP,100lots/200attachments.
Whole-set/UID/request/officialURL binding, DTD/entity/token-reflection guards,
immutable conflicts, tenant isolation, full checkpoint и atomic intake сохраняются.
Схема и DB CHECK не меняются; worker3GiB/3CPU, source quota/pacing, joint budget,
180s atomic window и cron сохраняются. Нужны synthetic boundary regressions,
real retained full ingest/replay/tenant+memory proof и полный release gate.

## Последствия и альтернативы

Увеличиваются bounded стоимость XML parse и размер snapshot. Перед установкой
измеряется весь pipeline трёх наборов в прежнем cgroup3GiB; только проверенные
ресурсы допускают exact worker deployment. Ошибка или неполный набор не PASS.
API read compatibility и non-owned module parity проверяются для сохранённого API.
Отказ от чтения >4MiB сохраняет известные пропуски. Обрезать5874 до5000 нельзя:
это потеря требований и ложная полнота. Снятие всех limits и частичный импорт
не используются. Национальная полнота и PARTICIPATE не следуют из этого изменения.
Откат worker оставляет immutable историю; старый reader может вновь отвергать
крупные source sets. Историю не удалять; потребители используют saved snapshots.
