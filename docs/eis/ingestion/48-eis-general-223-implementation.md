# S169: последовательный rollout purchaseNotice

Статус: **DEPLOYED, 2026-10-03**. Итоговые measurements и fingerprints ниже
переданы root; Astra не выполнял независимый повтор live intake.

Дата: 2026-10-03. Владелец этого плана и ADR-0052: Astra. Owned files:
только docs/48 и docs/adr/0052. Root владеет общим docs/15 и production rollout;
Sol — bounded parser milestone по назначению root. Этот документ не меняет
ownership кода. Зависимости: docs/47, ADR-0050/0051/0052 и текущий S168.

## M1 — контракт и parser

Решение принято в [ADR-0052](../../adr/0052-general-223-metadata.md): metadata
admission нового explicit family с independent full-XSD quality. Полный
returned archive set сохраняется атомарно; known schema FAIL не вырезается.
Старый S152 rejection остаётся immutable. Нового live ingestion на M1 нет.

Acceptance parser:

- Exact purchaseNotice root/Data/namespace; missing/duplicate identity,
  unsafe XML, invalid version и resource overflow отклоняются.
- Optional lotData сохраняет UNKNOWN; source ordinal/GUID не заменяются
  array index. Multi-lot identity сохраняется.
- initialSum/maxContractPrice/text branches различимы, с exact provenance;
  max/formula не создают initial_sum_rub. Currency disagreement UNKNOWN.
- Naive deadline UNKNOWN; lotOriented и public/status flags явны.
- FS/previous/additional/notPlacement manifest не выдаётся полным;
  unsupported/hidden references не получают готовый download URL.
- Все прежние family fixtures читаются совместимо, persisted старые snapshots
  не приобретают придуманных source facts.
- Offline cached sample: ровно все 25 XML versions/25 лотов, 20 initialSum и
  5 maxContractPrice, исходные hashes неизменны; full-XSD отдельно 24 PASS/1 FAIL
  в каждой pinned release. Эти цифры — expectation сохранённого sample docs/47,
  не новый production result.

## M2 — SQL guards и consumers

Root последовательно расширяет explicit-family regex/model/window identity
constraints и migration. Не выполнять rollout partial schema, при котором
reader допускает запись, а snapshot/window guard трактует другую family.
Downgrade с новой историей fail closed, upgrade сохраняет прежние rows/hashes.
Проверить tenant/version/replay/conflict и атомарный отказ полного окна.

Consumers должны показать source price kind и source amount; unsupported
ветка остаётся в discovery без ложной initialSum/выручки. Search не смешивает
разные лоты и currencies. Comparison/positions используют source ordinal,
а API lot_index остаётся явным индексом выбора существующего лота.

Особый проверенный gap: source XSD FAIL в текущем comparison — warning,
не blocker; estimate наследует document blockers и не имеет отдельного
schema-status поля. При rollout требуется видимость этого warning в estimate
контексте/результате. Нет требования превращать XSD FAIL в supplier FAIL.
Max/formula estimates UNKNOWN; stale/expired/cancel/hidden/invalid source
ограничения не обходятся новым price model. Общий deadline при lotOriented
не выдаётся за проверенный lot deadline.

Manifest consumers получают explicit UNKNOWN для unresolved branches;
notPlacement=true не скачивается даже при внешне допустимом official URL.
При любом incompatible contract вместо guessed URL/empty COMPLETE — UNKNOWN.
Обычный read API cached only, no jobs/audit/network/parse.

## M3 — ограниченный новый source window

Только после M1/M2 gates root выполняет один разрешённый явный RI223 window
в установленном scope под общим lock/quotas/resource bounds. Получить все
returned archives, сохранить exact initial/prepared/source SHA и dataset
counts; не обходить bounds дроблением/пропуском failed members. Ошибка typed
metadata отвергает окно атомарно; XSD FAIL отражается отдельным quality evidence.

Replay проверяет отсутствие дублей и лишнего audit. Saved schema checks
привязаны к exact number/version/XMLSHA. UI/API должны показывать новое family,
max price kind, naive deadline UNKNOWN, quality warnings и manifest gaps.
Production writes и proof выполняет root; Astra в этой задаче их не делает.

## Что не считается завершением цели

Новая family не означает все 223-ФЗ или доступность любой процедуры поставщику.
SYNCED не означает XSD PASS и не подтверждает current open submission.
Новые XML/цены не дают прибыли без действительного КП, reviewed ТЗ, налоговой
модели, полной стоимости и base/realistic/conservative. Позднейшие отмены и
lot schedules требуют самостоятельного контракта/evidence.

## M1 независимый review текущего parser

Read-only review Astra обнаружил следующие issues до M2 admission; проверка
выполнена локально на synthetic `general_xml` без source requests/DB writes.

- **Цена:** initialSum 100.25 + присутствующий commodityPrice `-1` возвращает
  initial_sum_rub 100.25: parsed commodity value становится None, и проверка
  ошибочно считает ветку отсутствующей. Нужен gate по присутствию ветки или
  raw/evidence, включая пустое/invalid значение; unsupported не активирует
  economics. Аналогичную distinction сохранить для пустого priceFormula.
- **Manifest:** prevDocument без FS или additionalDocumentsCount=1 оставляют
  COUNT_CONSISTENT, если число обычных document совпадает с total. Unresolved
  branches должны давать UNKNOWN согласно ADR0052, независимо от равенства
  счётчика. M2 download consumer не должен принимать такое поле за READY.
- **Валюта:** неизвестный code XYZ без digitalCode получает CONSISTENT из
  сравнения `dict.get(code) == None`. Нужна проверка принадлежности mapping
  перед сравнением; observed initial_sum_rub остаётся None, но status ложен.
- **Совместимость моделей:** новые поля optional для legacy snapshots;
  generic purchaseNotice не должен использовать этот compatibility fallback
  для отсутствующего price/deadline/manifest contract. M2 model/SQL guards
  должны отличать generic обязательные extension fields от старых families.

Также проверить retention `hidePurchaseCustomerAccredited`/`forSmallOrMiddle`
из docs47: текущее расширение хранит только hidePurchase. Их отсутствие
не позволяет делать вывод о свободном участии; конкретную semantics ограничения
не выводить из имени XML поля. Пока только UNKNOWN/source flag, без legal PASS.

Положительные результаты review: root/Data namespaces и direct business paths
проверяются fail closed; optional lotData, отдельные max/text amount/locator,
FS/previous references, selected_deadline UNKNOWN для lotOriented и полный
atomic archive traversal присутствуют. Новые network types пока отделены
от parsable types; до M2 это полезный admission gate.

## M2 независимый review перед staging/deploy

Повторно прочитаны final parser/model, новая `eis_223_policy.py`, index/sync/
documents/comparison/source estimate, migration20261003_01, generic consumer/PG
tests и UI helpers/estimate. Прежние M1 findings исправлены: explicit presence
flags блокируют formula/commodity даже при invalid amount; unresolved manifest
не становится COUNT_CONSISTENT; unknown code не CONSISTENT; generic extensions
обязательны на model validation, legacy defaults остаются старым families.

Shared unavailable policy переносит confirmed hidden/accredited/status I в
search availability FAIL и document/estimate blockers. Это source availability,
не утверждение о юридической отмене или supplier hard gate. Выбранный deadline
для lotOriented остаётся UNKNOWN; consumers не используют общий deadline как
срок конкретного лота. Max/formula не получают ceiling_rub. Schema FAIL отдельно
переносится в estimate status/reasons и показывается UI; manual preliminary
initialSum calculation не превращается в PARTICIPATE.

Migration меняет три explicit-family check constraints, не перезаписывает
snapshot/raw history, FK/immutability/RLS остаются. Guard downgrade проверяет
новую family в windows/versions/attempts при row_security=off. SQL сохраняет
identity/family binding, подробный generic shape дополнительно защищён model
validation. Refresh строит шесть family/date targets с oldest-observed ordering;
batch2 и budgets не расширены. Комментарий «four targets» в due selector устарел,
но не влияет на поведение.

Блокирующих замечаний в прочитанной финальной реализации не найдено. Root
выполняет итоговые test/migration gates и последующий bounded live proof.
Этот review не заявляет успешный deploy, новый SYNCED window или source XSD PASS.

## Итог rollout: evidence root

Проверки завершены: 66 isolated PG и 397 Linux focused tests, Ruff/mypy девяти
файлов, ESLint/build/TypeScript и M2 review. API/web healthy, migration HEAD
20261003_01; временная test DB удалена, marker снят. Штатный cron продолжил
регион50/три families с прежними cadence, batch2 и budgets.

Новое окно **region50/2026-10-02/purchaseNotice**: весь возвращённый набор из
одного ZIP, 40 XML versions и 38 уникальных номеров атомарно принят. Цены:
38 INITIAL_SUM и 2 MAX_CONTRACT_PRICE; подтверждённых aware selected deadlines
нет. Независимая full-XSD проверка: 38 PASS/2 FAIL на каждой release16.2/16.3,
всего 80 quality observations. SYNCED относится к полному metadata ingestion,
а не к XSD PASS всех records или открытой подаче.

Первый getDocsIP+ingest успешно завершился в 09:42:41Z; после commit helper
proof упал с AttributeError при unpacking preflight. Recovery проверил уже
сохранённый immutable response
`a94d61d94c9192536caabc09a15828f00ad345baf0dc42fd3a352f7f302b1be7`
без нового source request/journal writes. Replay не добавил ingestion writes.
Старые S152 artifacts/rejection не переписывались.

API проверка карточки `32615966906`, v15: максимальная цена договора 6 млн
показана отдельно; estimate UNKNOWN. Read comparison не мутирует данные.
Точный запрос «металлоконструкций» вернул одно совпадение примерно за39мс —
один API sample, не SLA/recall benchmark. Browser verification root подтвердил
новую generic карточку и source/family/price labels.

Для той же карточки получен один public ТЗ DOCX из восьми перечисленных файлов:
32 native snippets, extraction UNKNOWN и requirements UNKNOWN. Это проверка
работоспособности document path, не полный комплект и не reviewed ТЗ.

Все proof files retained на VPS; файлы/корпус не переносились в ownership Astra:

| Proof file | SHA-256 |
|---|---|
| `s169-retained-proof-20261003T094121Z.json` — 25 retained members,24/1 quality | `df472ad7c995f58b6af72262fb5f6e7d88de191396c8b861451788e3d49866ff` |
| `s169-live-proof-20261003T094418Z.json` — новый source window/recovery/replay | `ba5358821f7c19746ef4d78d1f0137e7ea27a8e807d3eea308553f06c5d47875` |
| `s169-api-proof-20261003T094541Z.json` — search/comparison/estimate | `a7878b69ec79fa5fb22b1fac446fae8d551ca35f8ca0d8e9d8d3701dd24df0f9` |
| `s169-document-proof-20261003T094741Z.json` — один public DOCX | `ea4cf1308dcc257cced77895da44e2542bab37ea2ba7398e232272d303328313` |

Full ЕИС coverage, действительность подачи без aware lot deadline, полнота
ТЗ, supplier quote и прибыль остаются UNKNOWN. Эти gates сохраняются после
DEPLOYED и не закрываются количеством новых XML.
