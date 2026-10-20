# ADR-0032: независимый review и operator binding exact requirement set

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

S81 создал immutable proposal, terminal reviewer decision и case binding, а S82
добавил безопасную server-derived материализацию строк DOCX. Эти операции были
доступны через API, но у reviewer не было экрана для просмотра всех строк и
явного решения, а operator не мог привязать выбранный `PASS` к версии кейса без
ручного HTTP-запроса. Объединение двух ролей в одной форме нарушило бы
независимость проверки.

## Решение

Добавить два маршрута без list/latest selection:

- `/requirement-set-review?set_id=…` использует отдельный server-only
  `PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN`. Он показывает все строки,
  provenance, typed requirement или `MANUAL_REVIEW_REQUIRED`, exact proposal
  digest и сохранённое terminal decision. Ни один assessment или статус не
  выбран заранее. Server action повторно читает proposal и сверяет digest перед
  отправкой решения;
- `/requirement-set-binding?set_id=…` использует operator
  `PROCUREMENT_API_TOKEN`. Он разрешает ввод exact `case_id + version` только при
  persisted terminal `PASS`, показывает proposal/decision digests и повторно
  загружает set перед созданием binding.

Reviewer route разворачивается как отдельная внутренняя поверхность. Dedicated
reviewer token не имеет fallback на operator token и не попадает в HTML или
browser JavaScript. Operator action не принимает reviewer decision. API остаётся
authority для разделения preparer/reviewer/binder, существования case version,
immutability и идемпотентности.

## Последствия

`PASS` подтверждает coverage и normalization exact proposal. Он не закрывает
manual entries, не доказывает соответствие найденной карточки и не создаёт
полного BOM или КП. После binding sourcing может исполнять только typed часть и
сохраняет общий technical status `UNKNOWN` до проверки exact конфигурации.

Новая схема БД и API endpoint не нужны: UI использует контракты S81. Production
доступ по-прежнему требует session auth/RBAC/MFA; локальный пилот сохраняет
разделённые deployments и server-only credentials.
