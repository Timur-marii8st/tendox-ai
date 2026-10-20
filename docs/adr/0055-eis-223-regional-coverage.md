# ADR-0055 — автоматический региональный scope223 и честный backlog

Статус: **ACCEPTED / DEPLOYED**, S172,2026-10-03, HEAD `20261003_04`.
Owner:Astra; runtime owner:root, source adapters:Sol. Official catalog contract
подтверждён в пределах docs54 PUBLIC_KLADR_SELECTOR. Effective date:2026-10-03.

M2 evidence: получен официальный `PUBLIC_KLADR_SELECTOR`,90уникальных top-level
ID, не `NSI_ACTUAL_VERIFIED`. Exact11charID имеет two-digit prefix и9нулей;
mapping к orgRegion — structural inference, не отдельное поле HTML.
Body22514bytes, SHA `b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`.
Scope принят для измеримого плана90×5×2=900targets после parser/review gates;
actual=true подтверждено отдельным lookup только для50, не остальных89.
NSI get-all NO_DATA не заменяет этот каталог и не доказывает пустой scope.
Raw HTML/URL/bodySHA сохраняются; parser должен требовать observed unique
container chain и закрытый полный list, не принимать EOF между закрытыми li.

## Контекст и ограничение производительности

Один parameterized loader должен автоматически обслуживать весь подтверждённый
каталог orgRegion. Отдельные milestones77/78 не являются архитектурой охвата.
Регион выгрузки не равен месту поставки и не ограничивает поиск пользователя.

Исторический pilot при2окнах/30мин имеет потолок96attempts/day. Если каталог имеет99codes,
то99×5families×2dates=990targets: нижняя граница полного прохода10.31суток без
ошибок, ожиданий и contention. Это пример расчёта, не подтверждённый размер
каталога и не measured throughput. Добавление полного такого набора ежедневно
даёт неустойчивую очередь. Пересоздание только today/previous-day scope теряет
непосещённые окна в полночь и скрывает отсутствие прогресса.

Root выбрал S172 budget после bounded77/78 validation: до32окон/600s на
существующем cron11/41, sequential browser reuse без fanout. Теоретический
потолок1536attempts/day; он не measured throughput и не SLA. Source polling,
общий44/223 import lease, quality и resource gates могут существенно снизить
actual capacity. Порог запуска нового окна проверяется до source request;
in-flight bounded overrun учитывается отдельно, atomic returned set не режется.

## Принятое решение

1. Сохранить official catalog snapshot с source/version/hash/as-of и точными
   codes/statuses. Не генерировать range01..99. Исторические/неактивные codes
   включаются или явно исключаются только по проверенному source contract;
   исходный каталог и причина scope choice остаются видимыми.
2. Создать bounded finite wave: фиксированные catalog hash, пять семейств
   (purchaseNoticeAESMBO, purchaseNoticeZKESMBO, purchaseNotice,
   purchaseRejection, purchaseLotCancellation) и exact source dates.
3. Persist unique tenant/wave/region/family/day targets один раз. Полночь,
   restart и изменение каталога не удаляют и не переносят эти targets.
4. Очередь сначала обеспечивает справедливый первый проход, затем bounded
   retry lane с cooldown. Stable tie-break по region/family/day/target key;
   один failed target не вытесняет непосещённые регионы. При достаточно долгой
   работе due retry не должен голодать. Claim/attempt фиксируются под общим
   import lock либо эквивалентной lease-защитой, исключающей double dispatch.
5. Новый wave имеет changed date pair и минимум24h cadence. Sweep завершение
   следует отличать от полного source coverage: permanent failure одного target
   не должен бессрочно блокировать национальную свежесть. Предлагается после
   первого полного прохода retain unresolved targets в retry backlog, разрешая
   новый wave с явным incomplete previous scope и bounded retry reserve.
   Runtime использует first-sweep advancement, retained old gaps и первый retry
   slot в batch2..32; catch-up advances не более2source days.
   Нельзя называть незавершённый wave coverage complete или удалять его gaps.

Рекомендуемый первый срез — finite waves с честным lag. Если root выбирает
rolling lanes вместо frozen waves, необходимо зафиксировать явные unscheduled
date gaps и правило обслуживания каждой region/family lane; пропущенные даты
не превращаются в covered. Capacity uplift — отдельный измеримый срез.

## Tenant, evidence и coverage

Catalog evidence может быть общим immutable source resource; tenant plan,
targets, attempts, source receipts и audit tenant-scoped с FORCE RLS/FK.
Exact source key включает region/family/day. Business notice identity остаётся
number/version/XMLSHA и не размножается из-за другого region; новый региональный
receipt связывается с теми же bytes/notice. Conflict versions не переписываются.

SYNCED требует полного returned set и exact committed checkpoint. NO_DATA
подтверждает только ответ для конкретного окна в observed_at. PREPARING,
FAILED, SERVICE_ERROR, never-attempted и deferred различаются. Coverage payload
показывает catalog hash, planned scope, attempted/positive/no-data/failed/pending,
oldest due/lag и source observation times. Заполненность источника, все закупки
ЕИС и будущие изменения окна остаются UNKNOWN. Read-only coverage API не seeding
queue и не source fetch; ranking не снимает existing cancellation gates.

## Migration boundary

Новая migration использует literal old/new CHECK SQL, не выводит historical
contract из живых models. Историческая20261003_01 импортирует live models и
использует string replace при downgrade — это обнаруженный риск drift.
Widened regions должны проверяться во всех notice/whole-event/lot-event windows
и attempt contracts. Downgrade запрещён при non50 source history/новых plan
receipts в любом tenant; RLS не должен скрывать этот history guard. Если допустим
пустой downgrade, он восстанавливает точный прежний region50-only contract.

## Acceptance

Official catalog proof; overnight/restart no-loss; fair first/retry pass;
source failure stays visible; same number across regions deduplicates; exact
checkpoint FK/tenant isolation; coverage GET no mutations; old/new migration
paths; budget32windows/600s после validation,32MiB compressed/window,
DB100GiB/free40GiB gates и существующие resource locks сохраняются.
Контрольная77/78 выборка проверяет общий loader, не заявляет полный каталог.

План: [S172 implementation](../eis/ingestion/55-eis-223-regional-implementation.md).

## Deployment evidence и оставшийся scope

Root подтвердил api/worker/web deployment HEAD20261003_04,90PG+484Linux+
latest16tests и webbuildPASS. Admission proof:
`/research/regions/s172-admission-20261003T174923Z.json` — catalog90,
frozen Oct2–3 plan900,77/78 controls122newversions, replay0writes/no extra
source calls. First national run начат; полный900target sweep и measured sustained
throughput пока не завершены. Catalog refresh пока bootstrap-only; bounded
retention,44regional parity, прочие223families и stable lot association остаются
отдельными gaps. Whole coverage/freshness UNKNOWN.
