# ADR-0057 — согласованная передача source lease между44 и223

Статус: **ACCEPTED / DEPLOYED**, S174. Дата:2026-10-03.
Owner ADR:Astra; runtime/scripts/tests:root. HEAD остаётся `20261003_05`,
новой migration нет; api/worker rebuilt, API health200 подтверждён root.

## Причина

223cron каждые10min терял запуски при45s ожидании общего import lease;44corpus
может держать lease до60окон. Увеличенная частота223 также может задерживать
44freshness/documents. Нужны явные demand hints и уступка между atomic windows,
без параллельных запросов и без прерывания полного returned archive set.

## Контракт

-223 сначала берёт отдельный dispatch lock неблокирующе. Дубликат выходит без
  изменения marker. Только владелец dispatch создаёт/удаляет свой demand marker.
-223 не берёт44priority lock.44не берёт223dispatch. Каждый ожидает только общий
  import lock после собственного lane lock; циклического ожидания нет.
- Corpus проверяет44priority и223demand markers между atomic windows. Marker —
  operational hint с возрастом0..600s; stale/future timestamps не создают demand.
-223 ждёт import до300s. После получения выполняет не более одного нового
  bounded atomic window перед обязательной проверкой44priority. Затем уступает
  при актуальном marker, сохраняя backlog и пропуская offline quality.
-44documents import wait увеличивается45→300s, как freshness. Существующий
  document dispatch lock исключает накопление однотипных waiters. Иначе
  guaranteed one223window с source timeout180s мог пережить45s ожидания44doc.
- Source caps32windows/600sstart/180ssourcewindow и ресурсные guards не меняются.
  Возможный45s catalog check, commit/cleanup означают, что300swait не является
  строгой wall-clock гарантией handoff. TTL/timeout/skip видны в отчёте.

Перед объявлением demand нужна read-only проверка наличия работы и proxy;
catalog revalidation/создание due wave считаются отдельной реальной работой.
Под import lease работа проверяется повторно. Idle cron не должен останавливать
corpus через marker — ранее устранённый S166 риск сохраняет силу.

Marker cleanup выполняется на нормальном exit/ошибке/INT/TERM и не удаляет чужой
marker. Dispatch ownership сохраняется до cleanup. Прерывание wrapper не должно
отпускать import lease, пока его source worker продолжает работу. Проверка
markers не обращается к ЕИС, не меняет source receipts и не означает coverage.

## Fairness и acceptance

Два waiters могут получить lease в любом порядке: flock не обещает FIFO.
223получает bounded progress после acquisition, затем отдаёт при44demand;
corpus уступает обоим. Это cooperative fairness, не strict zero-starvation SLA.

Проверки: duplicate dispatch не трогает marker; idle не создаёт marker; timeout/
normal/error cleanup; stale/future hints; corpus не начинает второе окно после
demand;223не прерывает первое atomic window, не начинает второе/quality после
44demand; document wait300; source counters/atomic receipts сохранены. На VPS
наблюдаются lock wait/skips/attempts/handoff и влияние на обе полосы. Runtime
review и deployment proof приведены ниже.

## Read-only review реализации

Прочитаны223wrapper/probe/runner, corpus markers и44document wait300.
Отдельные lane locks не создают циклического ожидания;223trap установлен до
marker touch, background flock waiter reaped на signal/exit; corpus проверяет
оба hints между окнами. Source budgets и atomic windows сохранены.

Замечания первого review, исправления перечитаны:

1. Probe передавал limit1 при scheduler contract2..32: реальный cron всегда
   получал REGIONAL_BATCH_INVALID. Исправлено на допустимый limit2.
2. Coverage без wave не возвращает catalogSHA. Недавно принятый catalog без
   первой wave ошибочно выглядел IDLE до24h; bootstrap readiness должен отдельно
   читать наличие accepted catalog. Добавлен exact _accepted_catalog read в
   tenant consistent-read transaction при отсутствующем coverage catalogSHA.
3. Проверка marker только перед следующей итерацией не пропускает quality,
   если44demand появился в последнем selected window либо после catalog-only
   work. optional_quality теперь проверяет marker в empty/final paths.

Открытых code blockers после повторного review нет. Root подтвердил76Linux
focusedPASS за4.75s, включая8реальных flock/signal tests; bash-n3PASS,
Ruff/mypy2PASS. Read-only actual PG probe20:25:41UTC:READY,due2,source0;
deployment proof `state/s174-live-probe.json`.

## Live handoff evidence

`state/s174-handoff-canary.json`: под принадлежащим deploy priority marker
223полностью завершил окно region39/2026-10-02/ZKESMBO — SYNCED,
4newversions,2POST/1GET,18.088s. ЗатемPRIORITY_REFRESH_REQUESTED и
DEFERRED_FOR_PRIORITY: следующее source window/optional quality не запускались.
Marker удалён trap; failed source observations не было. Это проверяет bounded
progress и передачу lease после atomic window, не полный regional sweep.

Независимый wrapper run `state/s174-first-dispatch.json` ещё выполнялся на
момент передачи evidence root; его итог не приписывается canary. Full900sweep,
устойчивая6h freshness и строгая fairness SLA не доказаны. Whole coverage/
freshness остаются UNKNOWN; последующие operational результаты ведёт root.

## Дополнение26Oct2026

[ADR120](0120-eis-freshness-priority-wait.md) уточняет fresh priority handoff:
один fresh dispatch waiter вместо потери tick при document priority ownership.
Document/import300s и прежние source/lease guards сохраняются; статус V51 в ADR120.
