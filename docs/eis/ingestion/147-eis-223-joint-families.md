# V59: позиции совместных закупок в general/KESMBO/AESMBO

Владелец root; GATE_PASS_REVIEW_PENDING. Production V55 совместим с ZP;
V58 восстанавливает только44. Evidence `tmp/eis-joint-families-20261027-v59/`.
Родитель кода — exact accepted V55 source ba622978; root dirty snapshot не пакуется.
Owned files и acceptance зафиксированы в slice.json до правок.

## Исправление после release gate

Прогон `gate-state2/release-20261027-055549-77cf98b67668` завершился FAIL
на пяти PostgreSQL-тестах; cleanup complete. Приём и поиск сохраняли фильтр
только ZP, поэтому три новых семейства не получали projection. Добавлен файл
`src/procurement/storage/eis_223_index.py` в owned scope: обе точки используют
существующий типизированный whitelist. Старое code review относится только к
прежнему SHA и не подтверждает исправленный пакет. Новый пакет SHA-256
`45900cca6c093ade3a1feb7394667010c15100d6af2656339f9daaef5b243212`;
Gate3 завершился FAIL на двух search oracle и двух converter tests; cleanup complete.
Search fixture дополнен проверкой числа ссылок для нового ограниченного чтения.
Gate3 ошибочно запущен от root: `mode=0700` scratch блокировал converter после
снижения привилегий. Штатный запуск — от непривилегированного владельца;
7 адресных тестов PASS локально. Новый пакет SHA-256
`accd7d60a9c01c0161e419c89f6f58bdd23b1043ede313ca69ed5a85978904d6`, полный gate4
в `eis-joint-families-20261027-v59-correction2` штатным пользователем: PASS 56/56,
trusted receipt и cleanup 9/9 проверены. API `a6cb4f22`, WEB `5c4b9e9d`.
Финальный API image, network-none/read-only: 6 native cases, 106 позиций и
60 отрицательных подмен PASS (`final-image-native.json`). Новый SHA требует
независимого code review; exact rollout plan и его независимое review, установка,
mainHTTP/UI6 и установленная приёмка остаются PENDING. Национальный охват,
полнота ТЗ и PARTICIPATE остаются UNKNOWN.

## Контракт

Шесть сохранённых latest извещений из V58:32616316174v5 KES(32items),
32616327569v4 general(2),32616374237v2 general(7),32616399522v6 general(40),
32616403675v3 AES(19),32616407474v4 general(6). Итого106items/53customer scopes/8lots.
Native namespaces подтверждены независимым contract review PASS_WITH_BOUNDARIES.
Installed V55 обрабатывает joint только в ZP, потому все эти позиции пока отсутствуют.

Разрешены ровно четыре подтверждённых типа: прежний ZP плюс general/KES/AES.
Exact document_type передаётся в projection, provenance сохраняет родной тип и путь.
Старый ZP JSON/digest должен оставаться побайтово прежним, parser_versionv1 прежний.
У AES две позиции без qty/okei/additionalInfo, у одного general ещё7 без description;
цена commodityItemPrice и lot header не восполняют эти пропуски. UNKNOWN сохраняется.
Source-item coverage не означает полноту спецификации/фактов.

Новая миграция27_03 расширяет только identity CHECK существующей immutable таблицы;
FK/RLS/grants/trigger/tenant/audit прежние. Проверяется переход от реального старого
ZP-only CHECK. Downgrade запрещён, если non-ZP projection есть в любом tenant;
более ранний guard всех persisted projection histories сохраняется.
После admission non-ZP старый V55 API несовместим с Literal[ZP]: необходима установка
совместимых API/worker/collector/WEB pins до записи и forward-only barrier.
При сбое сохранять принятые совместимые образы, изолировать прежние consumers.

Canonical snapshot/search_keys/version/source-window/ZIP/quote inputs не меняются.
Не объединять customer scopes и не суммировать количество/цены разных заказчиков.
GET только bounded saved JSON; ZIP GET не читает. Participation/economics UNKNOWN.
Source0, cron/квоты0; 54min/hour,180s source turn,TLS/cooldown/SQL5slock2s сохраняются.

## Приёмка

Regression до исправления воспроизводит потерю позиций для трёх семейств.
Unit37 PASS (18 прежних+19 новых); native6/106items и60tamper negatives PASS.
Старые test IDs и27allowedskips сохранены; PG840 в18freshgroups, unit4516,
WEB228 ожидаются в полном56-stage gate. Code review PASS_PENDING_FRESH_GATE
на source87e46dba98f35938cfd0aef4d97de4624dfa5ae8e7f4954dffaa98513790b8f8.
Verifier проверяет все customer/item facts и сохранённые canonical facts;
пропущенные старой схемой manifest_references не становятся доказанной полнотой.
Три head-dependent guard fixtures переведены на27_03; исторические миграционные
before/after проверки, exact-head assertion и прежние IDs не ослаблены.
Нужны unit QName/ambiguity/UNKNOWN/oldZP compatibility, realPG migration/tenant/
CHECK/FK/replay/downgrade и свежий полный release gate с trusted receipt/cleanup.
Final installed-image native106 parity до rollout, затем exactplan review,
четыре lease, миграция/совместимые pins,6source0 projections, mainHTTP6/actualUI6
и независимая installed приёмка. Partial результат не становится PASS.

Пока national coverage/freshness, полнота ТЗ и PARTICIPATE UNKNOWN.
