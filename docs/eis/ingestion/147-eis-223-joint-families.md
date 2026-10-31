# V59: позиции совместных закупок в general/KESMBO/AESMBO

Владелец root; V59 установлен, независимая установленная приёмка PASS_BOUNDED.
Production V55 совместим с ZP;
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
60 отрицательных подмен PASS (`final-image-native.json`). На этом этапе новый SHA
ещё требовал review, плана и установки. Национальный охват,
полнота ТЗ и PARTICIPATE остаются UNKNOWN.

## Изолированная проверка финального образа

На финальном API `a6cb4f22` и disposable PostgreSQL миграция до27_03,
source0 backfill6/106, native fact parity, mainHTTP6, чужой tenant и replay
PASS; canonical rows не изменены. Evidence `pg-proof-result.json` и входной
manifest `pg-proof/manifest.json`; временный контейнер удалён. Production и
источник не затрагивались. Первые два прогона тестового адаптера остановились
на сравнении raw snapshot с API после добавления defaults в модель. Причина:
`lots`, `attachments`, `manifest_references`; диагностический вывод сохранён.
После двух циклов сравнение переведено на явную типизированную нормализацию;
неизменность raw snapshot отдельно проверена до/после, все факты сверены с XML.
Это ограниченная изолированная проверка, не installed acceptance и не review.
Read-only baseline 27Oct13:24 МСК: schema27_02, прежние API/WEB; все шесть
ref существуют, latest совпадает, проекций0. `activation-baseline-readonly.json`;
идентичность/очередь повторно сверялись под lease. `rollout-draft.json` фиксирует
images, шесть источников, порядок и барьеры; это не исполняемый exact plan.
Далее были независимое ревью исправленного пакета и изолированной проверки,
затем подготовка и ревью исполняемого плана установки.

## Подготовка исполнителя

Повторный read-only preflight: шесть latest refs, сохранённые ZIP/SHA и отсутствие
проекций подтверждены (`source-before-v59.json`); всё повторяется под lease.
`executor-draft/` содержит адаптер переключения, source0 backfill, readback и
генератор exact plan. 50 тестов исполнителя и 19 изолированных синтетических
тестов plan maker PASS; синтетические отзывы только внутри временных каталогов.
Генератор проверяет SHA итогового manifest и совпадение native evidence,
отзыва, тестов, исполнителя, backfill и readback template. Изолированная база и
финальный image: backfill6, SHA проекций, replay, mainHTTP/native106 и tenant
изоляция PASS (`isolated-proof-summary.json`, manifest `675d83a3…`). Первый
прогон адаптера остановлен до записи: тест использовал app role без доступа к
версии схемы; после перехода к штатной worker role результат PASS.
На момент первоначальной подготовки code/proof и executor review не были проведены,
exact plan не запечатан, production не менялся. Review brief
с SHA и открытыми вопросами — `executor-draft/review-brief.json`.

27Oct после V61 независимое review подтвердило исходный code/gate/proof, но
нашло запуск недоверенного executor и verifier до проверки SHA в plan maker.
Исправлены pre-execution guards; два regression до исправления FAIL, после —
все71 executor/plan tests PASS и повторное review PASS. У `32616407474` latest
сменился v4→v5: старый план неприменим. Сохранённый v5 ZIP/XML повторно сверены,
final image native6/106 и60 tamper negatives PASS; два isolated PostgreSQL/API
proof с v5 PASS, source0. Старые evidence сохранены отдельно. Затем потребовались
review новых proof, свежий baseline с установленным V61 и exact-plan review.

28Oct01МСК: обновлённые proof и exact plan `1588ca8f…` прошли независимое
review, актуальная резервная копия27Oct и preflight под lease подтверждены.
Установлены schema27_03/APIa6cb4f22/WEB5c4b9e9d; шесть source0 projections,
mainHTTP6 и реальный UI6:106 позиций,53 группы заказчиков, XML SHA и version
сверены, включая `32616407474v5`. V61 host script сохранён, cron неизменён.
UI evidence — `tmp/eis-joint-families-20261027-v59/actual-ui-six-v5.json`;
это сводка просмотренных карточек, не полная пополевая сверка интерфейса.
Независимая установленная приёмка PASS_BOUNDED: повторная сверка API, проекций,
аудита и сохранения V61. UI проверен владельцем, reviewer сверил его сводку, но
самостоятельно UI не наблюдал. National coverage остаётся UNKNOWN.

## Контракт

30 октября: для true joint flag разрешается сочетание общей и заказчиковых
ветвей только при уникальном взаимно однозначном совпадении GUID и XML-деревьев
позиций, кроме порядкового номера. Покрытие остаётся UNKNOWN с причиной
`JOINT_MIRRORED_DIRECT_ITEMS`; интерфейс не повторяет зеркальные позиции лота.
Другие неоднозначные формы по-прежнему блокируются. Сохранённый XML из штатного
повтора и изолированный PostgreSQL подтвердили этот частный случай, provenance,
tenant audit и идемпотентный replay; общая полнота ЕИС не установлена.

Шесть сохранённых latest извещений из V58:32616316174v5 KES(32items),
32616327569v4 general(2),32616374237v2 general(7),32616399522v6 general(40),
32616403675v3 AES(19),32616407474v5 general(6). Итого106items/53customer scopes/8lots.
Native namespaces подтверждены независимым contract review PASS_WITH_BOUNDARIES.
V55 обрабатывал joint только в ZP, поэтому эти позиции до V59 отсутствовали.

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
Final image native106 parity, exactplan review, четыре lease, миграция/совместимые
pins,6source0 projections и mainHTTP6/actualUI6 выполнены. Независимая installed
приёмка PASS_BOUNDED. Partial результат не становится national PASS.

Пока national coverage/freshness, полнота ТЗ и PARTICIPATE UNKNOWN.
