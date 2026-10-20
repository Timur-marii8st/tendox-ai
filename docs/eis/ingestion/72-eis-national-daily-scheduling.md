# S189 — ежедневные пять типов процедур и защита старой очереди

Статус: DEPLOYED AND VERIFIED / BOUNDED DAILY5; independent review PASS.
Дата: 04.10.2026.
Контракт: [ADR0070](../../adr/0070-eis-national-daily-scheduling.md).

## Решение и основания

Ежедневный план охватывает завершённые даты по candidate codes 01–99 и пяти
поддерживаемым типам: EF, EZK, EOK, отмена и отмена несостоявшейся процедуры.
Коды не являются проверенным реестром регионов. Почасовой приоритетный поток
сохраняет фактические регионы 50/77/78. Полнота ЕИС и срок завершения всей страны
остаются UNKNOWN.

Read-only snapshot 19:42:50 UTC: 1485 ожидаемых ключей за 1–3 октября,
1197 запланированных и 288 отсутствующих EOK (96 на каждую дату).
Девять существующих EOK: семь canonical и два NO_DATA. Все пять families:
516 canonical, 680 NO_DATA, один FAILED, 288 unplanned.
Source requests и DB writes: 0; длительность census 13.635 s.

Старый selector выбрал 60 исторических окон за 6 сентября за 8.447 s.
Отдельная симуляция только ordinary NULL-attempt order с отсутствующими EOK
поставила новые EOK на все первые 60 мест. Это не полный selector и не
persisted очередь; результат обосновывает защиту настоящего старого backlog.

## Производительность и ограничения

План добавляет до 495 ключей за новую дату, включая 99 EOK. Национальное
почасовое расписание потребовало бы 495 новых ключей в час до повторов.
Потолок priority — 288 окон/ч; corpus — отдельно 240 окон/ч. Они используют
общую import lease, поэтому их производительность нельзя складывать.
Corpus ограничен 60 окнами за проход; у `run_corpus` нет 240 s wall-time cap.
Yield перед следующей транзакцией, source failures и resource guards сохраняются.

Последние 24 h: corpus 2120 attempts (1717 historical, 403 recent), freshness
1095 attempts; 959 первых canonical ключей по всем actors. p95 6994.542 ms
получен из 1095 валидных metrics трёх регионов; 61 metric отсутствует.
Это не национальная скорость и не ETA.

Timestamped 223 log sample за 22.85 h: 137 lease work observations, 14441 s
работы, около 17.6% наблюдаемого периода; 138 waits, 661 s, max 300 s.
Логи corpus/priority/documents без timestamps не дают сопоставимого rate.
Совместная пропускная способность и суточный SLA пока UNKNOWN.

## Проверки и rollout

PG gates, staged selector/EXPLAIN, независимый predeploy review, идемпотентное
планирование, backup/hash rollout и live pass подтверждены.
Исторические attempts и pending keys не удаляются;
NO_DATA и partial/HOLD не считаются canonical completion. Source guards,
schema HEAD, cron cadence и CPU/memory/disk budgets сохраняются.

## M2: фактические результаты до выкладки

35 tests на изолированной PostgreSQL: 14 integration и 21 unit, PASS;
Ruff/mypy PASS. Старую fixture с July/Aug backlog исправили, сохранив все
assertions: прежние Sep26–28 попадали в новый recent диапазон.

Synthetic overlay и затем настоящий normal fill выявили плохой nested-loop
plan с cardinality estimate 1–3 вместо большого pending cohort; statement
превышал 60 s. Проверка остановила rollout. В fairness helper исключения
canonical/retry стали некоррелированными, non-null и tenant-scoped; latest attempt
читается индексным LEFT LATERAL LIMIT1. Прежний fallback SQL не менялся.

До rollout добавлены ровно 288 внутренних EOK targets; предварительно проверены
completed-date scope и EOK-only/297 bound. Повтор добавил 0, все новые ключи
связаны с planning audits. Scope 1485/1485; targets 148273→148561. Source calls 0.

Окончательный staged runtime проверен на настоящей таблице в tenant READ ONLY
RR snapshot `55358:55358:`, 20:13:44 UTC. Limit3 — 8.592 s: первый historical
81/06.09/CancelFailure, второй новый 01/03.10/EOK, третий failed77/29.09/EZK.
Limit60 — 19.406 s: 35 historical, 24 new EOK, один recent FAILED; 60 unique.
Восемь bounded SELECTs для двух запусков, EXPLAIN plans сохранены. Source0/writes0
для SELECT proof; bootstrap был отдельной внутренней mutation.
Это единичные наблюдения, не SLA и не ускорение относительно прежнего селектора
на другой очереди. Полная производительность общей загрузки остаётся UNKNOWN.

Final runtime SHA256:
`f94333368b80761494abc6edd95464f9c3de0c1020289c57d888347ae0072ca0`.
Daily script SHA256:
`c86f5baa418068d3253d6fe26ffdcb273dc0c4d0bae1de1bc63878faa93ef27c`.
Independent predeploy review PASS.

## Выкладка и live verification

API и worker images собраны; API обновлён, web не пересобирался. Host13/API1/
web3/worker1 hash gates PASS, HEAD `20261004_03`, migrations не выполнялись.
Резервная копия перед code rollout:
`/home/syurai/vibe-seller-state/backups/s189-before-20261004T201558Z-code.tar.gz`,
SHA256 `524ee288460cce6c8028877ad53e3da4299504a3b45bac1359a73769b2c13c62`.

Один pass 20:16:51–20:17:26 UTC выбрал и исполнил три стандартных окна:

| Окно | Ответ | Canonical / bound versions |
|---|---|---|
| 81 / 06.09 / CancelFailure | NO_DATA | false / 0 |
| 06 / 03.10 / EOK | NO_DATA | false / 0 |
| 07 / 03.10 / EOK | NO_DATA | false / 0 |

Все три exact attempt IDs, response SHA256 и journal audits сверены;
LEGACY checkpoint отсутствует. `run_corpus.status=PARTIAL`, reason NULL:
ограниченный проход выполнен, полнота источника UNKNOWN. Partial variant intake
не встретился в этом pass; его защиту проверяют отдельные существующие gates.
С момента staged snapshot фоновые workers обработали часть очереди, поэтому
новый второй EOK — 06, а не 01; это не selector override. Планирование в live
добавило 0, повтор 0. У выбранных трёх ключей не было старых attempts;
проверка их сохранности сама по себе не доказывает сохранность старой истории.
Независимая последующая сверка двух saved S184/S185 файлов подтвердила 50
различных original attempt IDs: 50 actual, missing0/mismatch0, каждый recorded
field и sorted canonical row digest совпали. Typed proof имеет aware clock,
tenant consistent snapshot, source0/writes0 и scope
`RECORDED_S184_S185_ATTEMPTS_ONLY`; это не проверка всего журнала.
Wall time от checked_at до finished_at 34.734 s; сам run с последующей сверкой
24.824 s после предварительного выбора. Это не время полного ЕИС.

API 20:19:03 UTC: health200, anonymous401, cached paper200/no-store,
828 matches/100 returned, 3727.377 ms, default scope и UNKNOWN coverage/freshness.
Проверка API не запрашивала источник и не создавала document jobs.
Operations 20:19:04 UTC: DB3821181975 bytes, volume free262449061888 bytes,
test DB отсутствуют, оба markers false; API/web OOMfalse и caps1GiB/768MiB.
Worker2CPU/2GiB, DB100GiB/minfree40GiB и cron cadence сохраняются.
Source bytes остаются на VPS; ноутбук не хранит архивы ЕИС.

## Следующий bounded этап

S190: добавить сопоставимые timestamped lease wait/work metrics для corpus,
priority и document workers, затем измерить общий рабочий цикл вместе с223.
На основании этих измерений выбрать национальное обновление текущего дня и
показатели backlog/возраста данных. Для пяти суточных families уже есть durable
plan; расширение времени и типов источника требует отдельного измеренного контракта.
National current-day hourly99×5 и полный охват всех карточек/документов ещё
не подтверждены. Новые source/CPU/memory/disk budgets в S189 не добавлялись.

## Evidence на VPS

Файлы приватны, source bytes остаются на сервере:

- `/var/lib/eis-browser/research/rejected/s189-feasibility.json`, SHA256
  `f1ccaeb78698ee09a092ae119396487d48e1ef169d38c1c0e3d3db937743957e`.
- `/var/lib/eis-browser/research/rejected/s189-lease-observation.json`, SHA256
  `9f87fe45f31f9062f7503edac27c576aa388b1a09b1a47a19e1db2e91eebcc8d`.
- `/var/lib/eis-browser/research/rejected/s189-bootstrap-proof.json`, SHA256
  `2e66414796babe98a25f6ebae28109e9a76e34a524738f70cdddf1a89bb7a2f8`.
- `/var/lib/eis-browser/research/rejected/s189-selector-actual.json`, SHA256
  `f65107109d4b7dd662f96dbca247bda4ad331c991aed4dba29d9d17fb24447ec`.
- `/var/lib/eis-browser/research/rejected/s189-live-proof.json`, SHA256
  `59802fc392c661c46d818d95dfb3a8843867fbd11cc09dcf5011a4f3d61031ab`.
- `/var/lib/eis-browser/research/rejected/s189-api-proof.json`, SHA256
  `f65d4770e5b1c4a6212316ec008a2ac7e7b0dc23ca65242315ec97301495ac96`.
- `/var/lib/eis-browser/research/rejected/s189-operations-proof.json`, SHA256
  `0d30f47a2ea5a3e2959b3eebade9823217d08c2b30ef37e53909c36069aef78c`.
- `/var/lib/eis-browser/research/rejected/s189-originals-proof.json`, SHA256
  `fcbaf82b614367fe7485917b4333f7055022ace3329a00a92124fd2e8ef0176c`.
