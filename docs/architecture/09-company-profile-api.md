# Реализованный контракт профиля и передача агенту сравнения

Дата: 2026-10-15. Локальный завершённый срез: самостоятельные версии профиля
и immutable выбор exact версии. Сравнение сохранённых кейсов подключено отдельным [срезом](08-selected-procurement-comparison.md); ранжирование отсутствует.
Основа — [принятый контракт](07-company-profile-contract.md); границы уточнены
пользователем: если OWNER отсутствует, блокировать hard policy и завершать
доступную часть. [Запуск/evidence/checkpoint](08-company-profile-implementation.md).

Уточнение на 2026-10-23: описанные ниже права OPERATOR и
`OWNER_AUTHORIZATION_UNAVAILABLE` — установленный старый baseline этого среза.
Локальная owner extension с ролью `COMPANY_PROFILE_OWNER`, exact confirmation и
audit описана в [ADR0115](../adr/0115-company-profile-owner-confirmation.md) и
[операционном remediation-отчёте](../operations/125-spec-remediation.md); она
проверяется отдельно и не объявлена production-installed.

## Отличия фактической реализации от общего проекта 07

- Используются существующие OPERATOR (ручной ввод/выбор) и AUDITOR (чтение).
  Роли OWNER нет и она не добавлена. OPERATOR не получает её полномочий.
- `finance.*`, enabled_platforms, allowed_procedure_methods,
  subcontracting_allowed и prohibitions всегда заблокированы для записи;
  у новых профилей UNKNOWN. Даже запись UNKNOWN в эти paths возвращает 403.
  `critical_settings_status=OWNER_AUTHORIZATION_UNAVAILABLE` не является допуском.
- География — заявленный интерес поиска, не подтверждённый logistics gate.
  Реквизиты/деятельность — manual declaration, не проверка официального реестра.
- Источники первого среза только manual_declaration; загрузка/подтверждение
  retained/official documents и ProfileProhibitionV1 отложены. Источник нельзя
  назначить через body клиента. Нет policy_confirmation: policy не применяется.
- `facts` — строгий по whitelist **плоский объект с dotted paths**, 27 ключей.
  Это transport DTO; типы/ограничения выводятся из полей существующего company.py,
  cross-field правила переиспользуют вложенные модели. Второго домена policy нет.
- Сохранение принимает patch `changes`, а не полный profile; missing keys не
  очищают данные. Сравнение читает exact selections; endpoint описан в срезе сравнения.

## API

Все endpoints `/v1/company-profile` используют bearer → Principal.company_id /
actor_id / AccessRole. Client company_id/actor/version снимка запрещены.
Чужие и отсутствующие версии/selections неразличимы (404).

| Метод и путь | Результат |
|---|---|
| GET `/capabilities` | company_id, actor_id, access_role, can_edit, critical_settings_editable=false, blocked_fields, field_paths, source_kind |
| GET пустого суффикса | последний CompanyProfileSnapshotV1; 404, если профиля нет |
| GET `/versions?before=N` | items: version/created_at/created_by, до 50; next_before или null |
| GET `/versions/{version}` | exact неизменяемый снимок, version integer >=1 |
| POST `/versions` | сохранённый снимок (201); duplicate/no-op возвращает тот же снимок |
| POST `/selections` | сохранённый ProfileSelectionV1 (201) |
| GET `/selection` | последний сохранённый выбор; не переназначается при редактировании |
| GET `/selections/{uuid}` | точный неизменяемый выбор для handoff |

POST требует `Content-Type: application/json`, `Idempotency-Key` (1–200 chars),
body <=65536 bytes. Receipt включает actor: переиспользование ключа другим actor
или с другим нормализованным payload →409. Роль проверяется до записи;
version/command/manual sources/audit/receipt атомарны на existing storage.transaction.

### Команда сохранения

```json
{
  "schema_version": "company-profile-save-command-v1",
  "expected_version": 0,
  "changes": {
    "identity.name": {"knowledge": "KNOWN", "value": "ООО Синтетический пример", "reason": null},
    "provided_services": {"knowledge": "KNOWN", "value": [], "reason": null},
    "geography.all_russia": {"knowledge": "KNOWN", "value": false, "reason": null}
  }
}
```

expected_version — строгий int>=0: 0 для первого сохранения, N для edit N→N+1.
Bool не принимается как int. Два edit от N сериализуются lock tenant/head: один
сохраняется, второй получает409. Пустой changes разрешён при создании. Если
нормализованные facts не изменились, версия/audit сохранения не добавляются.
Source неизменённых полей сохраняется. Исходная команда хранится рядом со
снимком; digest включает нормализованные changes и expected_version.

Каждый вход: knowledge (`KNOWN|UNKNOWN|NOT_APPLICABLE`), value, reason.
KNOWN требует non-null value и null reason. UNKNOWN — null и непустую reason
(форма ставит NOT_PROVIDED). NOT_APPLICABLE — null/reason, только identity.kpp
или geography.max_distance_km; сервер создаёт source заявления.
Никакие supplied sources/roles/tenant/time из клиента не принимаются.

| Paths | Тип KNOWN value в JSON |
|---|---|
| identity.name/inn/kpp/ogrn/legal_form, business_description | непустая string; реквизиты проверяются по исходным regex, не по официальному реестру |
| okved, supplied_goods, performed_works, provided_services | array[string]; [] только явное подтверждение пустого списка |
| geography.all_russia | boolean; false не равно UNKNOWN |
| geography.federal_districts/regions/cities | array[string], нормализуется как sorted unique set; город должен иметь понятный контекст региона для будущего сравнения |
| geography.max_distance_km | конечная десятичная string, >0; каноническая единица km |
| finance.* | Decimal string с исходными границами FinancialPolicy; запись блокируется403 до появления доверенной owner-авторизации |
| enabled_platforms, allowed_procedure_methods | array[string]; запись заблокирована |
| subcontracting_allowed | boolean; запись заблокирована |
| prohibitions | UNKNOWN; известные структурированные правила в этом срезе не поддержаны |

Неполнота сохраняется; отсутствие не превращается в доменные defaults. Если
вся география известна и all_russia=false при трёх явно пустых scopes,
сохранение отклоняется422. Известные числа не заменяются на float:
деньги используют существующий finite Decimal validator, расстояние тоже
конечный Decimal; JSON number, bool вместо числа, NaN/Infinity отвергаются.
Форма понимает десятичную запятую и отправляет string с точкой.
Decimal нормализуется (`100.50`→`100.5`, `0.00`→`0`), значение не теряет точность.

### Снимок

CompanyProfileSnapshotV1: schema_version=`company-profile-snapshot-v1`,
company_id:str, version:int>=1, parent_version:int|null, created_at/effective_at:
aware ISO8601 UTC, created_by:str, currency=`RUB`, amount_basis=`EX_VAT`,
facts:dict[dotted path, ProfileFact], critical_settings_status,
snapshot_sha256:64 lowercase hex, audit_event_id:str. effective_at=created_at.

ProfileFact: knowledge, value, reason, sources (array). KNOWN требует источник;
UNKNOWN — null/reason; false, [] и известный "0" не означают неизвестность.
ProfileFieldSource: company_id, kind=`manual_declaration`, source_sha256,
recorded_at:aware datetime, recorded_by, source_url=null,
provenance: existing Provenance(document_id, locator, extractor=`manual`, confidence=1).
document_id=`profile-command:{sha256}`, locator=точный dotted path. SHA ссылается
на команду в той же tenant-scoped строке версии; чтение сверяет hash, payload,
значение поля, actor и время источника. Confidence относится к ручной записи,
не подтверждает юридическую истинность заявления.

Hash использует существующий payload_digest над каноническим JSON снимка без
snapshot_sha256: UTF-8/sort_keys/compact JSON, Decimal strings, UTC `Z`,
sorted sets; tuple order сохраняется. Редактирование standalone profile не
трогает ProcurementCase, его вложенный profile, input_digest или assessment.

### Выбор версии и handoff

POST `/selections` принимает только `{version:int>=1, snapshot_sha256:str64}`.
Сервис загружает exact версию своего tenant и сверяет digest. ProfileSelectionV1:
schema_version=`company-profile-selection-v1`, company_id, selection_id:UUID,
profile_ref={company_id,version,snapshot_sha256}, selected_at:aware UTC datetime,
selected_by, audit_event_id. FK включает tenant/version/hash.

Агент сравнения читает exact selection по ID, затем exact snapshot по version;
сверяет company_id/hash/schema. **Latest не является ссылкой начатого сравнения.**
Выбор остаётся v1 после появления v2; старые выборы доступны по ID.
Неизвестные/заблокированные policy facts не дают PASS.

Web endpoint GET `/company-profile/export?selection={uuid}` требует ту же
персональную сессию и скачивает JSON:
`{schema_version:"company-profile-handoff-v1", selection, profile_ref, profile_snapshot}`.
UI не показывает технические hashes/receipts. Сервер и агент читают их в JSON.
Отчётов comparison, оценок, ranking и изменений кейса при выборе не создаётся.

Синтетические fixtures (не клиентские данные и не доказательство допусков):
[unknown](../../tests/fixtures/company_profile/unknown.json),
[supplier partial](../../tests/fixtures/company_profile/supplier-partial.json),
[явные empty/false](../../tests/fixtures/company_profile/explicit-empty-and-false.json).
Для каждого лежит соседний `.command.json` с воспроизводимым вводом.
Эти fixtures не зарегистрированы в БД; manual source/selection внутри примера
синтетические. Финансовая policy в них остаётся UNKNOWN.

## Ошибки и права

401 — нет/невалиден bearer;403 — неподходящая роль или critical_settings_locked;
404 — версия/selection отсутствует или принадлежит другому tenant;
409 — устаревшая база, payload/actor conflict, неправильный SHA, повреждённое
stored evidence;413 — размер;415 — content type;422 — схема/значения;
503 — storage не настроен.422 может содержать detail={code,fields} с paths
для понятной ошибки формы; исходные значения в errors не возвращаются.

Сессия формы проверяет bearer существующим PostgresAuthenticator и сохраняет
его в HttpOnly/SameSite=Strict cookie path `/`, на час; login/logout очищают legacy cookie path `/company-profile`.
Одна персональная сессия используется профилем и сравнением;
Secure в production. Общий PROCUREMENT_API_TOKEN не используется как личность.
Production IAM/owner provisioning остаются отдельной задачей; синтетические
локальные ключи и postgres-owner не являются готовой production-авторизацией.

Миграция `20261014_01` создаёт company_profile_versions/company_profile_selections
на существующей schema: FORCE RLS, SELECT/INSERT grants runtime role,
immutable mutation trigger, composite FK на источники версий и audit.
Downgrade отказывается уничтожить непустую историю.
Таблицы регистрируются отдельным company_profile_schema на общей metadata;
Alembic env импортирует её явно. Core storage/models.py и закреплённые исходники
ЕИС сохранены byte-for-byte: profile wiring их не меняет.
