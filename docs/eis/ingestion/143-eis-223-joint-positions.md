# V55: позиции совместных закупок 223-ФЗ

Владелец root; ACCEPTED_BOUNDED_INSTALLED, independent installed review PASS.
Evidence: `tmp/eis-joint-lot-positions-20261027-v55/`.
Родитель V54 установлен, обычный joint-case FAIL; [ADR123](../../adr/0123-eis-223-joint-position-projection.md).

## Проверяемый результат

Закупка32616471357v2: XMLb9a65598 содержит два customer scopes по одной позиции.
Показать в основном поиске количества6290.8 и1140 с исходной единицей и точными
QName/provenance. Контроль32616506760: одна обычная позиция без изменений.
Whole-lot2184103.86 остаётся исходной суммой; распределения по позициям нет.

## Контракт и границы

Новая immutable tenant projection223 с FK на exact canonical XML, RLS/audit,
append-only и запрещённым downgrade при данных. Canonical snapshot, search_keys,
source-window/ZIP/member/version и replay не меняются. Источник — уже сохранённый
проверенный ZIP; EIS requests0, cron/quotas0. Автовывод только для новых canonical
строк; старый exact ref получает отдельный идемпотентный backfill.

Лот/заказчик/позиция — отдельные ordered scopes, даже при одинаковых именах/ИНН.
Неизвестные факты UNKNOWN; суммы/количества разных покупателей не складываются.
Обязательны точные QName, уникальность scalar fields и native-item bijection.
Проекция не попадает в КП, per-unit economics, аналоги или PARTICIPATE.
Номер/title recall прежний; item-keyword recall не входит в этот срез.

GET читает только сохранённый JSON финальной страницы, 2 bounded SQL,
512KiB/record и2MiB/page до hydration и после сериализации; ZIP в GET не читается.
UI показывает заказчика, количества, единицы, sourceSHA и locator; усечение явно.

## Приёмка

Parser negatives/real raw facts, PG tenant/FK/digest/immutable/replay/read budgets,
UI render/UNKNOWN/source, полный свежий gate, review, exact rollout plan,
установленные mainHTTP и actual UI для joint2/control1. Принято bounded по результатам ниже.

## Проверки перед установкой

Gate4 остановлен на React immutability после успешных серверных/PG стадий.
Исправлен render: чистый derived view, лимиты100items/100groups; повторный render
и101пустая группа проверяются в прежнем test ID. Lint PASS; независимый review
`code-review-render-addendum.json` PASS_PENDING_FRESH_GATE. Предыдущие FAIL
сохранены, выборочного переноса результатов нет. Полный56-stage gate5 PASS56/56
на source `ba622978f24301b5e06c2994790822b910256a5dab247029be73a78ade808d53`.
4497unit/27allowedskips,831PG/18freshgroups,228WEB,9doctest; trusted receipt
и cleanup9/9 PASS. APIad34eecf/WEBca9d7336. Final-wheel/nativePG/mainHTTP
для joint2/control1 PASS, source0/prod0/replay/RLS; isolated native cleanup PASS.
На том этапе production оставался V54; установка приведена ниже.

Exactplan v1 до apply отклонён: TestClient warning смешивался с JSON.
Новый ops-only import filter ограничен exactmessage/module и import context;
5exactimage framing случаев PASS, прочие warnings остаются видимыми. Source/образы
и gate неизменны. Unappliedv1/FAIL сохранены; plan730c6cc3 принят и применён ниже.

Plan730c6cc3 установлен27Oct~01:54UTC: schema27_02/APIad34/WEBca9d.
MainHTTP joint2/control1, source0/replay/RLS PASS; actualUI6290.8/1140 по двум
заказчикам и control5760«Человек в час» PASS, exactXMLSHA видимы.
Read-only installed-observation-20261027T015726Z.json:5releaseaudits, DB/config/cron/
old5checks неизменны, newFK/RLS/grants/trigger PASS, ownedproducers absent.
Observer missingnow исправлен только в readonlyprobe; ошибки сохранены.

Независимый installed-review.json PASS_BOUNDED_INSTALLED_JOINT_POSITIONS.
Приёмка ограничена joint2/control1 и автоматическим сохранением проекций новых
ZP версий. [V56](144-eis-223-joint-backfill.md) — отдельный план старого второго
извещения и пяти карточек. Национальная полнота/полнота ТЗ/PARTICIPATE UNKNOWN.
