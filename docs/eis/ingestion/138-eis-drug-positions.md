# V50: исходные лекарственные позиции

Владелец root. Статус: PASS_BOUNDED_INSTALLED_DRUG_POSITIONS.
[ADR119](../../adr/0119-eis-drug-position-projections.md),
[предыдущая проверка полноты](137-eis-completeness-recovery.md).

Проверяемый результат: 26 позиций из шести retained XML видны в основных
карточках; новые admitted drug notices получают bounded derivation.
Canonical lot_items и история неизменны, повторный импорт идемпотентен.
Owned files/acceptance/dependencies: `tmp/eis-drug-completeness-20261026-v50/slice.json`.

Pure parser на реальных XML: 26 позиций, 26 явных единиц, 22 количества UNKNOWN,
4 исходных total: 5625, 15000, 500000, 680. Source requests:0.
Evidence: `tmp/eis-drug-completeness-20261026-v50/real-pure-current.json`.
Final-image isolated PG/API:26позиций/22UNKNOWN/112source facts, replay/RLS/NO_QUOTE PASS.
Полный gate50PASS:4405unit+27allowed skips,771PG/0skip,222web.
План11121f6b установлен26Oct17:20UTC:API/worker024906c3,WEB95e2ad9a, schema26_02.
Live main search6×HTTP200; шестьprojection audits и пятьrelease statuses прочитаны.
Canonical/SHA неизменны, источник0, миграций0. Evidence:activation-result,
installed-readback,live-search-result.json в каталогеV50.
Actual CUA выявил светлый текст на белом фоне; forward fix77254de6 изменил
только className. Второй полный gate50PASS с теми же counts; WEB71e83972
установлен exactplanbac2d11f, API024906c3 не пересоздавался.
Повторный actualUI:6карточек/26позиций/22UNKNOWN; source SHA/QName, единицы,
цены, суммы и officialURL PASS. Два UI globalprice примера(12+1позиция) PASS,
live globalprice6×HTTP200. Скриншоты читаемы, CSS Lab тёмный/белый подтверждён;
числовой WCAGratio не заявляется. Ошибка локального SSHtunnel устранена,
не дошедшие до API запросы не признаны дефектом продукта.
Новая штатная загрузка уже создала40projection audits;5новых refs/SHA/typedfacts
выборочно проверены readonly. Это не40проверенных UI.
Independent installedreview PASS; `acceptance.json` связывает точные proofs.

Используется существующая immutable position projection v4 без миграций и
canonical rewrite. Основной поиск и глобальная сортировка читают сохранённый
разбор выбранной страницы. Проверки: отрицательные synthetic cases, оба writer,
HOLD/replay/tenant/digest, no-GET-I/O, размер ответа, web, release gate, шесть
реальных ZIP в isolated PostgreSQL и actual UI пройдены в указанном scope.

Лекарственная взаимозаменяемость, полнота ТЗ, КП, PARTICIPATE и национальный
охват остаются UNKNOWN. Поиск по новым лекарственным названиям вне title —
отдельный следующий срез. Барьер совместимости V48 обязателен.
