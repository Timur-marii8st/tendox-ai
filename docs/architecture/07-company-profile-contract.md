# Профиль компании: историческая ревизия и контракт для сравнения

Дата исторической ревизии: 2026-10-14. Статус этой вводной и следующей таблицы:
контракт предложен и зафиксирован **до реализации**; это не текущий production
статус.
Владелец ревизии: root. Продуктовый результат — проверенная карта реализации,
типизированный вход отдельного агента сравнения и один законченный будущий путь
«создать → сохранить → отредактировать → сравнить».
API, миграции и интерфейс этого пути ещё не реализованы. ЕИС вне среза.

Текущий указатель: реализационные и интеграционные материалы находятся в
[08-company-profile-implementation.md](08-company-profile-implementation.md),
[09-company-profile-api.md](09-company-profile-api.md),
[10-profile-search-comparison-integration.md](10-profile-search-comparison-integration.md)
и [beta shortlist](../operations/123-beta-shortlist.md); общий live-статус — в
[плане реализации](../15-implementation-plan.md). Корректировка owner-статуса
ещё ведётся; эти ссылки не означают завершённость.

Основания: [PRD §2–2.1](../product/11-product-requirements.md#2-первоначальная-настройка-компании),
[Company Profile Manager / Legal & Policy Engine](../product/14-product-agents.md),
[домен](01-domain-model.md), [ADR0006](../adr/0006-reviewed-case-before-automation.md),
[ADR0007](../adr/0007-postgres-rls-and-bearer-tenant.md).

## Историческая ревизия 2026-10-14: «Что уже есть» до реализации

| Область | Подтверждено кодом | Граница |
|---|---|---|
| Данные | [company.py](../../src/procurement/domain/company.py): frozen `CompanyProfile(company_id, version)` и вложенные identity/geography/finance/prohibitions | Самостоятельного сохраняемого агрегата профиля нет; нет provenance полей, timestamps и digest профиля |
| Валидация | Формат ИНН/КПП/ОГРН, непустая деятельность и территория, уникальные rule_id, согласованные финансовые лимиты; деньги конечные Decimal, float/bool отвергаются | Реквизиты проверяются по форме, не по реестру/контрольной сумме; неизвестные обязательные реквизиты/финансы сохранить этим типом нельзя |
| Хранение | [case_versions](../../src/procurement/storage/models.py) хранит полный JSONB `ProcurementCase`, включая profile; [repository.py](../../src/procurement/storage/repository.py) сохраняет неизменяемые версии, tenant/RLS и write receipts | Это версии кейса с вложенным профилем; нет таблицы независимых версий профиля и единого текущего профиля tenant |
| API | [app.py](../../src/procurement/api/app.py): POST `/v1/cases`, GET списка/точной версии, POST оценки; bearer tenant, Idempotency-Key и конфликты версии | Нет маршрутов create/read/update для профиля; нельзя править профиль независимо от всего кейса |
| UI | [pilot-dashboard.tsx](../../web/src/app/pilot-dashboard.tsx), [actions.ts](../../web/src/app/actions.ts): импорт полного JSON кейса, список, оценка; форма case-from-evidence также принимает JSON | Нет формы компании, восстановления её данных, редактирования с diff или выбора версии профиля; TypeScript `ProcurementCase` в procurement-api.ts даже не описывает profile |
| Использование | [cases.py](../../src/procurement/domain/cases.py): tenant consistency; profile входит в `case_input_digest`; изменение его версии/данных инвалидирует старый assessment | `evaluate_case` автоматически проверяет только min/max суммы, min_margin/min_expected_profit и price_floor_margin после gates/КП/сценариев |
| Остальные правила | Шесть ручных GateCheck, известные PASS/FAIL требуют evidence | Автоматического сравнения деятельности, географии, площадки, субподряда, обеспечений и prohibitions в evaluator нет; строки condition не образуют работающий реестр предикатов |

Разрыв с PRD: лицензии/СРО/аттестации, структурированные чёрные списки,
аванс/отсрочка, оборотные средства и налоговая политика не представлены в
CompanyProfile. `legal_basis: str` не заменяет официальный источник, дату действия
и проверку применимости. Архитектура экономики требует налоговой модели профиля,
но в коде НДС хранится в КП/сценариях. Автоматического переноса налогов нет.

Историческая строка покрытия «tenant-scoped версии в БД и первый UI» означала
версии **кейса**, а не завершённый CRUD компании. Ревизия уточняет эту границу.
`enabled_platforms`, `allowed_procedure_methods`, `subcontracting_allowed` имеют
defaults; отсутствие явного ввода/источника нельзя считать подтверждённым выбором.

## Контракт CompanyProfileSnapshotV1

Один профиль на tenant; отдельный profile_id в первом срезе не нужен.
Заголовок снимка и все поля строгие (`extra=forbid`), снимок неизменяемый.
Доменный CompanyProfile сохраняется: новый транспортный DTO нужен для UNKNOWN
и evidence, а полный набор значений валидируется существующими вложенными типами.

| Поле заголовка | Тип и значение |
|---|---|
| schema_version | Literal `company-profile-snapshot-v1`; версия формы данных, не номер редакции |
| company_id | непустой str; только из authenticated Principal |
| version | int >=1, последовательный серверный номер редакции |
| parent_version | int >=1 или null только для первой редакции |
| created_at / created_by | timezone-aware datetime / actor_id из Principal; устанавливает сервер |
| effective_at | timezone-aware datetime; в первом срезе равно created_at, отложенная активация отсутствует |
| currency / amount_basis | Literal `RUB` / `EX_VAT`; все денежные лимиты на базе без НДС, явно подтверждается при вводе |
| facts | строгий объект полей из таблицы ниже; все ключи присутствуют, неизвестность явная |
| policy_confirmation | серверная запись actor_id, confirmed_at, command_sha256 и changed_paths для точного сохранённого ввода |
| snapshot_sha256 | 64 lowercase hex; SHA-256 канонического снимка без этого поля |
| audit_event_id | непустой str, ссылка на tenant-scoped audit сохранения |

Каждый лист `facts` имеет тип `ProfileFact[T]`:

```text
knowledge: KNOWN | UNKNOWN | NOT_APPLICABLE
value: T | null
sources: tuple[ProfileFieldSource, ...]
reason: str | null
```

Это состояние знания, **не** PASS/FAIL сравнения. KNOWN требует типизированное
не-null value и хотя бы один проверяемый source. UNKNOWN требует null и
непустую причину: NOT_PROVIDED, SOURCE_MISSING, AMBIGUOUS, CONFLICTING_SOURCES
или UNSUPPORTED_FIELD; sources могут показывать конфликт. NOT_APPLICABLE
допускается только для kpp (подтверждённая неприменимость к реквизитам) и
max_distance_km (явно нет ограничения); требует reason и sources.
Пустая строка не факт. Неизвестное число не равно нулю, boolean не равен false.
Известные false, 0 и [] сохраняют самостоятельный смысл.

### Поля facts и переиспользование

Здесь указаны типы T; JSON tuples/sets передаются массивами, Decimal — только
десятичной строкой. Денежные числа JSON, NaN/Infinity и bool запрещены.
Границы берутся из company.py, в том числе при неполном вводе; противоречивые
известные значения отклоняются, а не переводятся в UNKNOWN.

| Путь | Тип T / ограничения |
|---|---|
| identity.name | str, непустая |
| identity.inn | str, 10 или 12 цифр |
| identity.kpp | str, 9 цифр; UNKNOWN и NOT_APPLICABLE различаются |
| identity.ogrn | str, 13 или 15 цифр |
| identity.legal_form | str, непустая; юридическая форма не выводится только из длины номера |
| okved | tuple[str, ...]; регистрационные коды не доказывают фактическую способность исполнить контракт |
| business_description | str, непустая; описание для поиска/предложения сопоставления |
| supplied_goods / performed_works / provided_services | tuple[str, ...]; хотя бы одна известная непустая группа нужна для полного CompanyProfile |
| geography.all_russia | bool; true не доказывает физическую выполнимость доставки |
| geography.federal_districts / regions / cities | frozenset[str]; точные утверждённые обозначения; неоднозначный город без региона не даёт PASS |
| geography.max_distance_km | конечный Decimal >0; без исходной точки/расчёта расстояния соответствующая проверка UNKNOWN |
| finance.min_contract_amount | конечный Decimal >=0 |
| finance.max_contract_amount | конечный Decimal >0; min <= max |
| finance.min_margin | конечный Decimal в [0,1], доля, не проценты |
| finance.min_expected_profit | конечный Decimal >=0 |
| finance.max_contract_without_extra_approval | конечный Decimal >=0 и <= max_contract_amount; не разрешает внешнее действие |
| finance.max_application_security / max_performance_security | конечный Decimal >=0; величины обеспечения, не расходы |
| finance.price_floor_margin | конечный Decimal в [0,1), <= min_margin |
| enabled_platforms | frozenset[str], ID площадок; KNOWN [] означает нет разрешённых площадок, UNKNOWN означает выбор отсутствует |
| allowed_procedure_methods | frozenset[ProcedureMethod.value]; существующий enum из tenders.py, без произвольных LLM-строк; KNOWN [] не допускает ни одного способа |
| subcontracting_allowed | bool; UNKNOWN не разрешает субподряд |
| prohibitions | tuple[ProfileProhibitionV1, ...]; KNOWN [] — явное отсутствие пользовательских запретов, юридические требования всё равно проверяются отдельно |

ProfileProhibitionV1 переиспользует поля ProhibitionRule: rule_id, kind
(`legal`/`commercial`), condition, rationale, enabled и legal_basis; сохраняет
валидацию уникальности rule_id и legal_basis для LEGAL. Добавляет effective_from
(date), effective_until (date|null), sources (непустой tuple источников).
Период включительный; comparison_policy_version фиксирует timezone для проверки
дат (в первом срезе Europe/Moscow), клиент не меняет его через UTC offset.
LEGAL требует official_document source и контекст применимости. COMMERCIAL
требует подтверждённого решения владельца. Неизвестный/неподдержанный condition
даёт UNKNOWN, не исполняется как код/инструкция. Истёкшее правило не применяется;
это не основание объявлять юридический допуск PASS.

Налоговую политику, лицензии, параметры аванса/отсрочки, чёрные списки и
оборотные средства не изобретаем в generic condition. В v1 их нет; агент
обязательно показывает UNSUPPORTED_FIELD/UNKNOWN для соответствующих проверок.
Добавление структурированных полей требует следующей schema_version.

### Источники и версия

ProfileFieldSource: `provenance: Provenance` (существующий document_id, locator,
extractor, confidence), `kind: manual_declaration | retained_document |
official_document`, `source_sha256: str[64 hex]`, `recorded_at: aware datetime`,
`recorded_by: actor_id`, `source_url: str|null`.
Все источники разрешаются внутри того же company_id; URL без сохранённого
документа и hash не подтверждает факт. Confidence не превращает UNKNOWN в KNOWN.

Ручной ввод — заявление владельца, не независимая проверка реестра. Сервер
создаёт immutable запись команды с actor/time/hash; document_id ссылается на
эту запись, locator — точный путь поля, extractor=manual. У неизменённых полей
сохраняется исходный source. Документы переиспользуют существующее tenant-scoped
хранение; внешнего получения документов этот срез не добавляет. Поля политики
из документа могут стать предложением, но применяются только по точному вводу,
подтверждённому владельцем. Внешний текст не меняет permissions.

Канонизация переиспользует правила case_input_digest/payload_digest: UTF-8,
sort_keys, компактный JSON, Decimal строки, aware ISO datetime, сортировка set,
сохранение порядка tuple. До hash Decimal нормализуется в обычную десятичную
запись, время — UTC; snapshot включает knowledge, reason и источники.
Номер версии/actor/hash не принимаются из свободного JSON клиента.
Сохранение версии, команды, подтверждения, audit и receipt — одна транзакция.
Точный нормализованный ввод и его command_sha256 хранятся в строке версии
рядом со snapshot; отдельная таблица/служба ручных источников не нужна.

Legacy profile из кейса можно предложить как старт формы, сохранив case id,
version и input_sha256. Он не назначается текущим автоматически; поле без
собственного evidence остаётся UNKNOWN до явного ввода/подтверждения.
Адаптер в CompanyProfile разрешён только при наличии всех необходимых известных
значений и успешной существующей валидации; NOT_APPLICABLE переводится в None
для двух optional полей. UNKNOWN нельзя маскировать доменными defaults.

## Передача отдельному агенту сравнения

Агент получает сохранённый снимок целиком, а не текущие поля формы:

```text
CompanyProfileComparisonInputV1:
  schema_version = company-profile-comparison-input-v1
  profile_ref = {company_id, version, snapshot_sha256}
  profile_snapshot: CompanyProfileSnapshotV1
  case_ref = {case_id, version, input_sha256}
  case_snapshot: ProcurementCase
  compared_at: timezone-aware datetime
  comparison_policy_version: str
```

Сервис разрешает обе ссылки на сервере, проверяет tenant, schema/hash и
повторную валидацию. Снимок кейса содержит прежний profile: сравнение с выбранной
новой версией выполняется отдельно, старый кейс не переписывается.
`GET latest` используется при открытии формы; начатое сравнение всегда привязано
к exact version/hash. Смена профиля v1→v2 не меняет сохранённый результат v1.

Выход CompanyProfileComparisonV1: company_id, comparison_id, profile_ref,
case_ref, compared_at, comparison_policy_version, input_sha256, audit_event_id,
checks и overall_status. Каждый check содержит check_id, mandatory: bool,
status: PASS|FAIL|UNKNOWN, reason_code, reason, profile_field_paths,
profile_sources и case_sources (Provenance). KNOWN у реквизита означает только
известное значение, не допуск участника. Итог: mandatory FAIL → FAIL; иначе хотя
бы один обязательный UNKNOWN → UNKNOWN; иначе PASS только в объявленном scope.
Соответствие в процентах в первом срезе вообще не выводится.

Минимальный реализуемый scope сравнения: диапазон суммы контракта на известной
базе EX_VAT/RUB и разрешённый ProcedureMethod. Предикаты детерминированные;
нет доказанной суммы/метода либо их политики → UNKNOWN. Остальные требуемые PRD
проверки перечисляются в результате как UNKNOWN с причиной отсутствующих
данных/предиката; поэтому частичный PASS не объявляется полным соответствием.
В TenderProcedure нет platform_id и суммы обеспечения — из заголовка закупки
их выводить нельзя. Нужен источник на стороне кейса для расширения scope.
Описание деятельности/ОКВЭД допускает лишь A0-предложение соответствия,
не автоматический hard-gate PASS. Профильная география не заменяет проверку
сроков, маршрута и цены доставки.

Агент сравнения A0 предлагает сопоставления и missing facts; окончательные
статусы вычисляет детерминированный сервис. Этот отчёт не выставляет ручной
GateCheck.COMPANY_POLICY, не запускает evaluate_case и не выдаёт PARTICIPATE.
Техническое сравнение товара и ТЗ остаётся отдельным существующим контрактом.
Для будущего применения новой версии в решении нужен новый кейс/assessment:
case_input_digest уже защищает от повторного использования старой оценки.

## Минимальный законченный путь и границы реализации

1. **Создать:** отдельная страница `/company-profile` на существующем Next UI;
   группы реквизитов, деятельности, территории, финансов, площадок/методов,
   субподряда и запретов. Неуказанное явно UNKNOWN; сохранение неполного снимка
   допустимо, это не делает его пригодным для положительного решения.
2. **Сохранить:** POST `/v1/company-profile/versions` с facts,
   expected_version=0 при создании, подтверждением точного command_sha256 и
   Idempotency-Key. Сервер присваивает tenant/version/actor/time, валидирует,
   атомарно сохраняет immutable snapshot+manual source+audit+receipt.
3. **Отредактировать:** GET `/v1/company-profile` возвращает последний снимок;
   GET `/v1/company-profile/versions/{version}` — точную редакцию. Та же форма,
   diff старого/нового ввода и явная кнопка «Подтвердить и сохранить версию».
   POST с expected_version=N создаёт N+1; устаревшая база → 409, обновления нет.
   Подтверждается введённый exact payload; LLM не сохраняет policy сам.
4. **Использовать:** отдельная кнопка сравнения с выбранным сохранённым кейсом;
   POST `/v1/company-profile/comparisons` с profile version/hash и case ref,
   без клиентского verdict. Сервис собирает вход выше, сохраняет immutable
   результат+audit+receipt; GET `/v1/company-profile/comparisons/{id}` открывает
   тот же результат с номером профиля, причинами и источниками.

Для записей существующие idempotency/tenant semantics: тот же ключ+payload
возвращает тот же результат; другой payload →409; чужой/отсутствующий объект →404;
невалидные типы/источники →422. Два новых агрегата `company_profile_versions` и
`company_profile_comparisons` используют существующие PostgreSQL/JSONB,
transaction tenant, FORCE RLS, audit_events и write_receipts. Composite FK
связывают comparison с точными tenant/profile version и case version.
Отдельные БД, profile-service, orchestrator и фоновые jobs не нужны.

В AccessRole нет владельца компании. Перед записями необходим минимальный
`COMPANY_PROFILE_OWNER`, назначенный человеку через существующий bootstrap;
OPERATOR не становится владельцем автоматически. OWNER подтверждает изменения
профиля; OPERATOR может читать и запускать внутреннее сравнение; AUDITOR только
читает. Server Action использует credential текущего пользователя; общий
pilot-token не доказывает личность владельца и не может заменить этот gate.
Внешних действий и отдельного workflow согласования в этом срезе нет.

Контракт команды сохранения: schema_version=`company-profile-save-command-v1`,
expected_version: int>=0, facts: строго типизированный ввод тех же путей,
confirm_policy_sha256: str[64 hex]. Для KNOWN оператор указывает собственное
значение как manual_declaration либо exact document ref (document_id, sha256,
locator); клиент не назначает actor/time/confidence ручного источника.
Сервер сначала разрешает документы/создаёт manual sources, затем валидирует
полный SnapshotV1. Хеш подтверждения считается по нормализованной команде без
confirm_policy_sha256, включает expected_version, знания/значения/причины и
выбранные refs. Diff, сумма и налоговая база видны до клика; изменение любого
значения после подтверждения требует нового клика. Новая версия без изменения
содержимого не создаётся; возвращается текущий снимок с receipt.
Команда сравнения содержит только profile_version, profile_sha256, case_id и
case_version; компания, время, policy_version, снимки и verdict серверные.

### Последовательность и acceptance будущего среза

Владелец CRUD профиля — один implementation agent. Owned files: company DTO и
адаптер рядом с domain/company.py; profile storage/API в отдельных модулях;
миграция двух агрегатов/роль; точечные wiring в access.py, storage models,
API contracts/app/postgres/bootstrap; web `/company-profile` и отдельный lib
клиента; тематические тесты и этот документ. Существующий CompanyProfile и
ProcurementCase остаются совместимыми. Точный список назначается перед кодом.

Зависимая задача сравнения начинается после snapshot API: отдельный агент
владеет comparison-модулем/тестами/UI результата. Общие wiring/миграции остаются
у владельца среза. До handoff агент получает только этот контракт и refs;
пересекающиеся файлы не редактируются параллельно.

Порядок: DTO/источники → сохранение/чтение/RLS → одна форма с edit/diff →
сравнение сохранённого кейса. Готовность только после всего пути, включая:

- Сохранить неполный v1, перезагрузить страницу и получить те же UNKNOWN/source;
  затем изменить финансовый лимит и получить v2 с diff/audit, сохранив v1.
- OWNER/OPERATOR/AUDITOR проверены раздельно; чужой tenant не читается/не пишется
  через API и реальный PostgreSQL runtime role/RLS.
- Retry идемпотентен; конкурентная правка от v1 после сохранения v2 получает 409;
  numeric JSON/float/nonfinite, деньги без базы и известный факт без source не проходят.
- Сравнение v1 и v2 с одним кейсом сохраняет разные exact refs; UNKNOWN не даёт
  допуск, mandatory FAIL не перекрывается рейтингом; новая версия не меняет
  старые assessments/reports. Существующие case tests остаются зелёными.
- Визуально пройден весь путь формы и отчёта; API/реальный PG/wire/build checks
  по затронутым областям. Нет вызовов/изменений ingestion, поиска и задач ЕИС.

## Evidence этой ревизии

2026-10-14: прочитаны указанные модели, API/routes, SQL schema/repository,
UI/actions/types, PRD и роли; выводы относятся к локальному рабочему дереву,
не к установленному серверу. Рабочее дерево содержит ранее накопленные изменения;
в этом срезе меняется только документация профиля.

`uv run pytest -q tests/test_company.py tests/test_cases.py` — PASS (99 тестов).
Выборка существующих case API: `uv run pytest -q tests/test_api.py -k
'health_is_public or missing_and_invalid_bearer or create_rejects_body_tenant_mismatch
or cross_tenant_guessed_path or list_is_scoped_and_duplicate_immutable or
evaluation_uses_authenticated_actor or naive_time_float or latest_evaluation_returns
or latest_evaluation_cross_tenant or auditor_role_is_read_only'` — PASS (10 тестов).
Проверены auth/tenant, immutable version conflict, серверная оценка/audit и
read-only auditor через тестовый service, не real PostgreSQL.
`uv run python scripts/check_docs.py` — PASS: 263 Markdown files, 797 local
links, 14 complete indices; live-план 120 строк.
Новая реализация профиля, real PostgreSQL, browser visual и production
acceptance этим результатом не подтверждены.
