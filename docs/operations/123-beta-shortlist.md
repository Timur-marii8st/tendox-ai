# Подготовка сквозной беты подбора закупок

Дата проверки: 2026-10-23. Владелец: root, один агент.
**Поиск и расчёты готовы к ограниченному закрытому бета-тесту.**
Полный MVP, персональная реальная сделка и национальная полнота ЕИС не приняты.

Текущие API/worker ab3b9686 (R4), WEB949064db (B9), schema20261021_01.
23Oct10:15МСК: health/images/schema/disk PASS; переустановка не требовалась.
Evidence: `tmp/beta-readiness-20261023-v32/acceptance.json`.
Сквозной smoke на текущих образах в изолированной синтетической базе PASS:
профиль → поиск → регион → карточка → КП/17расходов → три сценария → два
финансовых варианта; reload, обрыв связи, expiry, desktop/mobile проверены.
На production выполнены только readonly запросы; реальные данные не подменялись.
Текущая вкладка недоступна из-за browser policy; другой live browser не использован.
Полный release gate не повторяли: код, образы и схема не менялись.

### Как начать закрытый тест

1. Откройте `/company-profile`, подключите существующий персональный доступ
   компании. Общий пароль входа на сайт не заменяет персональный ключ.
   Сохраните товары/услуги, географию и доступные поля профиля, выберите версию.
   Сейчас выбран v1 с проверенным SHA, но все27полей UNKNOWN; реальных КП0.
   Критичные поля ограничены прежним owner contract; разрешения не обходятся.
2. На `/tender-discovery` введите товар/номер, выберите место поставки, нажмите
   «Найти закупки», затем «Сначала дорогие». Этот порядок охватывает все
   совпадения в сохранённой базе; НМЦК не означает прибыль. Регион поставки
   UNKNOWN по умолчанию исключается. Поиск «бумага А4»:1709совпадений/19.592s;
   Амурская область:13совпадений/55.505s. Это близко к web timeout60s;
   скорость при росте корпуса остаётся ограничением беты.
3. Откройте карточку → «КП и расходы» → «Добавить КП и расходы». Введите
   действующее полное КП на выбранный лот, источник, даты с часовым поясом,
   НДС,17расходов и основания. Явный0 — заявление пользователя; пропуск UNKNOWN.
   Нажмите «Сохранить КП и пересчитать». Не вводите вымышленные значения.
4. В «Лучшие по расчётной прибыли» обновите подбор. Он сравнивает до20лотов
   загруженной выдачи и показывает до5вариантов с положительным консервативным
   результатом. Это отдельный режим от сортировки всей базы по НМЦК.
   Для сравнения нескольких вариантов нужны КП/расходы каждого лота.
5. В карточке проверьте исходные документы, ссылку ЕИС и площадку. Для44
   0325200000326000113 подтверждены source href ЕИС/Росэлторг и4вложения;
   для223 32616494439 — РТС и1вложение, ЕИС доступна через явно подписанный
   поиск номера: прямая публичная ссылка в источнике не подтверждена.
   Внешние файлы в этом срезе не скачивали; роль ТЗ/полнота остаются UNKNOWN.

Бета не подтверждает PARTICIPATE и не подаёт заявки. Полнота/устойчивая свежесть
ЕИС UNKNOWN; отсутствие результата не доказывает отсутствие закупки. Реальная
экономика требует ввода профиля, действующих КП и расходов пользователем.
Для обратной связи фиксировать шаг, товар/регион, номер закупки, ожидаемое и
фактическое поведение, время МСК; не прикладывать ключи или необезличенные КП.

Ниже сохранены acceptance, история установки и evidence B8/B9.

Первоначальный план активации: `tmp/beta-shortlist-20261021-v1/activation-plan-beta.json`,
SHA256 `ae868bf6086fc41a579b49649d57bb5df4cd18d9ade871e5d2abc7369635ca40`.
Этот payload уже применён с подтверждением пользователя, повторно не применять.
Коррекция navigation44 отдельно подтверждена и применена22Oct; ниже live evidence.
Действующие реальные КП/расходы и целевые поля реального профиля ещё требуют
ввода/проверки пользователем. Финансовая приёмка реальной сделки, полнота ТЗ и
PARTICIPATE не заявляются; M5 national freshness остаётся INCOMPLETE.

Запрос: предлагать несколько выгодных закупок с учётом профиля и региона;
дать открыть ТЗ и перейти к закупке в ЕИС и на указанную внешнюю площадку.
Контракт: [PRD](../product/11-product-requirements.md),
[экономика](../architecture/04-economics.md),
[профиль и сравнение](../architecture/07-company-profile-contract.md).

## Acceptance всей беты

1. Персональная сессия, tenant и выбранная версия профиля определяются сервером.
   Профиль действительно участвует в подборе; причины исключения/UNKNOWN видимы.
2. Рабочий регион **поставки**, не подмена регионом публикации/заказчика. Факт
   места исполнения имеет provenance. Неизвестный регион не считается совпадением;
   политика включения UNKNOWN явна. Фильтр сохраняется при продолжении поиска.
3. Пользователь получает до пяти кандидатов с объяснением порядка, ограничениями
   охвата и свежести. Несколько карточек сравнимы. НМЦК не является прибылью;
   подтверждённый и предварительный расчёты не смешиваются. Mandatory FAIL блокирует.
4. Основной расчёт и рейтинг используют действующие полные КП и расходы, которые
   вводит пользователь, с явными налогами и тремя сценариями через Decimal.
   Отдельная предварительная оценка использует публичные цены и проверяет
   единицу цены, количество и состав лота.
   Все допущения явны, отсутствующие расходы остаются UNKNOWN, а потенциал до
   расходов не называется прибылью. Действительное полное КП, налоги и расходы
   обязательны для подтверждённой экономики; PARTICIPATE остаётся за доменными gates.
5. В каждой карточке открываются доступные исходные документы и ТЗ; версия,
   хэш и locator сохранены. Скрытые/невалидные URL не раскрываются через raw.
   Отсутствующий или неполный комплект показан явно.
6. Ссылка на ЕИС соответствует номеру закупки; переход может показать новую
   редакцию, что отмечено. Название и ссылка внешней площадки берутся из источника,
   не угадываются по вложению или поиску. UNKNOWN показан явно.
7. Негативные проверки tenant/stale/cursor/expired/FAIL/UNKNOWN, unit/integration,
   production build, полный обязательный release gate и сквозной beta smoke PASS.
   Установка — отдельный точный reviewable payload после подготовки и approval.

## Последовательные milestones

- B1: документы и источники в основном просмотре карточки.
- B2: извлечение и фильтр места поставки, точные ссылки ЕИС/площадки.
- B3: персональный подбор с объяснением ограничений профиля и shortlist.
- B4: привязка КП/расходов, три сценария и ранжирование сопоставимых кандидатов.
- B5: сквозной прогон с реальным профилем и закупками, gate и rollout.

Ни один milestone отдельно не означает готовность всей беты. Последний ответ
пользователя уточняет основной источник себестоимости: «Из действующих КП и
расходов, которые вводит пользователь». Это заменяет прежний выбор основного
режима по публичным ценам. Автоматические цены остаются отдельной предварительной
оценкой. Техническая привязка КП доказана на стенде; наличие пригодных реальных КП
и приёмка производственной сделки ещё UNKNOWN;
публичная цена не становится КП и не даёт PARTICIPATE.

## История B1: документы (частичный срез на момент проверки)

Рабочая копия: `tmp/beta-shortlist-20261021-v1/candidate`.
Основа — ранее принятый source archive `candidate-v3.tar.gz`, SHA256
`c41a998b8e6515c3665c987a79981f70fbd3a61198805fdfad4adb90ad49b5c5`.
Локальный основной checkout отстаёт от установленного source; его не заменяли.

Owned files внутри кандидата:

- `web/src/lib/tender-workspace.ts`
- `web/src/app/tender-discovery/workspace.tsx`
- `web/src/app/tender-discovery/tender-documents.tsx`
- `web/tests/tender-workspace.test.ts`

Добавлены исходные вложения44/223 с provenance; доступный файл открывается из
основной карточки. Для44 доступен прежний разбор документов без перехода в
расширенный поиск. Это не утверждает роль ТЗ по имени или полноту комплекта.
223: используется только validated `url.value`; `raw` не становится ссылкой,
флаги сокрытия/аккредитации/notPlacement блокируют открытие.

Исходный дефект воспроизведён на baseline: новых документов нет в модели;
регрессия отказывает с `Property 'documents' does not exist` (red log).
Проверки и исходный patch находятся в той же папке evidence. Установки нет;
B1 не закрывает отсутствие региона, профиля, прибыли, ссылок223/площадки.

После двух неуспешных попыток установки web dependencies из registry/offline
изменён способ проверки: использованы существующие dependencies из сохранённого
`s228-compiled` image, Next16.3.4; package/lock кандидата не меняются. Документация
`next/dist/docs/.../use-client.md` прочитана из установленного web image.
Первый `tsc --noEmit` требовал Next route types; штатный `next typegen` устраняет
эту причину. Итоговые результаты фиксируются после завершения проверок.


Итог B1-document slice21Oct: targeted11PASS; full web182PASS/0FAIL/0SKIP;
Next typegen, TypeScript и production build PASS. Docs268/831links/14indices PASS.
Evidence: `scope-manifest.json`, `source-delta.patch`, `source-delta.tar.gz`,
`regression-red.log`, `web-tests-final.log`, `web-build.log` в рабочей папке.
Полный release gate и сквозной production smoke не запускались: это частичный
кандидат, не готовый beta-релиз и не deployment payload.

Read-only проверка одного сохранённого223 XML (SHA совпал со snapshot) обнаружила
`urlEIS`, `urlVSRZ`, `electronicPlaceInfo/url` и отдельный
`lots/lot/lotData/deliveryPlace/region`. Регион customer/placer отличается по
смыслу и не подходит для фильтра поставки. `urlEIS` в этом примере ведёт в private
раздел ЕИС; преобразование в публичный URL не принято без проверки. Текущий
snapshot эти navigation/delivery факты не сохраняет. Нужны source-bound intake
и стратегия чтения/индексации прежних XML; подмена одним UI-селектом исключена.

## B4a: автоматический расчёт из публичных цен — частичный кандидат

B4a выполнен до B2/B3 по прежнему выбору автоматического поиска цен. После
уточнения об источнике себестоимости этот срез сохраняется как предварительная
оценка, отдельно от основного расчёта по действующим КП и расходам пользователя.
Критерии всей беты не сокращены. Привязка КП/расходов, B2/B3 и автоматический
запуск поиска поставщиков остаются открыты.

Owned files дополнительно: `domain/public_price_opportunity.py`,
`sources/public_unit_price.py`, `storage/public_unit_price.py`,
`api/public_unit_price.py`, регистрация в `api/app.py` и `api/discovery_runtime.py`;
соответствующие три unit/API test modules и `test_public_unit_price_pg.py`;
web public-unit-price model/actions/view/widget, подключение в supplier-product,
API client и wire/render tests. Все пути относительно `candidate/src/procurement`,
`candidate/tests` и `candidate/web`; точный перечень и SHA — в scope manifest.

### Принятое поведение кандидата

- Явная опубликованная цена и reference quantity читаются из exact сохранённого
  Product/Offer JSON-LD. SHA тела и locators проверяются; источник не исполняется,
  новых HTTP нет. Поддержан ограниченный UnitPriceSpecification, не произвольный
  текст сайта, код единицы или догадка о составе упаковки.
- Техническое основание: [UnitPriceSpecification](https://schema.org/UnitPriceSpecification),
  [referenceQuantity](https://schema.org/referenceQuantity),
  [valueAddedTaxIncluded](https://schema.org/valueAddedTaxIncluded), проверено21Oct.
  Это формат метаданных, не гарантия достоверности поставщика.
- Этот срез использует существующую цепочку exact-position44; адаптер223 ещё не реализован.
- Серверный readonly POST `eis-public-unit-price/read` принимает только exact
  SupplierProductRequest. Нет caller tenant/URL/HTML/чисел цены. Используется
  прежний current/hold/tenant/parent/body guard; максимум4096 байт запроса,
  прежний лимит2MiB HTML; ответы no-store, ошибки без подробностей источника.
- При открытии сохранённых условий товара web автоматически запрашивает расчёт
  на количество заказчика. Поддержаны явно сопоставимые шт/г/кг/м без конверсии;
  упаковки и неизвестные единицы не домысливаются. Округление вверх до копейки.
- Результат одной позиции не становится стоимостью всего лота или прибылью.
  База НДС берётся из источника; gross не превращается в net автоматически.
- Чистый доменный движок выбирает минимальную сопоставимую свежую net-цену каждой
  позиции. Пропущенная позиция, расходы или налоговая модель дают UNKNOWN,
  истёкший deadline и source blocker дают BLOCKED. Деньги — Decimal; чужой tenant,
  другой XML и цены несуществующей позиции отвергаются.
- Полнота состава лота сверяется с source count; отдельное evidence полноты
  расходов обязательно. Одна сумма расходов не подтверждает их полноту.
- Полный предварительный расчёт получает три сценария прежнего движка.
  Явные beta-допущения: снижение0/5/10%, рост затрат conservative10%; MOQ, шаг
  заказа, наличие и полнота ТЗ не подтверждены. Это ESTIMATE, quote/PARTICIPATE UNKNOWN.
- Доменный shortlist — до5 разных XML с положительной conservative оценкой, порядок по прибыли,
  затем марже и стабильному ID. UNKNOWN и убыточные оценки не получают балл прибыли.
  Этот движок ещё не подключён к автоматическому поиску по всему набору закупок.

### Evidence и ограничения

Scoped Python: **167PASS/0FAIL/0SKIP**, включая102 проверки домена/парсера/API/экономики
и регрессии прежних supplier page/product/API. Web **186PASS/0FAIL/0SKIP**;
TypeScript, ESLint затронутых компонентов, Ruff затронутых Python и mypy нового
доменного модуля PASS; production Next build PASS. Локальные targeted проверки
не заменяют release gate на pinned runtime. JUnit: `auto-price-results.xml`;
логи: `auto-price-python-final.log`, `web-tests-auto-price.log`,
`web-build-auto-price.log` в рабочей папке.

Два начальных сбоя API collection разобраны: недостающий psycopg в локальной
тестовой среде и ошибка forward annotation нового report model. Среда дополнена
по uv.lock, аннотация исправлена; последующий9API и последующий scoped167PASS.
Изменение способа проверки не ослабляет обязательный release gate.

Readonly replay реального сохранённого HTML:132943байта, SHA
`82b4393608fa9402dbeef32676a875c116d40d182c59230566b73f93c75af411`, совпадает с БД.
Наблюдение06Oct11:46UTC, replay выполнен на время наблюдения, не как свежая цена.
Результат UNKNOWN_EXPLICIT_BASIS_MISSING, source requests0, profit UNKNOWN.
Это подтверждает отказ от ложного умножения цены299.6 на400 пачек, а не наличие
подходящего источника для расчёта прибыли. Evidence: `saved-source-replay.json`.

Actual PostgreSQL16: **5PASS/0FAIL/0SKIP** — readonly/source0, foreign tenant/unknown
parent, hold, stale version и численный расчёт из сохранённого Product/Offer.
Позитивный случай:120RUB за10шт, заказ100шт →1200.00RUB; прибыль остаётся UNKNOWN.
Полный50-stage release gate, live browser и сквозной beta smoke не выполнены.
Production не менялся. Общая бета NOT READY; новый deployment payload не подготовлен.
Следующий проверяемый шаг — source-bound география/навигация44/223 и подключение
автоматического поиска к профилю. Полный source gate запускается перед выпуском
завершённого кандидата; отдельного approval процесса для каждого среза нет.


PG evidence: `pg-proof-v3.json`, `pg-results-v3.xml`, `pg-tests-v3.log`,
`pg-boundary-v3.txt`, `pg-test-source-v3.sha256`. Product source files и финальный
PG test file SHA совпали между локальным кандидатом и фактически проверенной копией.
Контейнеры не публиковали порты: PG network none, runner в его namespace,
source readonly; это не полный release receipt. Первый3/4FAIL сохранён в
`failed-v1-pg-tests.log`: foreign gate реально отказал, тест ошибочно ожидал
LookupError вместо точного ValueError/CHARACTERISTIC_NOTICE_NOT_FOUND_OR_MISMATCH.
Исправлен только новый тест; действующий tenant guard не ослаблялся.

Для bounded PG потребовался task-only `run-pg-check.sh`: локального Docker нет,
существующий release runner по контракту выполняет все50 стадий, а здесь проверялся
один новый slice. Использованы прежние runtime/DB рецепты и uv.lock. После двух
сбоев подготовки (недоступный JUnit через docker cp из tmpfs и неверное ожидание
наличия этого файла) изменён перенос evidence: обязательный docker exec cat.
Это не новый релизный процесс и не замена обязательного полного gate.

Тестовые контейнеры удалены. Четыре созданных этим срезом временных PG volume
проверены по времени создания, точному test namespace и двум известным тестовым
credentials внутри catalog/WAL; только они удалены, если не использовались.
Хэши credentials не выводились. Производственные тома/дампы/образы сохранены.
Proof: `owned-test-volume-cleanup-v2.json`; дальнейший task runner использует
PG tmpfs, чтобы не оставлять anonymous volumes. Проверенная версия runner
сохранена отдельно как `run-pg-check-executed-v3.sh`.

При будущем rollout обязательно сохранить установленную коррекцию bare Compose
worker v3.1: worker c2ca3bc9, файл SHA dfccf9f2f316ee82d0b2875520644d1a9d676afc3d291e6d735f9b6ec0500ebc.
Базовый source archive c41a998b был запечатан до этой operational коррекции;
его Compose не является разрешением заменить установленный маршрут worker.
Старые approval v3/v3.1 и receipt не допускают новый beta source.

Decimal сериализуется без научной нотации; повторный XML не занимает несколько
мест shortlist. Оба случая защищены регрессиями.


## B2/B4: КП, расходы и персональное финансовое сравнение — кандидат21Oct

Владелец root. Проверяемый результат: личный оператор сохраняет источник полного
КП и17 статей расходов для точной версии закупки/лота; повторное чтение проверяет
срок КП и source gates, считает три сценария и сопоставляет выбранный профиль.
Финансовое сравнение не является рейтингом допуска или PARTICIPATE. UNKNOWN
технических/юридических/неполных профильных проверок явно сохраняется; известный
блокер исключает вариант. До пяти позиций — разные закупки, лучший лот каждой.
Охват ограничен первыми20 лотами загруженной выдачи; весь рынок не заявляется.

Owned files (дополнительно к прежнему кандидату):
`domain/beta_quote.py`, `sources/tender_navigation.py`, `storage/tender_navigation.py`,
`storage/beta_quote.py`, `storage/beta_quote_schema.py`, `storage/beta_shortlist.py`,
`api/beta_procurement.py`, `api/tender_navigation.py`, wiring в app/discovery_runtime;
`migrations/env.py`, `migrations/versions/20261021_01_beta_quotes.py`;
четыре beta/navigation unit/API modules и `test_beta_shortlist.py`,
`tests/integration/test_beta_procurement_pg.py`; web beta model/actions/form/comparison,
workspace/actions/styles/API client и два существующих workspace test modules;
`scripts/beta-ui-smoke.py`. Точные пути/SHA фиксируются в итоговом scope manifest.

Acceptance среза: перезагрузка сохраняет введённое КП; чужой tenant не читает его;
аудитор не пишет; история append-only с audit; невведённые расходы не равны нулю;
срок, source FAIL/hold/stale, неверный lot и неподтверждённая цена блокируют расчёт.
Налоговый режим и выходной НДС вводятся явно; исходные условия и допущения видимы.
По профилю можно выбрать заявленный товар для поиска; известные финансовые и
географические ограничения участвуют в финансовом сравнении. Остальные ограничения
требуют review; отсутствие owner authorization не обходится.

Регион фильтруется по фактам места поставки в загруженных страницах, сохраняется
при продолжении; неизвестная география по умолчанию исключена, включается явно.
223: отдельное deliveryPlace/region, ссылка urlVSRZ и публичный source urlEIS.
44: read-only проверка актуального XML SHA
`85c1364dc283f0269603cd4ae305840fbc4d35b4d0c6aa2ef4ed61c17185f38f`
подтвердила `commonInfo/ETP/{name,url}` и адрес в
`notificationInfo/customerRequirementsInfo/customerRequirementInfo/contractConditionsInfo/deliveryPlacesInfo/byGARInfo/GARInfo/GARAddress`.
Адрес показывается отдельно. Регион из первого компонента ГАР принимается лишь
при однозначном совпадении полного названия с сохранённым официальным каталогом
регионов ЕИС; только орфографические сокращения/порядок слов нормализуются.
Город внутри области не превращается в регион. Обе исходные ссылки provenance
сохраняются, полнота всех адресов UNKNOWN. Без каталога регион остаётся UNKNOWN.
Исходный HTTP URL площадки допускается как пользовательская ссылка без fetch и
без выдуманного HTTPS; приватные/credential/local URL отвергаются. При отсутствии
прямой публичной223 ссылки даётся явно подписанный поиск номера в ЕИС через
уже существующий официальный search URL, а не выдуманная карточка.

Первые проверки:37 новых scoped PASS;9 HTTP/PG PASS на PostgreSQL16 с runtime RLS;
web187PASS/0SKIP, TypeScript/ESLint и production build PASS до последних доработок.
Результаты после доработок проверяются заново. Полный release gate ещё не принят.
Первый общий unit-прогон в урезанной PG-копии некорректен как full gate: отсутствовали
examples/docs/web и файлы корня; ошибки FileNotFoundError сохранены. Следующий прогон
использует полный снимок. Первый browser v6 не открыл страницу: compiled web image
имеет ENTRYPOINT sh; исправление запуска — явный entrypoint node и проверка readiness.
Ни один из этих прогонов не менял production.

Отдельный browser smoke нужен потому, что существующий `server-ui-smoke.py`
ориентирован на старый экран и не проверяет новую форму КП/расходов и личный профиль.
Новый скрипт использует только синтетические данные, запрещает внешние переходы,
проверяет href ЕИС/площадки/ТЗ, ввод17 расходов, три сценария, финансовую выдачу,
повторное чтение после reload, desktop/mobile и ошибки страницы. Это дополнение
к существующему release gate, не его замена.


### Сквозной прогон v12 и исправленные границы runtime

Browser v12 PASS на синтетике: выбор товара из выбранного профиля, поиски44/223,
фильтр поставки, href документов/ЕИС/площадки, форма КП+17расходов, три сценария,
прибыль35000.00, повторное чтение после reload, desktop/mobile,0 page errors.
Evidence: `ui-result-v12.json`, `ui-desktop-v12.png`, `ui-mobile-v12.png`.
PostgreSQL16:11PASS/0SKIP (`pg-results-v12.xml`); новая пара регрессий проверяет
реальный discovery-runtime и source_member223 из immutable snapshot. Локальные
runtime/quote/API/navigation regressions43PASS; web187PASS; full gate PENDING.

Браузер выявил реальный дефект, который полный create_app не показывал: lazy
IncludedRouter удалялся фильтром discovery-runtime. Cached navigation/public-price
routers теперь регистрируются после фильтра; режим pilot остаётся отделён от
личных КП. Unit guard разрешает только новый именованный beta prefix и отдельно
проверяет запрет pilot для quote/read, quote/save и shortlist. Регистрация не
открывает placeholder CaseService, исходящие действия или критические поля профиля.

После двух невалидных общих прогонов способ проверки изменён: v6-копия не содержала
всех fixtures, v8-стенд использовал tmpfs с noexec и породил82 shell/converter
отказа среды (new beta modules не падали). Общий набор выполняется штатным
release-runner, без ослабления stages/assertions/skips. Mypy locked2.3.1 с отдельным
writable cache PASS24files; default cache в readonly стенде дал INTERNAL ERROR,
это не засчитано как проверка типов. Сбор коллекции выполняется без лишнего `-q`:
из-за addopts второй quiet печатает только счётчики modules, а не node IDs.
Нулевые коллекции из черновой подготовки не используются для допуска.

В рабочем tenant read-only подтверждены400078версий44 и44432версий223 и выбранный
профильv1; целевые поля товаров/географии/финансов в нём UNKNOWN. Профиль нужно
заполнить в UI; критические ограничения owner authorization не обходятся. Эти
счётчики не доказывают национальную полноту/свежесть и не являются списком прибыли.

Финальная проверка дополнительно требует двух финансовых вариантов в браузерной
выдаче; второй синтетический КП создаётся в disposable seed. Все числовые решения
остаются вычислением по заявлениям пользователя, не независимой проверкой КП,
технического допуска или рекомендацией PARTICIPATE.


Перед финальным frozen snapshot UI-статус расчёта переведён на русский язык;
машинный CALCULATED остаётся в data-атрибуте и API. Идентификаторы новой декларации
выдаёт server action через node:crypto: публичный HTTP origin может не иметь
browser crypto.randomUUID. Финальный browser smoke отключает этот browser метод,
проверяет два финансовых варианта и сохранение/повторное чтение. Продуктовые
permissions и PART gates не меняются; code freeze перед полным gate.


Финальный self-review отделил фильтр от вердикта: неподтверждённый выбранный регион
и неприбыльный сценарий исключают позицию из финансового порядка, но сами по себе
не объявляют профиль FAIL. FAIL остаётся только за известным нарушением правила
профиля; добавлены две регрессии UNKNOWN. Scoped runtime/quote/navigation45PASS.
Первый запуск полного gatev14 остановился до тестов: копия tool bundle содержала
mutable buildx state, immutable inventory guard сработал. Receipt не выпущен;
следующий provider собирается только из проверенных executor/verifier, config.json
и pinned buildx plugin. Критерии и защиты не ослабляются; полный gate запускается
заново для нового frozen source.

Финальный срез: защита UI от устаревшего CALCULATED после истечения КП/закупки,
сохранение полей и idempotency UUID после ошибки транспорта. Node192PASS, web build
PASS; добавлены пять регрессий срока и source identity. Полный gatev15 завершился
FAIL при загрузке locked openpyxl: UV HTTP timeout30s. Executor меняет только
таймаут загрузки на300s (pip/uv), frozen lock и общий build cap1800s сохранены;
это защищено regression test. Новый frozen snapshot требует свежего полного gate.

Операционный инцидент: около22:13MSK21.10 Docker daemon перезапустился, причина
не установлена. Шесть прежних контейнеров запущены без пересоздания. API health и
web tender-discovery HTTP200; API c2ca3bc9, web cec6383b, compose SHA
`dfccf9f2f316ee82d0b2875520644d1a9d676afc3d291e6d735f9b6ec0500ebc`
сохранены. Бета не активирована, её миграция на production не применялась.

Browserv17: ввод/сохранение/reload, два финансовых варианта и ссылки прошли,
но проверка скачка часов после reload выявила устаревший UI-статус. PASS не
выдан. Таймер срока ограничен60s вместо24дней: после скачка/возврата вкладки
проверка времени срабатывает не позже очередного минутного tick. Browserv18
проверяет скрытие после скачка и одного tick; source изменён, нужен новый gate.

После двух неудачных clock-попыток diagnostic установил переполнение интервала
Playwright: +172800000000ms фактически дало +1001308160ms, дата02Nov2026, КП
до2030 ещё действовало. Новый тест устанавливает точную дату2032 и проверяет
Date.now перед assertion; продуктовый минутный tick сохранён. Предыдущий вывод
о доказанном stale UI дефекте не подтверждён диагностикой.

Gatev17b:3809unit,2FAIL/27allowedSKIP: legacy converter exec PermissionError.
Контроллер ошибочно запущен sudo/root: /test mode0700root, launcher сбрасывает
UID доnobody и не может выполнить synthetic converter. Seccomp установлен и
сработал. Правильный запуск — штатный nonroot syurai controller с docker через
существующий sudo boundary. Worker ownership/exec scratch и assertions сохраняются;
никакой chmod production, ослабления sandbox или новых skips. v18 также запущен
root и не может допускать релиз; новый полный gate нужен от правильного UID.
Локальная повторная web build дважды встретила stale Turbopack process path;
после вынесения только generated .next cache clean build PASS, исходники/lock прежние.

Финальный Browserv19PASS (frozen source02d0cf7c): два финансовых варианта,
профиль→регион→КП/17расходов→3сценария→reload, принудительный сбой save и
сохранение формы, отсутствие browser randomUUID, source href223 и скрытие
просроченных результатов при явной дате2032. Page errors0; PG11PASS.
Синтетика не доказывает скачивание реальных внешних ТЗ: внешняя сеть стенда закрыта.
Screenshots/evidence: tmp/beta-shortlist-20261021-v1/ui-{result,desktop,mobile}-v19.*.
Gatev19 nonroot1000:1002; исходники заморожены, итоговое live evidence ведётся
здесь отдельно от bundle, без повторного использования receipt для изменённого кода.

Адаптер активации готовится отдельно: существующие full_migrate/старый exact
adapter фиксируют прежнюю схему20261015_01 и иной перечень файлов. Поэтому
activate-beta-approved.py ограничен одним active compose, additive20261021_01,
API/web и свежим50stage receipt. Worker/base compose/cron не меняются. Это
конкретный блокер повторного применения старого helper, не новый общий механизм
согласования. Guard proof: неверный payload/отсутствующий human approval отвергнуты,
symlink target отвергнут, owned migration container очищается при exit0/1.
Активация ещё не разрешена/не выполнена.

Gatev19 дошёл до guarded downgrade223: прежнее точное ожидание head20261015_01
не соответствует additive20261021_01. Исправлена ровно одна строка ожидаемой
версии в test_eis_223_general_pg.py; запрет downgrade с hidden tenant history,
сохранность точного head после отказа и исходного извещения не ослаблены. Других
жёстких20261015_01 в integration tests нет. IDs/counts/skip policy неизменны.
Для нового sourcev20 нужен полный свежий gate; браузерное приложение и входы
не менялись, UI evidencev19 применимо только после byte-equality proof.

Целевой regression после исправления schema head:6PASS на disposable PostgreSQL16.
Frozenv20 SHA14f77bed; diff кv19 — только два документа и одна строка теста
(плюс manifest); src/web/migrations/locks byteexact. Full gatev20 выполняется.
После сборки дополнительно будет проверен тот же сценарий на самих API/web
release images: прежний stand монтировал compiled .next, поэтому готовый driver
переиспользован с отдельным API container и без source/.next overlays на runtime.
Это проверка изменившихся условий сборки, не повтор старой успешной проверки.

Финальный результат21Oct: release source14f77bed, receipt SHA
`901b722028c9808081e5a65fcdb5ebe6015fe5e68e3bcb07fd8b7784675ddf9c`.
API image128ec253, webc724122d. All50stagesPASS; cleanup complete. Actual-image
browser PASS, runtime source overlays/Next overlays отсутствуют. Test networknone,
внешние запросы/production writes0; ТЗ проверены как source href, не live download.
Read-only activation preflight PASS; rollout изменяет один active compose, API/web
и additive schema20261021_01. Worker c2, bare compose, cron, данные и backups
сохраняются; rollback возвращает c2/cec и сохраняет новую immutable историю КП.
Guard proof7PASS: payload/approval, symlink/mode/owner, migration success/failure,
чужой image и занятое container name. Activation ещё НЕ выполнена.
Frozen bundle не менялся после gate; эти финальные результаты — внешнее live evidence.

Установка по payloadae868bf6 подтверждена пользователем и применена21Oct20:21UTC:
operationba317ff1-168e-41ec-8c8c-9aa2b301b0de, INSTALLED_HEALTH_PASS, schema20261021_01,
API128ec253/webc724122d, DB container прежний, worker/base compose/cron прежние.
Live read3активных44: NAVIGATION_NOTICE_IDENTITY.223read3успешны (две записи с
регионами, три с площадками). Диагностика9c9d9bdfXML доказывает EPtypes identity/
commonInfo, base ETP leaves, common GARInfo/GARAddress; synthetic export-only
fixture это не покрывал. Это дефект реализации, не допуск неизвестных данных.
B6 исправляет только pinned namespaces/path, без local-name fallback/ослабления
identity или прав. Приёмка всей беты до live44 исправления не заявляется.

B6 candidate: pinned EPtypes/base/common profile, export-only compatibility
сохранена; cross-profile identity/duplicate commonInfo отвергаются.8новых unit
кейсов,22navigation PASS; red на прежнем parser5FAIL сохранён. Real offline replay
XML9c9d9bdf + official catalogb57a42d5: Астраханская область,1GAR address,
roseltorg.ru; coverageUNKNOWN, обе provenance сохранены. Сырые источники только
samples/private/beta-navigation44-20261021 (ignored); в пакет/fixtures не включены.
Scope/evidence нового API-only исправления: tmp/beta-navigation44-20261021-v21.
Fresh full gate обязателен; текущие API128ec253/webc724122d и schema20261021_01
пока прежние. Новый payload ещё не сформирован/не разрешён.

## Готовая API-only коррекция44 (v21)

Реальный EPtypes/base/common XML проверен в новом image: Астраханская область,
адрес и площадка извлечены. Все остальные Python modules совпадают с установленной
бетой. Gate50/50PASS: Python3790PASS/27allowedSKIP, PostgreSQL701PASS,
Node192PASS. Сквозной browser на новом API и установленном web PASS: профиль,
регион, КП/17расходов, три сценария, два финансовых варианта, reload, транспортный
сбой, expiry и ссылки. Стенд синтетический, production writes0.

Payload: `tmp/beta-navigation44-20261021-v21/activation-plan.json`, SHA256
`cd6aa08ddccc1b84a02e90def4096c55c86896fb6e2657b9e41c9815e4f8448e`.
Read-only preflight PASS. Перезапускается только API (image0c563705), schema,
web, worker, cron и base compose сохраняются. Коррекция подтверждена пользователем и установлена22Oct08:14МСК.
Повторно не применять; результат и оставшийся блокер ниже.
Evidence и передача: `tmp/beta-navigation44-20261021-v21/handoff-current.json`.

## Live acceptance после применения cd6aa08d, 22 октября

Operation77e80daf-3170-4c47-8989-47e270fb7752: INSTALLED_HEALTH_PASS.
API0c563705 установлен; web/DB container IDs, schema20261021_01, worker и cron
сохранены. Реальная навигация44/223 6/6PASS; исправленная44 через HTTP200
с no-store, регионом, площадкой и provenance. UI223 PASS: поиск, включение/
исключение по региону, ЕИС и площадка, page errors0. HTTPS TLS PASS, ожидаемый401.
После установки загрузчик44 записал6SYNCED/54NO_DATA к08:19:22МСК. Для223
в этом коротком интервале попыток нет: post-install progress UNKNOWN.

Общий UI поиск44/all не принят: карточка не появилась за90с; диагностическая
попытка30с всё ещё показывала «Ищем закупки». PostgreSQL продолжал FETCH и
search_hold_scope, точная причина latency требует query plan. Это отдельный
блокер B7; исправление namespace не доказывает готовность всей беты. Реальных КП0,
поэтому экономика реальной сделки UNKNOWN. Синтетический сквозной тест PASS
не подменяет этот live FAIL. Пользовательские финансовые данные не изменялись.

Evidence: activation-audit.json, live-navigation.json, live-http44.json,
live-ui223-readonly.log, live-ui44-readonly.log, live-ui44-diagnostic.log,
live-final-state.json и live-acceptance.json в tmp/beta-navigation44-20261021-v21.
Следующее действие: план/стоимость реального поиска44 и bounded исправление
производительности с сохранением всех variant hard gates.

## B7: исправление плана поиска44, кандидат v22

Ownerroot; owned production file storage/eis_notice_hold.py и два status docs.
Read-only profiling: scope393пар0,05с, scoped pairs0,02с; audited decisions
и resolved pairs превышают statement timeout15с. EXPLAIN показывает lateral
jsonb_array_elements до отбора связанных batches/audit events. Новый helper
материализует полный exact audit binding до раскрытия массива; tenant, parser,
payload hash, event type/object/id, длина полного массива, exact origin/variant,
conflict и tenant-wide receipt integrity остаются прежними. Никакого кэша допуска.

Read-only shadow Python на реальной базе: точный номер4,5с/1match, бумагаА4
9,8с/713matches, перчатки8,7с/305matches; held1 сохранён. Production source
не заменён, все обращения consistent read. До изменения записан red timeout
и план SQL; после изменения scoped unit11PASS. Следующий шаг: полный gate,
реальные HTTP/UI на отдельных candidate containers и isolated synthetic beta
E2E, затем exact payload. Наличие этого кандидата ещё не закрывает live FAIL.

## B7: готовый пакет установки, ещё не применён

Frozen sourcev22 SHA5cd80fd9, treee7569935, manifest35b86d39. Gate50/50PASS:
Python3790PASS/27allowedSKIP, PostgreSQL701PASS/0SKIP, Node192PASS/0SKIP,
9doctestsPASS. Receipt SHAe65c7260. Остальные246Python modules точны к текущему
API0c563705; изменён только storage/eis_notice_hold.py (SHAaf98da40).

Новый actual API imaged6926c0f + установленный webc724122d прошли realDB
browser test без source/.next overlays и без опубликованных портов: номер44
5,925с, бумагаА4 по обоим законам12,917с, номер223 0,307с. Проверены включение/
исключение по региону, ЕИС и площадка; page errors0. PostgreSQL
default_transaction_read_only=on и transaction_read_only=on подтверждены.
Production business writes0, external source requests0. Отдельно actual images
прошли synthetic E2E: профиль, КП/17расходов,3сценария,2финансовых варианта,
save/reload, transport failure, expiry, document/ЕИС/platform href; errors0.

Payload: `tmp/beta-search44-20261022-v22/activation-plan.json`, SHA256
`11e004f194d2967748f69b060f718da3821ca77581d07f29c7c302d7080c3ae0`.
Read-only preflight PASS. Адаптер прошёл проверки exact payload, обязательного
approval reference, symlink/owner/mode, API-only install/rollback и no migrations.
Изменяется только API; web, DB/schema, worker, cron и base compose сохраняются.
Payload связывает receipt, synthetic browser, realDB browser, source delta и
real44 XML replay. Следующий шаг — human exact-payload approval и установка,
затем live browser на установленном API. До этого production latency остаётся
блокером; результаты candidate test не выдаются за установленный релиз.

Evidence: fullgate-summary.json, real-result-parity.json, real-database-browser-
proof.json, release-image-browser-proof.json, ui-result.json, activation-preflight.json
и handoff-current.json в tmp/beta-search44-20261022-v22. Реальных КП0: прибыль
реальной сделки остаётся UNKNOWN до ввода пользователем. Remote downloads
документов не проверялись; href не доказывает доступность внешнего сервиса.

## B7 применён: проверка установленного API, 22 октября

Утверждённый payload11e004f194d2967748f69b060f718da3821ca77581d07f29c7c302d7080c3ae0
применён09:52МСК. Operationd717503d-354e-4047-bd90-0a8b1526cc07,
INSTALLED_HEALTH_PASS; новый API containera068487f/imaged6926c0f. Состояние
DB/web containers, schema, worker image/limits, cron и base compose подтверждено
адаптером. Tenant-scoped activation audit2. Повторно пакет не применять.

Browser обращался к установленному web/API, без temporary API или source overlays:
номер44 4,937с/1карточка; бумагаА4(all)11,951с/200карточек; номер223 0,315с.
Включение/исключение по региону и ссылки ЕИС/площадки PASS; page errors0.
Проверка personal quote/read, quote/save, shortlist с pilot token: все401.
Реальных КП0, финансовые записи пользователя не изменялись. HTTPS TLS PASS,
ожидаемый401 внешнего Basic Auth. В кратком post-install интервале loader
attempts44/223 отсутствуют: новый progress в нём UNKNOWN, cron сохранён.

Bounded technical beta PASS: серверная цепочка КП/17расходов/профиля/3сценариев/
нескольких финансовых вариантов проверена на тех же actual images в отдельной
синтетической PostgreSQL БД; поиск/регион/ссылки дополнительно на реальном
установленном сервисе. Реальная прибыль и допуск не объявляются PASS без входов
и hard gates. National freshness остаётся INCOMPLETE, remote downloads не
проверялись. Следующий шаг — ввод действующих КП, расходов и уточнение профиля.

Evidence в tmp/beta-search44-20261022-v22: activation-audit.json,
live-installed-proof.json, live-ui-result.log, live-beta-installed.png,
live-private-loader.json, public-https-after.json, live-acceptance.json.

## B8: простой поиск и дорогие закупки

Новый запрос: товар → место поставки → «Найти закупки» → «Сначала дорогие».
КП/расходы для этой операции не нужны. Кнопка сортирует начальную сумму лота
по убыванию в RUB/RUR среди загруженных результатов выбранного региона.
Исходные Decimal strings сравниваются без float/округления, FX и сложения
нескольких лотов. Неизвестные, текстовые, foreign и multi-lot суммы не становятся
сопоставимой ценой. Hard-blocked строки остаются blocked и следуют после остальных.
Это просмотр сумм закупок, не прибыль и не рекомендация PARTICIPATE.

Сортировка сохраняется при смене региона/подгрузке страниц, можно вернуть
«Порядок поиска». Финансовый shortlist сохраняет прежний выбор loaded lots.
Region navigation читает всю bounded страницу до200карточек (100на закон),
с concurrency3; ранее cap50 мог оставлять адреса остальных карточек UNKNOWN.
Общая полнота ЕИС/адресов не объявляется PASS.

Ownerroot;6web source/test files и2status docs, scope.json в
tmp/beta-price-sort-20261022-v23. Red regression: missing sort API и cap50!=200.
Node regression покрывает exact huge/fractional Decimal, stable ties/immutability,
FX/text/multi-lot refusal, FAIL, region+append и bounded200read. Следующий шаг —
полный gate и actual-image realDB UI, затем web-only exact payload.

## B8 готов к установке: проверка реальной выдачи

Source archive8807ce73, tree707c87c8, manifestc40ba55b; gate50/50PASS,
Python3790PASS/27allowedSKIP, PostgreSQL701PASS, Node197PASS, doctests9PASS.
Регрессионные5Node cases добавлены к сохранённым192; collection SHAac0f05c8.
Source delta8files, API/миграции/locks неизменны.247Python modules retained API
d6926c0f точно совпали с candidate API artifact4218f610, установленный API сохраняется.

Actual new WEB2692d128 + retained API проверены с real production DB в
default_transaction_read_only=on, без source/.next overlays и опубликованных портов.
Поиск номера44 4,959с; бумагаА4(all)18,078с с region evidence всей страницы200;
номер223 0,358с. Price-desc196priced rows PASS; source-order reset PASS;
Амурская область418649,00>80786,00 PASS; continuation300/296priced rows с
сохранением сортировки PASS. Mobile/no-horizontal-overflow PASS, page errors0.
Все source hard-blocks сохранены. Real business writes0, external requests0.
На той же паре runtime images isolated synthetic full beta E2E PASS: профиль,
КП/17расходов,3сценария,2варианта, reload/expiry/transport guards, source href.

Payload `tmp/beta-price-sort-20261022-v23/activation-plan.json`, SHA256
`b115d3024cbcf9897bc3ed1fe72065e287ae2df5031eb30a59fc9f48d8f1d3e9`.
Read-only preflight PASS. Адаптер/mock guards подтверждают exact payload,
обязательный human approval reference, owner/mode/symlink refusal, WEB-only
install/rollback без миграций. Меняется только WEB, API/DB/schema/worker/cron
сохраняются. Новая функция ещё НЕ установлена: следующий шаг — human exact-payload
approval, применение и live UI against installed WEB.

Evidence в tmp/beta-price-sort-20261022-v23: source-delta.patch/json,
web-tests.log, web-collection-delta.json, fullgate-summary.json,
real-database-browser-proof.json, real-beta-v23.png, ui-result.json,
api-equivalence-proof.json, activation-preflight.json, handoff-current.json.
Root web source отличается от установленного baseline и сохранён; complete source
в tmp/beta-shortlist-20261021-v1/candidate, patch применяется к sealedv22.
Сортировка только по загруженным страницам: полнота/самый дорогой во всей ЕИС
не заявляются. Финансовый shortlist остаётся отдельной операцией с КП.

## B8 установлен: сортировка и регион на рабочем сервере

Подтверждённый payloadb115d302 применён22Oct2026, завершение10:29:18UTC
(13:29МСК); operation139cbaf5-3533-4138-bb11-8e19e047ae84.
WEB image2692d128, container7975e4d7; APIa068487f и DB42ac4fdf сохранены,
schema20261021_01, worker/runtime budgets, cron и base compose неизменны.
Старые deployment payloads, включая b115d302, повторно не применять.

Первая установка73a458cd-0fca-4691-a68a-5cccf654aae3 выявила startup race:
full_health делает WEB fetch сразу после compose up; connection refusal до
готовности Next.js вызвал откат, и та же гонка прервала завершение audit отката.
Прежний WEBc724 восстановлен и отдельно проверен healthy. Сохранены исходный
activation-audit-startup-race.json и startup-rollback-reconciliation.json;
состояние первой операции закрыто tenant-scoped central audit.

Новый ограниченный reconciliation helper потребовался, потому что sealed executor
не умеет возобновление после отката с новым WEB container ID и не ждёт WEB startup.
Он проверяет исходные неизменные plan/executor/helper hashes, все artifact/gate/config
проверки; меняется только ожидаемый WEB ID подтверждённого отката в проверке before.
Устанавливает тот же одобренный image/config, добавляет bounded readiness retry60s.
Два коротких lease timeout из-за фонового ЕИС импорта устранены увеличением только
ожидания до import900s/остальные600s: исходные порядок/marker/cleanup сохранены,
тождество source с pinned lease кроме timeout проверяется. Никаких новых образов,
миграций или смены политик. readiness retry/terminal failure checks PASS.
Helpers: reconcile-startup.py SHA53cfffc097c873c6de0b63c7756057af567fd9b9b726c7e1fc4769833feb5936,
reconciliation-lease.py SHAeef7bf5bd908829b880456c7e990ac294240512f0cf7880b03dbdd05138853dd.

Live browser против установленного WEB и retained API с реальной базой PASS:
196 priced rows descending; Амурская область418649,00>80786,00;
возврат «Порядок поиска» точен; continuation300/296priced rows сохраняет sort;
Москва исключает контрольные закупки44/223, Астраханская/Ленинградская включает.
Номер44 4,931с, бумагаА4(all)17,973с, номер223 0,321с; ЕИС/platform href PASS,
mobile390px без horizontal overflow, page errors0. Business writes0, external source
requests0. Public HTTPS/TLS PASS, штатная BasicAuth401.

Evidence в tmp/beta-price-sort-20261022-v23: activation-audit.json,
live-installed-proof.json, live-ui-result.log, live-acceptance.json,
price-sort-desktop.png, price-sort-mobile.png, public-https-proof.json.
Путь пользователя: обновить /tender-discovery → товар → «Место поставки» →
«Найти закупки» → «Сначала дорогие». КП для такого поиска не нужны.
Сортируется загруженная выдача, а не вся ЕИС; дорогая сумма закупки не является
подтверждённой прибылью. Национальная полнота/свежесть и реальная экономика UNKNOWN.


## B9 — поиск дорогих закупок по всей сохранённой базе (кандидат)

Owner root; owned files/acceptance: tmp/beta-global-price-20261022-v24/scope.json.
Зависимости — установленный B8 source8807ce73, API d6926c0f/WEB2692d128,
[контракт continuation](../adr/0106-eis-search-continuation.md).
Новый общий server search применяет запрос, delivery region и exact RUB rank до
выбора100 строк из обоих законов; следующая страница имеет один общий cursor.
В форме после выбора региона нажать «Найти закупки»; «Сначала дорогие» запускает
новый поиск по полному сохранённому корпусу. Изменение global filters очищает
прежний результат и invalidates pending response; continuation не смешивает snapshots.
В памяти только batch, top100 и один source archive/catalog; КП/экономика отдельно.

Focused52 Python/API/cursor checks PASS; Node199PASS; real PG410 synthetic notices
подтвердил top вне legacy100, регион до limit и общий проход без потерь/дублей.
Первый PG fixture ошибочно сложил205XML в архив выше существующего member limit;
разбит на три архива без изменения лимитов. Добавлены поздний импорт/UNKNOWN и
cancellation cases; новый focused прогон, full gate/actual-image realDB ещё требуются.
Production остаётся B8, ни один новый payload ещё не применён.

B9 focused после коррекции: Python/API/cursor/navigation71PASS, Node199PASS;
10PG checks PASS (5 новых global и5 прежних continuation). Global tests включают
поздний импорт, UNKNOWN-region opt-in, tenant/law/region isolation и cancellation.
Диагностика realDB с readonly overlay выявила113s/110s для регионов при per-notice
чтении. Bounded batch source admission с прежним hold predicate, archive grouping
и exact-binding cache уменьшили Амурскую область до58,235s с cProfile;10совпадений,
314UNKNOWN-region сохранились. Без региона23,468s/1502 matches в первом замере.
Нельзя называть это actual-image acceptance: frozen build/browser/full gate впереди.
Повторные чтения source archive ограничены50MiB до передачи в Python (SQL CASE),
cache связывает tenant/law/hash и44window/response; metadata не более500 source rows.

До выпуска self-review обнаружил новый browser→server-action transport failure:
loadGlobalMore не ловил сетевой reject и мог оставить pending. Добавлен catch с
сохранением строк, снятием pending и повтором; stale generation не обновляется.
Browser acceptance дополнен однократным abort и успешным retry. Первый gate source
3d574128 остановлен владельцем для нового frozen source; cleanup complete, его
частичные PASS не являются release receipt. Все обязательные stages повторяются.

Окончательный sourcev24b: archivea20d20b8, treebaa0b634, manifest38e7b3aa,
1350files/17delta. Новый full gate release-20261022-112448-8aa1923ec8e2:
50/50PASS, unit3810PASS/27allowedSKIP (3837collected), PG706PASS/0SKIP,
Node199PASS/0SKIP, doctests9PASS; все прежние test IDs сохранены. Cleanup complete.
Accepted artifact API6b6954a2 и WEB949064db, worker artifact не устанавливается.
Дополнительный frozen-source price-boundary check8PASS: initial/max/text/missing,
foreign/formula/commodity/multilot; evidence price-boundary-proof.json.
Actual image browser проверяется на realDB readonly с memory API1GiB/WEB768MiB
как в production, CPU1 (production без CPU quota). Deployment не выполнялся.


## B9 готов к установке — actual image realDB и beta acceptance

API6b6954a2/WEB949064db из финального gate проверены без source/.next overlays
на real production DB с default_transaction_read_only=on и прежним API container ID.
Память как production: API1GiB (peak595648512B), WEB768MiB (peak221151232B), OOM0.
Глобальный запрос «бумага А4»19,531s,100priced rows; top99969142,27 /75713181,50 /
55832715,52руб.79/100 не входили в прежние первые200. Следующая общая страница200/
200priced rows сохраняет порядок, transient browser→action abort сохраняет строки
и доступный retry; повтор успешен. Амурская область46,692s,10matches, top1522368,4 /
418649 /343987,97руб. Exact normalized source region «Амурская   обл» подтверждён.
Номер44 с Астраханской областью4,572s;223 с Ленинградской0,271s; ЕИС/platform hrefPASS.
Mobile/no overflow, source-order reset и page errors0. Business writes0/source requests0.

Первая browser попытка остановилась на literal fullname вместо source abbreviation;
вторая — на unbounded Response.finished для RSC stream (stack сохранён после
остановки только собственного browser check). Исправлен только test harness:
matching POST args + fresh visible UI, exact normalized source fact, driver timeout300s.
Финальный полный сценарий PASS на тех же accepted images; продукт не изменялся.
Evidence real-database-browser-proof.json/real-ui-result.log и global-price-*.png.

На той же паре images isolated synthetic full beta E2E PASS: профиль/регион,
КП/17расходов/3сценария,2финансовых варианта, save/reload, transport form guard,
clock expiry и document/ЕИС/platform href. Реальные личные данные не менялись.
Proof release-image-browser-proof.json и ui-result.json. Adapter simulation9checksPASS:
exact payload/approval, symlink/owner/mode, API+WEB install/rollback, readiness retry,
аудит UNKNOWN при ошибке восстановления, no migration. Readonly preflight PASS.

Пакет `tmp/beta-global-price-20261022-v24/activation-plan.json`, SHA256
`37547d897816e1493bc0b0c22b7bb2bfe7a0b8dc117a63da728dd4c07fe5c9f5`.
Меняет только API/WEB; DB/schema20261021_01, worker c2, budgets, cron/base compose
сохраняются; откат возвращает API d6926c0f/WEB2692d128. Старые SHA не применять.
Точный human approval получен; B9 установлен22Oct15:46МСК. Live evidence ниже.
Полный код/owned17files и patches к sealedB8 зафиксированы в handoff-current.json.
Global price — вся matching сохранённая база, не полнота национальной ЕИС и не прибыль.


## B9 установлен по подтверждённому пакету

Payload37547d89 применён после явного подтверждения пользователя; operation
`db996aca-4780-4265-b7c3-9151f6236344`, activation `INSTALLED_HEALTH_PASS`.
API6b6954a2/WEB949064db; DB ID42ac4fdf/schema20261021_01, worker c2,
cron/base compose/budgets сохранены. Миграций и обновления источника не было.
HTTPS публичного адреса отвечает401 с Basic authentication при проверенном TLS.
Evidence: `tmp/beta-global-price-20261022-v24/activation-audit.json`.

Установленная пара images проверена browser test на рабочей базе: PASS.
«Бумага А4»: обычный поиск19,515s, глобальная цена20,558s;100priced rows,
80/100 вне старых первых200; top99969142,27 /75713181,50 /55832715,52руб.
Continuation200/200priced rows в общем порядке; transport abort/retry PASS.
Амурская область49,387s,10matches, source «Амурская   обл» подтверждён.
Номер44/Астраханская область4,507s;223/Ленинградская0,268s, ЕИС/platform hrefPASS.
Mobile/no overflow, source-order reset, page errors0. Business writes0/source requests0.
Evidence `live-installed-proof.json`, `live-ui-result.log`,
`global-price-installed-desktop.png`/`global-price-installed-mobile.png` в том же tmp.
Пользователь: обновить страницу, ввести запрос и место поставки, «Найти закупки»,
«Сначала дорогие»; продолжение сохраняет общий порядок. КП для этого не требуется.
Сортировка охватывает сохранённую matching базу; национальная полнота ЕИС не заявляется.
