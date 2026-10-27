# V56: проверка сохранённого корпуса ZP и восстановление позиций

Владелец root. ACCEPTED_BOUNDED_INSTALLED; independent installed review PASS.
Зависимость — принятие [V55](143-eis-223-joint-positions.md).
Evidence: `tmp/eis-joint-position-backfill-20261027-v56/`.

## Зафиксированный корпус

135 последних извещений из145 сохранённых версий,34 исходных ZIP,10876365 байт.
InventorySHA `91e5df3afe4964d892dfb21b98f33ce3c456475d12141ee9e2e78f79e887674e`.
Источник не запрашивался: EIS requests0. Чтение tenant-scoped/SQL5s, сначала metadata,
затем две страницы до100refs/2MiB,512KiB/record; архив16MiB/64MiB суммарно.
Первая попытка правильно отказала при135>100 и2.55MiB>2MiB; scope явно изменён
на две ограниченные страницы. Продуктовый read budget не изменён.

Все135 выбранных XML/SHA проверены offline:133 обычных с native/canonical parity;
две совместные по2позиции с customer scopes, canonical0. UNKNOWN0 именно в этом
зафиксированном корпусе. Это не полнота ЕИС или ТЗ и не доказательство доставки
в регион запроса. Независимый review — `corpus-review.json`.

## Следующее действие после V55

V55 восстановил32616471357v2. Для32616500904v2 потребовался exact source0
backfill, XML `bb37cc04048f25c8324d6d45375bd4b6d8659e615ea1327a0ed4f4b06deceec0`.
Тот же ZIP региона запроса11 содержит отдельное извещение о канцтоварах:
заказчики ОООКомитеплоэнерго и ПАОТПлюс; исходные количества22937 и2675,
«Условная единица». Их не складывать и не использовать как per-unit denominator.
Canonical JSON/search_keys/source-window/версии остаются неизменными.

Повторно использованы принятый projector/owned producer cleanup/four leases;
точный план, audit, один новый projection, идемпотентный replay, source0.
Миграций/образов/cron/КП не меняли. Запись выполнена по плану ниже.

## Реальная приёмка пяти независимых источников

SelectionSHA `17b6c761815f4ea5b286a78a997eec6efe017cb607b1990171ef16ab01ae1c45`.
Фиксированы разные purchase/ZIP/request-регионы:32616500904(11),32616318342(41),
32616389160(77),32616403822(49),32616417290(15). Все native5 проверены offline;
installed mainHTTP и actual UI5 PASS по результатам ниже. Выбор не основан на цене/допуске.
Национальное покрытие, свежесть, полнота ТЗ и PARTICIPATE остаются UNKNOWN.

## Установленный результат

Plan86cccada0ecb7b3f160bcf91df31415e66b03781447ce60c3d6777cdda7e4bcd;
executor cacd884c7a06a3f3f128601b3da6cc88f6283fe27d28ca25c5c75560b3e8c5d3.
Одна дополнительная immutable projection, canonical0/source0/image0/schema0/cron0.
Backfill[True,False], replay без новых строк/audit; старые источники неизменны.
ExactV45path/SHA проверяется до runpy;4negative executable-marker tests PASS.
4releaseaudits и producer absence подтверждены; parent runtime invariants PASS.

Пять mainHTTP/native/RLS и actualUI PASS. Новый joint22937/2675 по заказчикам;
обычные1/1/1«Условная единица»,4846«Штука» — exactnative quantities/units.
Для всех5 на сайте сверены XML/ZIP/responseSHA, member/window. Разные request
regions не являются подтверждёнными местами доставки. Evidence actual-ui-result.json,
actual-ui-joint-after.png, five-search-result.json, installed-runtime-readback.json.
Installed-review.json PASS_BOUNDED_INSTALLED_SOURCE0_JOINT_AND_FIVE_UI.
135XML — offline proof; HTTP/UI здесь только5. Полный route corpus принят отдельно [V57](145-eis-zp-corpus-search.md).
