# M2 — проверенный инструмент снимка поискового индекса

Дата: 2026-10-08. Владелец приёмки — root; реализация — Sol, независимый
review — Astra. Контракты: [116](116-eis-search-quality-contract.md) и
[117](117-eis-frozen-benchmark-capture.md). Текущий статус программы — в
[live-плане](../../15-implementation-plan.md).

## Принятый результат и границы

M2a принят как offline benchmark; M2b1 v9 принят как ограниченный инструмент
создания и проверки снимка. Исходники скопированы из отдельного worktree в
основной workspace после проверки точных SHA. Завершённый trusted capture ещё
не принят: corpus, независимая разметка, replay, precision@10, known-reference
recall и p95 остаются `UNKNOWN`. M2 целиком не завершён, M3–M5 не начаты.

Инструмент сохраняет полную поисковую проекцию одного tenant по обоим законам:
25 relations, включая точные необходимые FK parents. Это сохранённый индекс,
а не вся ЕИС и не резервная копия БД. Бинарное содержимое архивов не выгружается.
Все лимиты, READ ONLY REPEATABLE READ, effective RLS и проверка provenance
сохранены. Проверка содержимого пакета сама по себе не подтверждает его origin.

Для тестовой схемы `20261006_12` и рабочей `20261006_08` существуют отдельные
планы с одинаковыми closure, caps и source pins. В каждом случае наблюдаемая
версия `public.alembic_version` должна точно совпасть с выбранным планом.
Пропущенная, иная или неподдерживаемая версия не допускается.

## Проверки exact v9

- 71 focused unit/legacy test PASS; число включает прежний benchmark и M2a.
- Ruff, strict mypy и компиляция PASS; 15 независимых revision probes PASS.
- Fresh isolated PostgreSQL ordinal6: один обязательный integration test
  реально исполнен, zero failures/errors/skips; collected и executed IDs совпали.
- Независимый audit проверил 15 evidence-файлов, 9 stage report references,
  весь архив из 1202 файлов, manifest/tree и семь изменяемых source pins.
- Четыре точных временных ресурса удалены; authoritative residue пуст.

Запуск: `capture-pg-20261007-174339-acba55c693c6`. Архив WORKTREE_SNAPSHOT,
parent HEAD `9dbc82b0000a23cad2e48428ce89f1b3b5aea364`; это не новый commit.
SHA архива: `d186a4ac4a6aafb223778266f1d487f3e85a2b4bb2e9356746b5233012ab8c96`.
Независимый source review SHA:
`4c9abd79b1e8942a0ffd9acf898d68a39e0254e0a746976b2e453629d124ecbf`.
Независимый actual PG evidence review SHA:
`45d32c3025af583152a7ac9280f9cc60c0fe788091b3af033f51c4c5a486bf7a`.

PG подслучай 08 использовал пустую синтетическую схему 12 с временной меткой
revision 08 и последующим восстановлением 12. Он проверяет путь выбора плана
и schema validator; actual production schema parity этим не подтверждается.
Заполненный сценарий 12 проверяет tenant isolation, snapshot stability,
конфликтующие версии/holds, источники обоих законов и offline verification.
Полный release gate нового исходника и новый commit ещё не выполнены.

Evidence и отказавшие итерации сохранены отдельно в private
`tmp/improvement-program/m2` и server state; не заменять их успешным отчётом.
Внешний root origin anchor для реального corpus пока не существует.

## Следующая рабочая предпосылка

Read-only probe рабочей роли `procurement_app` получил SQLSTATE `42501`
при чтении `public.alembic_version.version_num`. Owner-only read-only catalog
подтвердил БД `procurement`, relation OID `16573`, revision `20261006_08`,
прежние table/column ACL `NULL`, отсутствие table и column SELECT у app role.
Owner используется только для проверки предпосылки и отдельно подтверждённого
ACL действия; выгрузка corpus обязана выполняться существующей app role.

Точный минимальный payload **подтверждён пользователем и исполнен один раз**:

```sql
GRANT SELECT (version_num) ON TABLE public.alembic_version TO procurement_app;
```

План `capture-revision-permission-plan-v2.json` SHA:
`7f369705e9e51b7753563ec17ba85bee0744d4c9c5940cc2ad9d34b36971fc79`.
SQL grant SHA: `134a280d6c517344aa608c0fb86657135fd88ae7abd1eb85bc73850a386edcc6`;
conditional rollback SHA: `b2044648d549bb43c8de30d16734cca91223798055d73a3bc752143241d3dbd9`.
Внутри короткой транзакции проверяются точные target, owner, revision и ACL;
служебная relation блокируется ACCESS EXCLUSIVE с lock timeout 1s и statement
timeout 5s. Обратный payload отзывает только это column SELECT при точном
совпадении добавленного ACL. Он восстанавливает effective permissions;
raw column ACL после REVOKE может стать пустым массивом вместо NULL.

SQL v2 и wrapper v3 reviewed. Десять real isolated SQL controls PASS;
26 author и 11 independent wrapper controls PASS. Независимый actual SQL audit
проверил 50 commands, точные target substitutions и восстановление прав.
Контейнер удалён; отдельная root readback не нашла container/network/volume
residue. Actual SQL review SHA:
`fed71d753047e2797e8ced144ea921e4989255edd1adebfd76233a11a81f3b47`.
Техническая подготовка принята отдельно от исполнения. После прямого
подтверждения пользователя owner SQL acknowledgement получен; обязательная
app-role READ ONLY проверка после commit прошла. При неоднозначном transport результате
нужна read-only сверка состояния; автоматического повторения или отката нет.
Требуется исключить параллельное административное изменение ACL/roles;
блокировка revision relation не заявляется общей блокировкой role catalogs.

По [AGENTS.md](../../../AGENTS.md) внешнее действие требует exact-payload
approval. Прямое подтверждение пользователя связано с подготовленным точным запросом;
external approval receipt и обе стороны audit сохранены. Остаются actual
schema/runtime parity, trusted tenant capture, isolated replay и независимая разметка.

## Приёмка рабочего права, 2026-10-07

GRANT исполнен один раз через reviewed wrapper v3. После commit app role
подтвердила БД/tenant, READ ONLY REPEATABLE READ, revision 08 и OID 16573,
column SELECT true при table SELECT false; superuser/BYPASSRLS false.
Первый отказ preflight из-за дополнительного compose-файла сохранён;
независимо reviewed helper v2 проверил точную текущую конфигурацию.
Независимый audit сверил 18 входов, внешнее подтверждение, exact payload,
local/remote before/after и фактическую app-role проверку. Root принял только
metadata permission; corpus не выгружен, реальные метрики UNKNOWN.

Applied review SHA: `1bccb61d600b476532ba200c810adbb5a0326a26b90d7141a61c062ff9d56b62`.
App-role proof SHA: `433e99726c23025540abb52fb614b16c4a96f544ccac42fd68e491fb20f41a17`.
Условный rollback не выполнялся; изменений данных, приложения или cron нет.

## Подготовка actual capture и replay

Root принял только staging helper v2: 15 независимых controls PASS,
bounded descriptor reads и проверка тех же bytes, которые передаются на сервер.
Отклонённый v1 сохранён; server staging ещё не запускался.
Read-only runtime readback подтвердил exact API/PG images, их общую сеть
и app role; шесть deployed file hashes и версии зависимостей не изменились.
Сеть общая, исключительный DB-only egress не заявляется. Deployed Git commit
остаётся UNKNOWN; он не подменяется parent commit коллектора.

M2b2 protocol v3 прошёл независимый review только как подготовка: девять
intent/scope случаев, полный независимый reference discovery, page 100,
три повтора, timeout 30s на страницу и budget 20 продолжений. Exhausted
budget оставляет полноту UNKNOWN; SQL_STORAGE не выдаётся за HTTP/UI SLA.
Конкретные suite/seed/quotas, isolated restore parity и labels ещё нужны.
Этот preparation record предшествует отдельной приёмке controller v2 ниже.

Stage review SHA: `00f4fd6dc7fad54079225ecf316d167dae38925da418ae2d9a7882b0ac710d1b`.
Protocol review SHA: `b8e8e71384957eec6942233b19741393ca48cc749d851863380e0e43db7c6ee6`.

## Первый actual capture — INCOMPLETE

Controller v2 и exact root plan приняты после закрытия четырёх отказов:
32 author и 27 independent controls PASS. Actual запуск выполнен один раз;
collector остановился на RAW_ROW_EXCEEDS_SHARD_LIMIT:audit_events до
streaming строк. По pinned-code control flow runtime и schema/RLS validation
25 relations вернулись успешно; отдельный certificate не сохранён. Failed
marker clock — host attempted_at, actual DB T/snapshot UNKNOWN.

Сохранены девять byte-exact actual evidence файлов. Отдельная readback
подтвердила пустой owned-container inventory, отсутствие credential-файла и
прежние API/PG IDs/images/running; full controller postflight не выполнялся.
Независимый audit принял failed evidence и cleanup, не corpus/origin.
Actual review SHA: `9017eac76744485eec9c6db7644262f39fc03b29a9d67983e3d3c7f022fc243b`.

Отдельный app-role READ ONLY/RR scalar probe измерил 96 связанных audit rows:
три превышают 8 MiB, max raw 14 839 504 bytes, max basis 14 839 307 bytes.
Все три относятся к EIS_NOTICE_PROJECTION_RECORDED; bodies не выгружались.
Поздний probe T не подменяет отсутствующий failed snapshot. Typed encoded
размер и семантическая полнота этих записей пока UNKNOWN.
Width proof SHA: `f5056766500fcc1993231df1d67c220bac04905de1646562b20586b94552deec`.

Root принял архитектурное направление: явный audit-only format v2 с binary
fragments точных canonical typed row bytes. Новые logical bounds 32 MiB raw /
64 MiB encoded видимы в контракте; physical shards 8 MiB, prefetch 64 MiB,
4 GiB total, 512 payload files, 900s и 2 GiB container остаются прежними.
Нужны versioned contract, реализация, semantic/adversarial/real PG и memory
проверки, independent review и новый capture ID; retry сейчас не запускался.
V1 source/plans/контракт и failed run сохранены. Метрики UNKNOWN.

Явный контракт format v2 принят root: [ADR-0108](../../adr/0108-bounded-eis-audit-row-fragments.md)
и дополнение в [117](117-eis-frozen-benchmark-capture.md). Sol владеет только
семью перечисленными source/test/new-plan paths в managed checkout; Astra
проверяет exact source независимо. Два исходных v1 plans остаются неизменными.
Новая отдельная focused PG проверка готовится с действительным ограничением
всего disposable worker в 2 GiB и измерением cgroup peak; локальные проверки
контроллера не являются измерением памяти или результатом actual PG.

Root принял подготовку нового focused PG harness: 17 author и 28 independent
controls PASS. При actual запуске он ограничивает весь exact owned worker
до 2 GiB без swap, проверяет настройки и сохраняет cgroup peak до/после теста.
Это не отдельное измерение RSS collector/verifier и не доказательство fit
production corpus. Review SHA:
`79f03842d839c7d81411e9855127d171603af0242fe6d37d870946d0c8a1ab33`.

Первый вариант local snapshot/staging helpers отвергнут: разные reads для
hash/parse handoff, неэксклюзивная публикация и reopening проверенного Python
helper. Сохранённые новые v2 helpers закрывают все три finding; 14 independent
controls PASS, root принял только подготовку. Review SHA:
`124427812ca4e00ee0d006a1a89f843e26cca8e79fa17eea82da8834b7332783`.
Actual archive7, fresh PG/peak evidence и production capture требуют отдельных
source freeze/review и запусков; эти проверки их не заменяют.

## Format v2: первый source review — REJECT

Author freeze v1: 48 capture units и 38 benchmark tests PASS; independent review
повторил 86 тестов и выполнил 12 дополнительных controls. Выявлены два blocker:
пакет с заведомой raw нижней границей >32 MiB принимался verifier, а физический
fragment записывался до отказа по исчерпанному global budget. Exact source,
контракт, два старых плана и evidence сохранены: 13 inputs; archive7 и actual PG
не запускались. Review SHA:
`efc43df15786142f74758b4841ec7e3c71183cb2553b010bd0a8ee5a9d728251`.

Root принял явное уточнение ADR/117: offline проверяется bounded decoded string
lower bound; exact PostgreSQL text width остаётся наблюдением collector в TX и
предметом последующего external origin audit. V2 report явно оставляет source
raw-width attestation UNKNOWN. Global payload file/byte capacity резервируется
до любой физической записи, включая inline/fragment transitions. Sol исправляет
тот же ограниченный срез; новый source freeze/review и real PG/memory evidence
остаются обязательными. Пределы не увеличены; реальные метрики UNKNOWN.

## Format v2: исправленная заморозка исходников 2, review pending

2026-10-08 root сверил семь source pins, два уточнённых контракта и два неизменённых v1-плана из `capture-format-v2-implementation-handoff-v2.json` (SHA `044fd2130696ab6c5982af0f70bb3c8e81293169a1ef228deb5eed08216bfe13`). Автор получил 96 scoped тестов PASS; единственный локальный PG-тест SKIP из-за отсутствия среды. Независимая проверка исправлений F2-A/F2-B выполняется отдельно. Архив7 ещё не создан; actual PG/2GiB memory, новый production capture и реальные метрики не подтверждены. Первая отвергнутая заморозка и её evidence сохранены.

## Format v2: source repair2 ACCEPT и запуск focused PG

Root принял independent source review `capture-format-v2-independent-review-v2.json` (SHA `a7a7b21d9de9774a83f0738c8b8c3dadebc05d5dbc5c32809471d06e8c74b6cf`): 96 scoped tests и 20 independent controls PASS; F2-A/F2-B закрыты для точной заморозки. Curated archive7 SHA `9a5627f73e3b228b614dfe870445aee737fbe5cbacfd1f0857dcaed5056c0ba5`, 1206 файлов; это WORKTREE_SNAPSHOT, не deployed commit. Новый plan SHA `201abe7b9b97117bf1cb1a5dab1790eadc8572057184186293d8a97d8eaddda0` и четыре входа отдельно staged в `capture-format-v2-pg`. Launcher исполнен один раз; actual diagnostic запущен. Terminal/JUnit/child RSS/cgroup/cleanup ещё не приняты; инструмент, production fit/origin и метрики pending. Старые архивы, controllers, v1-планы и failed-run evidence сохранены.

## Format v2: actual ordinal7 PG FAIL, evidence preserved

Fresh run `capture-pg-20261007-215725-cb27113effac` завершился DIAGNOSTIC_FAIL/transport exit1. Runtime/build/start, whole-worker 2GiB bound и migrations PASS. Единственный integration test выполнен и FAIL: `test_eis_search_capture_pg.py:644`, требование минимум трёх fragmented audit rows получило ноль (audit relation rows22). Fixture не воспроизвела крупные связанные audit bases; порог не снижается. 16 terminal/stage/JUnit bytes сохранены и hash-сверены в `capture-format-v2-pg-ordinal7-evidence`; cleanup complete по результату, independent failed-evidence audit pending. Final cgroup evidence stage не исполнился; multi-large memory/instrument acceptance UNKNOWN. Sol владеет только PG fixture для узкого исправления; архив7, handoff2/review2 и предыдущие версии immutable. Новый PG требует отдельной заморозки, архива и stage; production retry отсутствует.

## Format v2: fixture repair accepted, fresh ordinal8 launched

Rootcause ordinal7: title>4000 давал TITLE_LIMIT/HOLD и snapshot=None. Новая fixture SHA `1b124ccd692a1c2150053f687423a5004751681c2c97aa6d91210a09c835ba9a` использует валидные title и attachment metadata; independent actual parser всех 1350 snapshots PASS. Review SHA `8025caddf7324819717a4b5f341e7ce2f497ad3bcd313ede52e831092c6b4293` допускает fresh PG; шесть остальных исходников и v1-планы unchanged. Exact collector SQL selection проверяет три связанные raw audit rows >8MiB и <=32MiB перед сбором. Новый curated archive8 SHA `dfc6de8e34d7ef7f266efbdf7a4cb57d6b57f306f6eb9c567503ad447cb57e6e`; fresh plan SHA `c06539c83fd6d875a9170ac8c70fa747f459bb859ed1d86f7398d8a4c5aa0868` staged отдельно в `capture-format-v2-pg-fixture-repair1`, launcher исполнен один раз. Обязательны оба collected tests без skips и scalar SQL/childRSS/finalcgroup evidence. Actual diagnostic запущен, terminal acceptance pending. Ordinal7 failed-evidence/cleanup отдельно приняты root после independent audit и fresh server label inventory []; старые артефакты immutable.

## Format v2: bounded instrument accepted after actual ordinal8

Independent actual evidence review SHA `6fc09ab370b765496dd7eef9b93353fe45e48ff00118d66f4ef0775a5e62884a` и root acceptance `capture-format-v2-instrument-root-acceptance-v1.json`: все17 сохранённых файлов/report hashes и curated source closure сверены; 2 collected/executed tests PASS без skips/errors/failures, все8 stages PASS. SQL подтвердил3 связанные raw audit rows по9602437B; encoded max10602694B и3 fragmented logical rows. Whole-worker cgroup max2147483648B/swap0/CPU1; peak541057024B. Отдельные child RSS223072256B каждый — lifetime high-water, возможен startup/inherited floor; incremental phase usage не заявляется. Четыре owned resources удалены, final inventory[]; последующий root live label inventory тоже пуст. Семь принятых исходников скопированы в primary после проверки прежних v9 pins и отсутствия новых путей. Primary scoped command exit0; separate collection98 и один локальный PG skip дают inferred97PASS; actual PG отдельно2PASS. Ruff/scoped strict mypy/compile/docs PASS. Это synthetic bounded instrument acceptance; production fit/origin/trusted corpus/replay/labels/метрики и новый full release gate не подтверждены. Следующий срез — отдельная version-bound адаптация production runner/launcher, затем fresh actual capture.

## Format v2: отдельная controller adaptation и fresh metadata

Sol владеет только пятью новыми ignored controller/test/probe/handoff файлами; root владеет final wrapper plan/facts/staging/execution/docs. Assignment записан в `trusted-capture-format-v2-controller-task-v1.json`. Старые controllers/планы immutable; actual production capture нового формата ещё не запускался. Fresh `capture-target-facts-format-v2.json`, `capture-runtime-metadata-format-v2.json` и `capture-app-metadata-format-v2.json` получены read-only: API/PG identity, шесть source fingerprints и runtime versions совпадают с предыдущими; query parameters отсутствуют. App metadata lookup в READ ONLY REPEATABLE READ/tenant local, nonsuper/nobypass, schema08 PASS; data/privilege writes отсутствуют. Эти metadata proofs не являются frozen corpus или origin anchor и не задают будущий capture T.


## Format v2: actual production capture1 INCOMPLETE

Exact controller review SHA `df28909349d64a34fddce2f8f7d21ed5e7e441946696fed5b72a79a17199235b` и plan review SHA `8f23d6cb83e7c605b50397169f9dc83e9988533ff7eb2ef6547490dbadd727df` приняты для запуска; plan SHA `db0820497d4f55861ec4f181f8cc2c26d11ada81e90d53d0d67989b85fb4729b`, archive8. Staging24 exact inputs и single launch выполнены. Actual run `trusted-capture-v2-20261007-223828-1c89d6014cfcd5a125ba1d9e` завершился INCOMPLETE/exit2: preflight count/max raw width для `eis_feed_archives` превысил statement timeout30s. Связь архивов задана correlated OR EXISTS по notice versions/procedure events; причина плана SQL проверяется отдельно. Physical payload0, complete manifest/verifier отсутствуют. DB T `2026-10-07T22:39:45.179444Z`/snapshot `110228:110228:` относятся к неуспешной транзакции, не certificate полного corpus. Девять terminal files сохранены в `trusted-capture-format-v2-run1-evidence`; root-readback SHA `923e4dd61547069b00a4c553621c754d49861680a012f171300e3f52df8768cd` подтверждает staged pins, credential absence, owned inventory[] и прежние работающие API/PG identities. Independent failed-evidence audit pending; полный состав данных и caps остаются прежними. Trusted origin, replay, labels и метрики UNKNOWN. Sol анализирует ограниченный SQL repair; retry отсутствует.


Root принял только failed evidence/cleanup после independent review SHA `9330eedc0f7b864c0715acead78eb1a8cfbc4293bddd3ff26ba544f156bf1f5e`; postflight runtime отсутствует, поэтому более сильное утверждение не делается. Отдельный поздний app-role READONLY/RR scalar/EXPLAIN diagnostic нового полного composite-key UNION DISTINCT JOIN: count10396/maxraw212B за747.218ms. Старый EXPLAIN содержит correlated SubPlans; новый Hash Join/Unique/Sort/Append без них. EXPLAIN cost не время и не измерение server memory; диагностический T отличается от failed capture. Это подтверждает исполнимость одного query, не эквивалентность всего corpus или full-capture performance. Sol реализует только feed archive selection с duplicate/tenant/key-component/equivalence controls; caps/schema/permissions и остальные relations прежние.


## Feed archive query repair: source accepted, PG9 launched

Independent source review SHA `1b6f84fc37e3bd31bd8bd4d4de37fb07f8ace8a77130af6eaee4a6ec7ae40d5a`:59 capture units+1 local parser PASS,9 controls PASS; remaining24 selections byte-equivalent, guard AST unchanged, both v2 plans only collector pin differ. Local author98PASS+1requiredPGskip. Handoff SHA `7cafaae167245640b096fd02b487d5758a51b4937a2f1644f2ccd0e16ba3be9f`; previousseven files preserved. Fresh mechanical helper review SHA `bd115e08535ffdf0107107b1061f6577abfb8ac34f600c1292c0fb62f746d020` accepted only preparation. Archive9 SHA `bd377cc9743f6f85e3a686a3fc9a4b5d190d288285e7e50c0fd161a5b107c26a`,1206files/3619400B, WORKTREE_SNAPSHOT. Exact isolated PG9 plan SHA `b06c6280a8525480044cfab0e8693aaafe561bf964c28ba0cc1dface9cfe3bd4` staged4files in fresh `capture-feed-query-pg-v1`; single launcher PID3313128 at22:57:39.723211Z. Actual two-test/full-capture/equivalence/memory/cleanup acceptance pending. Source7 frozen in managed; Sol prepares only separate production controller mechanical rebind to archive9/fresh stage/basenames. No production retry or cap/schema/permission changes; origin/metrics UNKNOWN.


Actual isolated PG9 terminal DIAGNOSTIC_PASS/transport0:8stages PASS,2collected/executed tests,0errors/failures/skips. Same-RR old/new EXCEPT, multiplicity/membership и no-SubPlan EXPLAIN assertions исполнены; полный JSON EXPLAIN fixture не сохраняет, поэтому assertion PASS не подменяется сохранённым query plan.17terminal files preserved. Whole-worker cgroup exactID max2147483648B/swap0/CPU1, peak530612224B; childRSS223432704B каждый — lifetime high-water, не incremental phase.3fragmented auditrows/rawmax9602437B/encodedmax10602694B, raw width lower-bound validation/source attestation UNKNOWN. Cleanup4resources complete/residue[], freshroot label inventories containers/images/networks[] (SHA `30278b75ec632f2078eda9b46e437a313f63c6c36db4f16b340a5d4ee76acdb1`). Independent evidence audit pending; production corpus fit и origin/metrics UNKNOWN.


## Query repair instrument accepted; exact production query1 plan pending

Independent PG9 evidence review SHA `9f17abad84d603a9cce89743ea23d9e1c72c13a2020af431538f63486889cd4a` accepted bounded synthetic repair. Root guarded-copied7source files from managed after comparing all previous primary pins and unchanged v1plans. Primary98PASS/1localPGskip in49.84s, Ruff/strictmypy4files PASS; actualPG separately2PASS0skips. Root instrument acceptance is `capture-feed-query-instrument-root-acceptance-v1.json`; no full release gate or app deploy. Mechanical production controller/stage review SHA `51d4746ee76ffb197d953de927b15cc7b9d87b637a555c57961ee8fec89a98ff` accepted:7tests/36author/13independent controls and normalizedAST5/5 PASS, no server calls. Dedicated runner/launcher v3, archive9 and fresh `trusted-capture-format-v2-query1` stage preserve formatV2/guards/caps. Root fresh target facts SHA `ddc9c78f0101bb105cd23d4abe2064bcc5007e062d7f83c1cce3422189739be7` equal old canonical facts except observed_at, so old filename remains immutable plus explicit fresh/parity inputs. Fresh app metadata READONLY/RR/schema08 PASS; no privilege/data writes. Exact concrete query1 plan SHA `7bdab953d2879e33237a80496bb794c79ad9bae23f369ad030686d8cf9e002db`,23evidence/27stage inputs, strict local validation PASS; independent exact plan review pending. Run/capture IDs are host-generated labels, not assigned DB capture T. Actual stage/retry absent; production corpus/origin/replay/labels/metrics UNKNOWN.


Exact query1 production plan review SHA `2d0a46e281516a6755596d6250a6a1ecca00ec77336efff0aefb6ddaa7f091e0` accepted for stage/launch only. Root staged27 exact inputs and launched once PID3745663 at2026-10-08T05:13:46.653318Z. Run `trusted-capture-v2-query1-20261008-051403-a435325aa3c89d10777e41b3`; output/state roots are plan-bound, original two failed runs preserved. Current actual completion/content/cleanup/origin review pending. No new privilege changes or production data writes requested; capture uses READONLY/RR/tenant app-role. Metrics UNKNOWN.


## Query1 actual capture INCOMPLETE: encoded non-audit row bound

Actual query1 collector exit2/controllerINCOMPLETE: `CaptureCollectionError:ROW_EXCEEDS_SHARD_LIMIT`.70physical files/452345929B remain partial, no manifest/verifier. Partial decoded counts include9395 `eis_223_notice_versions` plus preceding223relations; exact offending row not yet inventoried. Preflight raw scalar bound passed, canonical typed encoding can be larger; partial counts are not completeness. Failed DB T2026-10-08T05:13:49.955056Z/snapshot113647:113647:. Nine terminal bytes preserved in `trusted-capture-format-v2-query1-evidence`; root readback SHA `ecbb75dccaf0c1013ae396256063f2b8f16faf224014e2fef992e412d3cecc18` confirms27staged pins, credentialabsence/freshownedinventory[]/API-PGsameIDs-images-running. Independent failed-evidence review pending, no retry/capraise/trim. Sol prepares bounded late READONLY raw/encoded-width inventory, source7 frozen. Separate design risk: offline verifier's SQLite TemporaryDirectory uses/tmp, but production verifier's/tmp is64MiB; synthetic PG9 worker did not prove that scratch fit. Need explicit bounded scratch treatment if confirmed, not silent memory/resource relaxation. Trusted corpus/origin/metrics UNKNOWN.


Query1 failed-evidence/cleanup independent review SHA `e16129ac06568e2eeeb8d22bc65a3da5bc05bb8822d1700bc337729e2f2f2b5a` принят root только в этих границах. Exact offending PK/encodedsize ещё неизвестны; prospective/tmp64MiB SQLite risk не объявляется наблюдённым ENOSPC. Root назначил READONLY bounded width inventory и новый format3/scratch design; source7/plans/controllers frozen, retry отсутствует.

## Подготовка format3: диагностика размера и отдельного scratch

Назначение владельцев, файлов, зависимостей и acceptance сохранено в
`capture-format-v3-task-v1.json`. Sol готовит ограниченную диагностику 11
non-audit JSON relations; Astra независимо проверяет чтение и точность encoding;
Luna готовит отдельный disposable SQLite sandbox без доступа к production БД.
Root владеет запуском проверенных инструментов и будущим контрактом. Исходники
поиска/capture и прежние планы остаются замороженными.

В первой версии width probe root self-test PASS. Независимые локальные проверки
подтвердили 44 случая эквивалентности encoding, но выявили unchecked short writes
в private stream и отсутствие конечного remote timeout вокруг блокирующего
Docker inspect read. Запуск этой версии не разрешён техническим review; новая
версия должна закрыть оба случая. Private encrypted SSH stream содержит выбранные
поля для локального encoding; persisted отчёт и human logs — только scalars,
typed PK и hashes. Нельзя утверждать, что private transport не содержит данных.

Scratch design v2 SHA
`ab6d1faf0b2c38bdbef6f5e4cac58e3fd5725c19c53a9cac79b528248f9685ff`
предлагает RW bind единственного заранее созданного файла с RO parent и
ограничением SQLite main file; `/tmp64MiB` и RAM2GiB сохраняются. Это дизайн,
а не подтверждённая изоляция или fit. Нужны реальные page-full/tmp-full,
запрет sibling writes, inode и упорядоченная cleanup проверки. Draft
`capture-format-v3-root-contract-draft-v1.json` не разрешает реализацию или retry:
сначала измерения и sandbox, затем явный новый контракт/ADR с сохранением V1/V2.
Trusted corpus, origin, precision/recall/p95 остаются UNKNOWN.

## Width inventory: actual ограниченный замер принят

Root один раз исполнил frozen probe V2 SHA
`69b916a41b602dc7eac8372f74a8f16a67a023457362f6d30fdf45262a938bf7`;
exit0. Evidence `nonaudit-encoded-width-v2.json` SHA
`ba38663a8ad050a933dfb478ba29763a2c239b5cffc2e73bc19a55848e547507`,
independent review SHA
`833d3b372e02f12e45d57355192eda2ea0f92fee3241c24c72daf05c0fdbc4e5`.
Измерены11relations и42кандидата: у lot_events только2строки, у остальных по4.
Selected raw bytes38085933. App role READONLY/RR/tenant/schema08 подтверждены;
DB T05:43:07.047852Z/snapshot113962:113962 относятся к новому замеру.

223 notice candidate32616441976/version1: raw8204471B, snapshot column8175142B,
exact typed encoding10836001B/SHA
`1f6626059307cb6fd9c9ebc4829d66bc34babc212badb7a95a79f67f4a9e29c2`.
Это подтверждает механизм encoded expansion >8MiB при обычном raw<=8MiB,
но не идентичность offender в прежней failed TX. Tenant counts этого замера:
223notice versions12035, 44notice versions280086; это не официальный census ЕИС.
Encoded global max остаётся UNKNOWN_TOP4_ONLY; bodies намеренно не persisted,
поэтому independent review не пересчитывает hashes из отсутствующих bodies.
Root acceptance: `nonaudit-encoded-width-root-acceptance-v2.json`.

Новые [ADR0109](../../adr/0109-bounded-eis-capture-v3-state.md) и
[контракт V3](119-eis-capture-v3-contract.md) пока DRAFT/PROPOSED. Они учитывают
отдельные1GiB collector membership/64MiB pending/8GiB verifier candidate ceilings,
внешние SQLite runtime pins обоих процессов и явный disk admission. Source
implementation и fresh capture ожидают actual sandbox и принятия контракта.

## V3: actual sandbox и контракт приняты, source slice начат

Root один раз исполнил frozen SQLite sandbox helper V3 SHA
`9c86664cd0b03d0ad5fb1f0fc9e6087ebe6cd6a8ec5991f04e11740ab7076d1d`.
Result SHA `42e342014fc8fe02d2af664acfccc568761c0537b0f875845c35b127bfbafa5b`,
independent actual review
`b382781afdd41ec9b3190f94707447db4b4a006c4f074859ec3441de90b25082`.
Networknone/no credentials, RO root, единственный RW file bind, CPU1,
cgroup RAM2147483648/swap0; same host/container inode64770:6702455. SQLite main
остался32768B;8pages×4096, шестая successful insert, следующая FULL с немедленным
close. Семь sibling/mkdir/unlink/rename controls отказали. Tmpfs67108864B,
one-over ENOSPC, exact nonce file удалён. Exact owned container removal,
authoritative empty inventory и original-inode host unlink подтвердили cleanup
по terminal evidence проверенного helper. Reviewer не выполнял live access.
Это механизм, не8GiB fit и не измерение memory peak.

SQLite3.45.1/source_id с distro alt1 и58compile options зафиксированы отдельным
operator pin `capture-v3-sqlite-runtime.production-v1.json`, SHA
`c8829afb343817f00cda310e33b08485e0555ac51689c05d618602cb8b150cc6`.
Canonical options digest
`3eee98448c100293647ea3c5b35186ce7fd1d02bb03557f90b84d5e0dab351b7`;
TEMP_STORE compile1/effective2. Pin не находится в package и не аттестует origin.

Final contract review SHA
`7d7524c91c9b8bfa7cde158f919b6ebc0c0d180e286a31bae1d442333485985f`
закрыл C1–C6/B1–B6. Root сохранил prior draft bytes, изменил только status/editorial
и уточнил42кандидата/up-to4; accepted ADR0109 SHA
`9352b9dc082e723512b117f589c440956dfab66963dc5a11976c0613da8fb8f6`,
119 SHA `9f479fd64e3aa7f19be1ab67bd21f7e0a8430af21ce37edef02e000593875db1`.
Все12baseline inputs сверены primary+managed; четыре old plans неизменны,
два V3 plan paths были absent. Root acceptance SHA
`2a35a9bfb6d6d47bdea1702122611c5bb3e48508bcf5dac4d065fa309b31a8a6`.
Sol начал exact7file slice в managed по `capture-format-v3-source-task-v1.json`;
root owns docs/archive/controller, Astra — independent review. Source freeze,
actual multi-large PG/intended-layout stress, production capture/origin и
benchmark metrics ещё не приняты. Нет нового commit/deploy/permission write.

Отдельная clock observation: remote UTC примерно239s позади local; сервер
сообщает NTP synced, локальная Windows time service остановлена. Это не
независимая аттестация UTC accuracy. DB capture T сохраняется как DB observation,
длительности — monotonic, host run labels не подменяют snapshot time. Настройки
часов не менялись; evidence `clock-cross-observation-v1.json`.

## V3: уточнённый PG layout и подготовка следующего архива

Astra layout design `capture-format-v3-pg-layout-design-v1.json` SHA
`7edd008657594a5630de12cab3067b7c7369d338981495a95848cd4cf7710e43`
исправляет описание PG9: worker имел `/test`1GiB tmpfs и `/tmp`512MiB tmpfs,
`TMPDIR=/test/tmp`; это не overlay. Старое memory evidence действительно для
этого worker, но не доказывает production `/tmp`64MiB или single-file verifier.
Предложено использовать существующий fixture setup, затем запускать отдельные
collector и network-none verifier с точными production mounts/лимитами. Seed
protocol для fixture/export ещё замораживают Astra и Sol; ни один из этих новых
V3 этапов пока не запускался.

Read-only archive impact `capture-format-v3-snapshot-preparation-impact-v1.json`
SHA `cf41f4997c68b4a23480cdce0f4c6d4e2ca8af55fd9f71f7ccec24e403170664`:
будущий archive10 должен включить семь final V3 source members (в том числе два
новых V3 plans) и сохранить четыре исходных V1/V2 plan bytes. Их точные новые
source hashes ожидают frozen handoff Sol; ordinal9 archive/proof/stage остаются
неизменными. Контракт/ADR и README indexes закрепляются отдельно, без неявного
расширения source tar. Root готовит свежие harness/controller/plan bindings;
source freeze, archive10, actual large-row PG и V3 capture пока не приняты.
Trusted corpus, origin и benchmark metrics остаются UNKNOWN.


### V3: отдельный PG harness, review до внешнего запуска

Root владеет новыми ignored PG harness/phase helpers и локальными refusal controls;
Sol продолжает exact7 source slice. Protocol `capture-format-v3-pg-fixture-protocol-v1.json`
SHA `422751e691405b48f348e1cf413d19b34ab9e0c8d105dce34aac73dbb34ad12e` принят root:
optional test-only export после normal cleanup, exact25 selection counts и finite
large-row cohort; receipt не задаёт paths, credentials, permissions или runtime.
Generic pytest worker удаляется до dedicated collector/verifier; их capture T
новый, прежний concurrent-commit test остаётся отдельным доказательством.

Frozen harness v1 получил REJECT review SHA
`07f097d8cf5c612a4aa7fb9748dc9987af78f5ced9750b3becf6f4c9782f352f`:
H1 терял failed cgroup observations, H2 поздно регистрировал inode transient files,
H3 не гарантировал nonblocking open/full opened-FD validation. Его bytes сохранены.
Fresh v2 handoff SHA `2e24659de2c6961f90e7de0acfa2e6e195f57b6636b03ccebd3d0bda6a01895b`
содержит repairs и64 local fake/child-pipe controls PASS; Ruff и exact compile PASS.
Это frozen-for-review, не actual Linux/PG/layout acceptance. Work3600s и отдельный
cleanup300s, public phases930s, command stdout4MiB/stderr1MiB; outer launcher review pending.

Snapshot curator v1 также не запускался: review SHA
`30031a87ffeea39185c6d755c4b755094ada1b61efe279cc0e71122b3b4532e4` REJECT SN3-1
за implicit TemporaryDirectory finalizer, обходящий explicit inode guard.
Luna готовит fresh manual-cleanup revision; archive10/stage/actualV3PG отсутствуют.
Full semantic stress >64MiB SQLite и worst valid dense/escaped64MiB heap pressure
ещё не подтверждены. M2b2 V3 impact SHA
`0ae3e467027d2cce2d822ecf4ce4aca21ad5f63e2107624e27b6748f944f9b0b`
сохраняет nine-case SQL_STORAGE protocol, independent official raw labels и
external origin prerequisites; restore/replay/labels/quality metrics не запускались.


### V3: четыре source blockers и ограниченный transport

Astra отклонила первый exact7 source freeze: review
`capture-format-v3-source-review-v1.json`, SHA
`a3f59b03f9c01e69582cb0125f2a46e944a370d27506179833ff1d0460bc07e2`.
V3-S1: ordinary seed ломал обязательную V2 проверку до optional export.
V3-S2: COMPLETE verifier принимал неверную роль/размер membership observation.
V3-S3: membership backing file удалялся после неуспешного close.
V3-S4: failure flow терял уже наблюдавшийся pending high-water и сообщал ноль.
72 local tests PASS не отменяют эти воспроизведённые отказы. Root назначил Sol
finite source-repair-v2 с сохранением предыдущих семи bytes, новым handoff и
регрессиями для каждого finding; actual PG и source acceptance не выданы.

PG harness v2 принят как preparation-only после независимого review SHA
`071fdce0e0ad8d9aa7c0355d36d9fcd465a9356a5dac770eb4adfc55e87b01fb`.
Root подготовил fresh stage/launcher:41 local controls, Ruff и3 compile PASS;
handoff SHA `649c04ef357a07783a83b15ec7543d3e0362764a86d5afa6a19b783caa63cd0a`.
Это ещё не review/actual acceptance. Лимиты3900s harness +300s recovery,
stdout4MiB/stderr1MiB, total staged bytes32MiB; interrupted host-file cleanup
остаётся UNKNOWN без первоначального inode evidence. Никаких server calls,
archive10, нового execution plan или actual V3 PG этот срез не выполнял.

Отдельный finite14-case codec-pressure design SHA
`f162cc04dda7bac2c68443b4df1dd883d97f5d9d3271220c933b1eedfcec3744`
задаёт boundary/dense/escaped/wrapper проверки; authoring приостановлен для
приоритетного source repair. Заявленный2GiB fit и полный semantic state >64MiB
не измерены. После trusted capture нужен новый isolated restore/parity runner:
готового принятого restore mechanism пока нет. Origin/labels/quality UNKNOWN.


### V3-S5: реальный рост SQLite и незавершённая транзакция

Source handoff v2 SHA
`88565e6f106fb5b907aab7cc5b8e150a47c465a4ebe505c4fe35c3e3f62bca9d`
содержит S1–S4 repairs,84 scoped PASS/1 unavailable localPG skip, benchmark38 PASS.
Astra подтвердила эти repairs, но review v2 SHA
`ef1a115249ea5a1c8a9250a46e12d3554fe3596c33af30b649bb62edf097c039`
выдал REJECT за V3-S5. Actual private SQLite membership1000 inserts:29pages
до close,20480B после rollback при close; probe-only commit дал118784B/PASS.
Реальный verifier lifecycle также воспроизводит mismatch после роста файла.
Это local SQLite3.50.4 с Windows POSIX metadata shims, не pinned Linux3.45.1
или actualPG acceptance. Root назначил finite repair-v3: success-only checked
commit до terminal observations для двух ephemeral SQLite roles, real growing
file regressions и запрет дальнейшего SQL после fault. Hard bounds/equality и
PostgreSQL READONLY transaction не ослабляются. Предыдущие seven bytes сохранены.
Archive10/stage/actualPG остаются незапущенными; codec helper saved/paused.

Transport независимый review SHA
`979a08235eac45373b663928ec4d62e4336d09d5a959b77fc440a3bc6d50acb7`
принят как preparation-only:41 author +9 independent controls. Curator v2
root review SHA `0a1ff92891731fdb482273a6ca05b176316309f9ed6c0072660e2e7bcf48b90f`
принят после actual replacement/refusal/GC preservation checks. Ни один из этих
результатов не подтверждает source readiness, PG fit, origin или quality metrics.


### V3 source preparation and archive10: actual PG still pending

Root accepted the exact source-v3 handoff as `ACCEPT_CODE_PREPARATION_ONLY_NOT_INSTRUMENT_OR_CAPTURE`: source handoff SHA `6d3acea1224c6799d83ee0965f0ae74fa39dee2b69fbbc394e377fa189575082`, Astra review SHA `b5b9ae6f0ff40c73fdacbdcac5a0bcebda9d0c60ad7e85a0ba04a0dd4e1415d7`, root acceptance SHA `b1520e9e67039f1e68da224ede83daf35a7f59a8e1031ecd790ab41356639b26`. S1–S5 are closed by independent code review: 93 scoped unit/regression checks plus 13 independent function controls; all seven source hashes, four preserved legacy plans and two contracts matched. This is preparation acceptance only: PostgreSQL was not run, resource fit is UNKNOWN, and no capture/origin/quality acceptance follows.

Archive10 `capture-source-10.tar.gz` SHA `e8c92db19617f67b560f2e1282d3f3e7d481cb5d1c9b65f239b8d59a0d0d14b7` contains 1,210 files; snapshot proof SHA `d37214f7a93d355db31f0eeb2257c7e479bf20f0b60d3d08e6e8023e1eb37c19` records that bundle and tree SHA `9e6c1a636b95bf71acebe86199fd5d8f88ba2a0dd2d27589e08535610024ca1c`. The exact ordinal-10 plan SHA is `c7b8dcde3bf13596a79a49c26deeb4e609e80f201de5aa930d59a4afc07b978d`, nonce `d94d4e46505f46e50a00a90f`; plan review is pending. Nothing was staged or launched, and no actual PG run or capture occurred. The archive was sealed before this documentation update and contains the prior doc states; these newer doc bytes are not claimed to be in archive10.

The bounded evidence preserver v2 root review SHA `bcafcc9c6cba9bb6015d0964e1c613f8083bbf7620ef79a8b7a7c953adc239af` accepted preparation only. Helper SHA `30201565085ef8e75b17a82c226bf6085438368324f160b1b2df6eed013b0366` and handoff SHA `129844bc221312674798f22c19499c19dfdd8fd2f1140ec19bff51bd8997dea8` bind the actual launcher worker-start schema and preserve ambiguity as UNKNOWN; it has not read a real run. The separate codec-pressure helper SHA `c910a5fb5279de565c0c9edaf794dd79c9a19c5e55e5f7eac9efb47468cd13a7`, tests SHA `9d7be06038398cd8a2997f8ce54d8a4a9073ee31771083c81d782de4f52b03b1`, and handoff SHA `6e945dc4a8cc325cd869a04da7bae15d719a90f92dbd7e6e512050e57f07246f` are frozen as preparation; review and a separate root execution plan remain pending. The 14 local controls built no large payloads and made no Docker/SSH/PG calls.

A distinct production FORMATV3 controller is being authored locally by Sol. Actual PostgreSQL/resources, the production-pinned codec fit, complete trusted capture, external origin, corpus completeness and replay metrics all remain UNKNOWN. No release gate, commit, deployment, production capture or origin acceptance is claimed.


### Фактический отказ stage и проверка локального клиента

Exact plan1 прошёл независимое closure review SHA
`490e8fcb5ea973d23835c8f1ca3a9dd61ef70e2a78959a8bfb59c4562e34cd8b`:
1210 source files + release-manifest, все SHA/bytes/modes и source/context pins.
Первое размещение вернуло `STAGE_UNKNOWN` до создания stage. Read-only inspection
SHA `f6187275e3e486dbfc23ea249d12e105c616eb248aeabe3c971f72dc71cf9b6f`
зафиксировал SSH UID1000/GID1002, private700 parents и отсутствие stage-v1.
Original remote stderr старый helper не сохранил; known host precondition
не выполняется. PG/containers не запускались, права и server groups не менялись.
Fresh host harness3 меняет только host predicate и versioned phase import;
container identity1000:1000 не меняется. Independent review SHA
`f8ee44450de239a6600a3dd9d4170dc0b8d0db88524ed353d7897c02a1d7dcab`:
70 controls и independent constructor refusal/diff checks PASS.

Transport2/preserver3 повторно отклонены до внешнего вызова: реальные Windows
entrypoints обращаются к отсутствующему os.getuid. Review SHA
`591b86fe6587b2d1e3321e575dd1b4e2a222ef4b468f123a889ef0432233f12a`.
Plan2 также не запускался. Luna готовит versioned repair: local Windows client
без server-only guard, remote stage/launcher сохраняют observed1000:1002.
Source7 и archive10 неизменны; это исправление маршрута, не успешный actualPG.

Codec helper1 review SHA
`1f9efdbf68ba5b365f75b823b3363fb2ad22e1f9cab4704bf79ccb70bd287448`
выдал REJECT по CP1–CP4: hash/use reopen, cgroup stat-size0 reader, потеря
failed-resource facts и неполная one-to-one mount validation. Шесть independent
actual-function fake controls воспроизводят дефекты; actual pressure не запускался.
Sol сохраняет v1 и исправляет отдельный codec2; production controller saved/paused.
M2, origin, полнота каталога и search metrics остаются незавершёнными.

### Actual PG3: отказ до первой стадии; codec3 принят только как подготовка

08.10.2026 root выполнил stage3 (9 файлов) и один запуск exact plan
`f4c2917f2ee8acfbbd37372a8e8642fe4ebdd774a4537df184496b30a2d8f3ae`.
Run `capture-pg-v3-20261008-085511-782ae06cd4412b2d3f776f13` терминальный:
`DIAGNOSTIC_FAIL`, `GateError`, stage reports 0. Наблюдение read-only;
приёмка raw evidence и окончательная причина ещё проверяются. Предполагаемое
несоответствие: installed provider требует совпадения владельца source/reports
с generic fixture worker, а SSH GID1002 отличается от заданного worker GID1000.
Новая ограниченная правка проверяется через настоящие методы provider;
это не изменение production collector/verifier1000:1000.

Первый вызов preserver4 остановился локально до SSH и публикации: retained
sender module не получил `__file__`. Preserver5 исправляет loader и двоичный
режим Windows; независимая проверка и сохранение failed raw evidence pending.
Source7, archive10, старые helpers и планы сохранены без изменений.

Codec3 независимо принят как `ACCEPT_PREPARATION_ONLY`; review SHA
`ad0a3684d8b475a4603b7f33de5b9abd0c87914d290f573802fc40baaab1fdde`.
Закрыт последний CP1: tar читает неизменные проверенные байты вместо открытого
изменяемого inode. Шесть независимых проверок, предыдущие локальные controls
и tiny actual codec PASS. Все 14 полноразмерных случаев, cgroup2GiB fit,
actualPG layout, trusted origin и реальные метрики остаются непроверенными.
Luna готовит отдельный bounded pressure transport; Sol — FORMATV3 controller.

### PG4: exact stage launched; terminal evidence pending

The first PG3 failure is now frozen as evidence, not a product result. Preserved
five-file manifest SHA `bc6ff7acb07c3fff0bc31ae8a5ac03167f482763a799db5907b25829b60de0ba`
and independent review SHA `0f4f119ac095304d80bdbb82b2288b6bb881bb2118902a8ae5d36173c0732d4c`
accept only the recorded `DIAGNOSTIC_FAIL`/`GateError`, zero stage reports and
absence checks supported by that record. The exact guard failure cause is an
independent reproduction/inference; the raw report did not retain path metadata
or an error message. It does not establish actual V3 capture or resource fit.

PG4 exact plan SHA `6c04eb0afb8ede51c2910952e482e2eec0edac5b59fb8128310d21c1ffa7d1b2`,
nonce `03ae4dfd6836f4c38911d478`, run
`capture-pg-v3-20261008-091254-03ae4dfd6836f4c38911d478`. Harness v4 prep review
SHA `d541cd444d1c4fa5adde98e9e041cb40ae6b492b099f1cd0118778da462fc2eb` and root
acceptance retain generic fixture identity1000:1002 while dedicated collector/
verifier remains1000:1000. Independent final-plan review SHA
`f2a8f0dc9cdb3b5f18d243a0ff180175bd21a4407645e92f6fac3024dead8d56`; route review
SHA `12f1300f4a14690b859ec3e4e7d0e16f8fa8b0c65e866781f9139801d3e94f36`.
Root acceptance SHA `68b7e4082e25771354df00f8390c9f244e465b25ddf257033db623aaf6f6ceef`
authorizes this one exact synthetic run only. Stage proof SHA
`fae89214b3b76ed4a4a3fec31fef4458efc84cc691d8178e6babcb96a899756c`
records nine staged files at
`/home/syurai/vibe-seller-state/improvement-m2-20261007/capture-format-v3-pg-v4`.
Dispatch receipt SHA `c98388d245775a944d9bd75a450f0dbfdeb6e0f5c88b3ef58255f5aa67d6ed62`
reports PID 4000087. A later read-only observation found diagnostic-result SHA
`f7aeecec04cc2478e032943f36c2a3346c36adebf9ef01fde583052e4525258e`, status
`DIAGNOSTIC_FAIL`, after runtime, PostgreSQL, Python-runner and memory-bound stages.
Completion remained null while fallback cleanup was finishing. Raw audit and
cleanup completion are pending; no failure cause is inferred yet. Capture,
resource-fit result and benchmark metrics are not accepted.

The codec-pressure candidate is now a distinct root-created execution plan:
SHA `64e607ce90d0ef24de857d9b208c7b277d3168835bd5618d0c132c25451865ae`, run
`codec-pressure-4f316d6d7b9cf6d499d9d6ef`, fixed 14-case set. Luna's local
transport handoff SHA `4c05d42ec8373c196c2b5e9bcb8e9451dfb998eabbbfa987f00cd8cfe8d1fed0`
binds a separate externally pinned wrapper. Independent review SHA
`a79344a8977c60f0bc791e777a28050fb95cffd0ec5732efc676e56ea6ceb4bf` rejected
transport v1: CT1 inspects the container ID before removal; CT2 null case-result
entries can raise `AttributeError` before cleanup/completion. No codec pressure
run was staged or launched; a finite transport v2 repair is required. Actual
14-case execution and 2GiB/no-swap fit remain UNKNOWN.

The separate production controller review SHA
`b32d9118b337acd7fc240654b8612303e86a15a570452e96653e6a24be19ec99` rejected v1
on PC3-1 abnormal-exit cleanup, PC3-2 reopening the runner after hash check, and
PC3-3 scratch inode registration after fallible operations. Sol is preparing a
finite v2 repair; there is no production-ready controller. M2 remains incomplete:
trusted corpus, origin, complete EIS coverage, replay and quality metrics are
UNKNOWN; M3–M5 have not started. These doc updates postdate archive10 and are not
claimed to be included in that archive.


### PG4 terminal audit; source4 fixture repair and archive11 preparation

PG4 completion SHA `66b8fcbae5020a52a8ba2d9763770238032f8622ef82f5882a2ead123b94e99d`
is terminal FAIL. Ten raw files preserved, manifest SHA
`bded8fb5b88bb69ff73950e8a38f1c942f92fa49b2fb250adfe484c902858f95`.
Independent review `069f5d1cff349b219e49ba31d4b04510e709db8cfef0fcae9b1721542ed0b210`
accepts failed evidence and recorded cleanup only: two tests, one failure, zero
skips; four exact owned resources removed and final inventory empty. The optional
large synthetic 223 fixture retained old nested document references after changing
its document SHA. The actual domain validator correctly rejected it. Dedicated
V3 collector/verifier layout, memory and SQLite stress evidence were not reached.

Only the managed integration fixture was repaired: recursively rebind provenance,
give generated attachment facts their selected-family field locators and retain
actual model validation. Synthetic data is not official XML or origin evidence.
Source4 handoff SHA `e04d9089bee96995271fc84e046440f50183290091c8d8f4a7c9b98af5db21dd`,
independent review `9f84f5bcd93369a6a3ae21dca4d6b4ba0d8946520b116f93e7d1301c711ae9d0`,
root acceptance `8355cfa09be8baef71f8aabcad3305c2fa20b8fcd091b6bb7f68747ced7447ba`.
93 scoped tests PASS; independent controls check 19,524 provenance nodes, original
immutability and three stale-reference refusals. Six other frozen files are unchanged.
Local raw JSON proxy 7,025,000 bytes is not an actual PostgreSQL width measurement.

Archive11 SHA `ee9334870bd346247644221e9f1e591416eedb6c014ca3e4727b8d12b7462ff1`,
proof2 SHA `0d1371cc7a022e3a8371402272a6316145edaccbee6c4c7e9f2fced000f66064`.
Root checked all 1,210 member digests/sizes/modes and exact 1,211-member closure,
curated7/legacy4/context4 and manifest binding. Fresh PG5 helpers are preparing;
no fresh actual run or layout acceptance yet. This note postdates archive11.

Frozen codec transport2 is under independent review; an embedded remote-program
indentation error prevents staging. No actual 14-case pressure run occurred.
Production controller2 finite repair has local checks and awaits exact archive11
binding/freeze and independent acceptance. Origin, resource fit, benchmark quality
and full EIS coverage remain UNKNOWN; M2 is incomplete.

### PG5 ordinal11: staged and launched once; terminal result pending

Root accepted one exact synthetic run after independent plan and route review.
Plan SHA `b2640b3a863d58c31f31279292fc59607d7798cdb44862993d7704e5da57d185`,
nonce `1df21976193b517aec297061`, run
`capture-pg-v3-20261008-094044-1df21976193b517aec297061`. The plan review SHA is
`b8bbcfccf45c98c145e7ceaca7ba16395eef167402fa010d3e48dfb5f5ab21b0`; route
review SHA `ac0f9c1c06de8804cd67f802555b048024c64c22956782c91df6fc9ecb7546f3`.
Root acceptance was limited to this one run, with no production access.

Stage proof SHA `55c1b1651d61acee56b34e49a4851adb5a28525a7c6f53a27c09b9574c3b46a8`
binds nine staged files, including archive11
`ee9334870bd346247644221e9f1e591416eedb6c014ca3e4727b8d12b7462ff1` and proof2
`0d1371cc7a022e3a8371402272a6316145edaccbee6c4c7e9f2fced000f66064`. Dispatch
receipt SHA `e25e77693ad1bb5fe7043d0c4855d03015c0081b6af5be9d29ebb92d5ae8e002`
records launcher exit 0 and PID `4031510`. A later read-only observation reported
`RUNNING` and files for runtime prerequisites, PostgreSQL start, Python runner
start and the memory-bound stage; diagnostic result and completion were absent.
File presence and launch receipt are not terminal or full-stage acceptance.
PG5 outcome, stage coverage, memory/layout fit and cleanup remain UNKNOWN pending
terminal evidence and review.

### Status snapshot before PG6 acceptance and codec dispatch — 2026-10-08

PG5 ordinal11 ended terminal `FAIL / CONTAINER_ENV_UNEXPECTED`. Independent failed-
evidence review SHA `2869adb768dfb2618f1ff6f95199ca4aa10915f14db425cf9c9a7fd41f9a04b6`
accepts the two PG tests PASS, nine completed stages, removal of five exact owned
resources and final empty inventory. It does not accept the failed run as a PASS.

PG6 plan SHA `5659792cec9cfd6dbce9ce242fdfdd13efa8812df14db2f21bae1bacc2ac46fd`;
the terminal diagnostic reported `DIAGNOSTIC_PASS` (diagnostic SHA
`119ce87d71012f035e14dd6a951346bdef2a62fb816310d3dd083fe3dcbe28d4`, completion
SHA `b153ae4844c429530a719e1a7c7724f8404f13a42b621d5d8fea75d99161db44`). The
root preservation attempt stopped before SSH with `LOCAL_PLAN_IDENTITY_INVALID`.
Therefore raw terminal evidence is not yet independently preserved, and actual
layout, memory fit and cleanup remain unaccepted.

Codec transport3 handoff SHA `ed353f93b61df4c768990a12967e796a67008683dbba3155740361a52704a339`,
execution plan SHA `43024c3c6667ab4142180c9d1cd85e1b170f77ca398b0aa0f299cbc49c52176f`,
wrapper SHA `a840075aa96dbe81ac475764feb0bfdd358c90f0875ae490eb9e60802e9a0533` and
supervisor1 handoff SHA `e4fa3dad7774762ee27ac94c74a43a5e4e9a5580668bfd0f61e7452dae8a7166` are
accepted preparation only. The 14-case codec run is NOT_RUN. Publisher1 review SHA
`23003989438a0cc51ab78e9a067d5279de122e850766eaf76b6808624e0c45eb` rejected its
bounded local reader; repair2 is active. Observer2 review SHA
`e3476e718df55a0953087ad493c792379fd42f83a9f2e58923b0324732607c8e` found an
early-record canonicalization gap; observer3 handoff SHA
`c1b7220432a1ba6cefa2fa677f2ad8c474ab845d3fd6aeafe7d87b62c516ab53` records 19
local tests PASS and awaits independent review.

Production controller3 preparation review SHA
`624ebf4751c7dbb086bba1e8a2a18dbf1464fb5307704460cb928e27d8a56370` is accepted;
no actual plan or capture has been created. Full EIS coverage, trusted origin,
replay and quality metrics remain UNKNOWN. M2 is incomplete; M3–M5 have not
started. This documentation update postdates archive11 and is not included in it.


### PG6 acceptance and codec3 T01 failure; snapshot before codec4 dispatch — 2026-10-08

Root accepted one bounded synthetic PG6 run only. Plan SHA `5659792cec9cfd6dbce9ce242fdfdd13efa8812df14db2f21bae1bacc2ac46fd`; independent local evidence audit SHA `eba3ad17861b1846ca7db14f436973e8587a04c4860ed3857ea3dbb685619e21`; root acceptance SHA `71c24b4a4a4db94de3c06fd24598ce8c239549459d289301cabb8a2ea3e36b2b`. Preservation receipt SHA `fc6245fa746d17bf7e3199341131912cee81fe36bf84b8a5ae1aa17fbba9e3b7` binds the terminal diagnostic `119ce87d71012f035e14dd6a951346bdef2a62fb816310d3dd083fe3dcbe28d4` and completion `b153ae4844c429530a719e1a7c7724f8404f13a42b621d5d8fea75d99161db44`. All16 present allowlisted byte hashes match; four absent optional/allowlisted reports are enumerated. Ten stages PASS/exit0; two executed PG tests PASS with zero errors/failures/skips.

The dedicated collector and verifier configurations were identical before/after execution for container/image and sandbox facts. Both used the pinned image, 2GiB memory, zero swap and a 64MiB scratch tmpfs; collector cgroup peak was 510255104B and verifier peak 425537536B, with zero OOM events. Verifier SQLite was configured PASS, closed its connection, retained file identity and reached 195891200B (`47825 × 4096`), above64MiB; package verification matched the manifest. Six exact owned resources were identity-verified removed; final and fallback inventories are empty with no cleanup errors. The scratch same-inode removal is harness-reported; the preserved set has no independent post-run host syscall trace. The seeded data is synthetic. Official source origin, source raw-width attestation, trusted corpus, search metrics, production fit and full EIS coverage remain UNKNOWN. This is not a full release gate.

Codec pressure preparation was accepted only: publisher2 review SHA `43367ad49075e154a9514d01c166304f8b7a468c301f8480a871469c8589b735` (14 author controls/5 independent controls) and observer3 review SHA `32500a7873307b5a8d1e7e5df1d7564e80a43ad13c29fce1dfaa7a1e672c2c44` (19 tests/10 independent controls). Exact execution plan SHA `43024c3c6667ab4142180c9d1cd85e1b170f77ca398b0aa0f299cbc49c52176f`, wrapper SHA `a840075aa96dbe81ac475764feb0bfdd358c90f0875ae490eb9e60802e9a0533`; stage receipt SHA `c5777bc22df5ed6fb5cc2fa19ee64f030194632dc19b4eb68bc2ccf217a5c191` and dispatch receipt SHA `4f96dd7dfd275b6621a89fdaf16895e1a2605a14336762af369fac37ac315a3f`. The one dispatched run `codec-pressure-f71b39496ca5fdfca203ce31` (PID `4077576`) terminated immediately at T01 `CONTAINER_SANDBOX_REFUSED`, runner exit2 after about993ms. Root preserved six JSON files plus manifest SHA `b93ddc01502b01e94bd07635a7cee3b241320dda89a527e6d05f8e003f412c86`; independent failed-evidence/cleanup review is pending. No encode/decode or heavy-pressure observations ran, so codec resource fit remains UNKNOWN; no root cause is inferred.

Production controller3 review SHA `624ebf4751c7dbb086bba1e8a2a18dbf1464fb5307704460cb928e27d8a56370` accepts preparation only; no actual production plan or capture exists. M2 remains incomplete; M3–M5 are NOT_STARTED. These documentation updates postdate archive11 and are not included in that archive.


### Codec4 preparation and dispatch snapshot before terminal review — 2026-10-08

PG6 remains accepted only as the bounded synthetic run described above. Codec4 uses the fresh run `codec-pressure-8722208314c55547cfae5ca2`, execution-plan SHA `492b7e9d9229bde77585f82cd91a5a2bfc97256011b418add30e53127f237b8f`, transport-wrapper SHA `3e2c8a30dd8a2a7d4b37b8ad7d4894c731e698c538487eeb06129646d08455d9`, runner SHA `812885f6b006f14294c30609efb8ca7f520b2be632019355f93120ec81c46839`, launcher SHA `84283747f21a1b583bf67b5935bd17b12f44981413ce05df88ec0524c3061651` and supervisor2 SHA `713b79b2c6d41f6688d441ea0acdf3946870f5794b051ddb62ed6f4ea8d40c25`. Root acceptance SHA `eb50003bd89b86ca9d921d88cf35b1284ea2e0de82a8451a7394f1dfa26af199` is for exact supervisor/plan preparation. Runner4 review `c217371651aa99012d3da576cede6dac5fcd78cba57e02f74247de7a719bbcfa`, transport4 review `511f9ca342c2ae76174394bf3fba637e0e57985be94edd362b674585b9e0faaf`, supervisor2 review `7c51f5cada607a39d49da6ad12d30d5e3d9d404bda7193668037a6c89033e361`, plan review `cb43e84922efd085b91f2d8f7d0947063c7e372bc51d3f850f8f7d80a16d4933`, publisher3 review `e7a016db6d416b8ae335c04c7f6317b2ee9665f297d091b4af511f198517f65a` and observer4 review `a2c3badceb71ac5cde760b089f169c4e66f5612cf6a500875359c5a752b9f166` accept preparation only.

Root's stage receipt SHA `915cd41f83b00060610d886c397c6b9ff4293a4152f0aa469a356b102fce162f` records seven exact files in fresh `capture-format-v3-codec-pressure-v4`; dispatch receipt SHA `9e38975fb1eda9f5fd112d3367ef73dd41246b77042b7c7cdaf61dff94bab732` records one dispatch, PID `4094237`. At this update the actual run result, memory fit and 14-case outcomes remain UNKNOWN; do not infer a result from staging or dispatch. The runner repair is limited to the exact four inherited plus three owned image labels; the 14-case formulas, caps, archive10 and six production source modules remain unchanged.

The preceding run `codec-pressure-f71b39496ca5fdfca203ce31` remains an early T01 `CONTAINER_SANDBOX_REFUSED` failure; review SHA `3d3a1d49675afb9bd064f0b32a0504cbc00e3af98b84b2a4cbb0bda2e5764c3a` accepts failed raw evidence and recorded resource absence only. Image-label evidence SHA `0b6f0a75a2d842612eb3367cfd4d341b9ee61a488bef644160f40b383ba3070d` and interpretation SHA `f1932de48c7d674d47c42bab69e17154a9bb318fb8268dd803eb66463ab40613` support the label-guard mismatch; the removed T01 container's bad inspection remains UNKNOWN. A separate worker-unstarted config probe SHA `640d5b4dfff8d2639a522631000a954ff12f37d4525466bf796140da90c4fed4` observed exact `no-new-privileges` and `/tmp` tmpfs settings and clean removal. Its `command_matches=false` flag used the wrong eight-label suffix against the seven-label expectation, so it is ignored and does not establish command drift. No cause beyond the reviewed evidence is inferred.

Production controller3 remains preparation-only (review SHA `624ebf4751c7dbb086bba1e8a2a18dbf1464fb5307704460cb928e27d8a56370`); no actual production plan or capture exists. M2 is incomplete; official corpus/origin, search metrics, production fit, full EIS coverage and replay remain UNKNOWN; M3–M5 are NOT_STARTED. This documentation update postdates archive11 and is not included in it.


### Codec4 terminal INCOMPLETE; bounded failure evidence only — 2026-10-08

The one dispatched run `codec-pressure-8722208314c55547cfae5ca2` (PID `4094237`) terminated INCOMPLETE; runner exit2. Preserved raw manifest SHA `9253177965f744cb78a9851b33e6c90f11697d4c7f9b78138acf403f4312ec4f` binds the six JSON records; independent review SHA `073ae862e5dc3d64681a6ce3cdbf2fe6a3c95a26fa7b57459d9b97ba6e9b6af9` accepts partial failed evidence and recorded cleanup only. T01 completed a 772-byte small roundtrip (peak 77,901,824B, no OOM). T02 is UNKNOWN: `PIPE_DRAIN_INCOMPLETE`, encode/decode result files absent; retained observation reached 992,169,984B under the 2GiB limit, with zero OOM events observed. T03–T14 were not executed. No large-row codec acceptance or production-fit result follows.

The failure cause remains UNKNOWN: a nested drain branch masks inner timeout/overflow facts, while the outer runner timed_out=false is separate. No timeout or OOM cause is inferred. Launcher and supervisor fallbacks each recorded zero exact owned codec containers before/after and removed zero; this is not a global host-resource absence claim. PG6 remains accepted only as a bounded synthetic diagnostic/layout/cleanup run. Production controller3 remains preparation-only; no actual production plan/capture exists. M2 remains incomplete; trusted source origin, corpus, search metrics, full EIS coverage and replay remain UNKNOWN. This documentation update postdates archive11 and is not included in it.


### Source5 streaming code preparation; archive12 closure pending at this snapshot — 2026-10-08

Source5 is accepted for code preparation only. Author handoff SHA `a77fa55fdd6b20ea514518fbad5ff76dd97842c22338dd15368e854a67bf0da0`, independent review SHA `e42a425bf93d62667f61c459fe6ad606495cd8338489a8a4745a91f3c3983e59` and root acceptance SHA `edad306f7b090df50805741922ddf9188d38ce7a5809219b28945c5b2123638d` bind the source5 result. The bounded scoped suite reported 99 PASS; independent review verified seven new regressions, eight focused existing fault regressions and eleven direct actual controls. Canonical output bytes and limits are unchanged; chunks are at most 65536 bytes, while typed-tree materialization remains eager. No total-memory or actual-fit guarantee follows. Ruff passed; source-format check remains non-PASS as on archive11 baseline, so no new format-pass claim is made.

Archive12 `capture-source-12.tar.gz` was constructed once, SHA `e68d69f1b386c41f03078e2d44d5bb2b2651e2c69d7b209dc190edc21e605f9b` (1211 worktree files); proof `capture-format-v3-pg-source-snapshot-v3.json` SHA `aaf3029cd656ef39ca46b5bce91d478b34b2a0e5b906f4d38a16f1ab74f9bd42` records eight curated source files, four preserved legacy plans and four context-document pins. Root closure review is pending; this is a whole-worktree snapshot, not an eight-file archive. Actual repaired PostgreSQL capture and codec14 run remain NOT_RUN. The prior codec4 T02 `PIPE_DRAIN_INCOMPLETE` cause stays UNKNOWN and is not relabeled by source5. Production fit, capture origin, trusted corpus, real search metrics and full EIS coverage remain UNKNOWN; M2 remains incomplete and the release gate closed. This documentation update postdates archive12 and is not included in it.


### PG7 bounded synthetic diagnostic accepted; codec5 dispatched — 2026-10-08

Source5 code preparation review SHA `e42a425bf93d62667f61c459fe6ad606495cd8338489a8a4745a91f3c3983e59` and root acceptance SHA `edad306f7b090df50805741922ddf9188d38ce7a5809219b28945c5b2123638d` remain preparation-only. Archive12 SHA `e68d69f1b386c41f03078e2d44d5bb2b2651e2c69d7b209dc190edc21e605f9b` closure was accepted by root SHA `03269ffb3a9bcf42596f85265ed1faa28dea305c5411547517fb9201e390b7dc`; it is a 1211-file worktree snapshot with eight curated source files, not a production capture.

PG7 actual synthetic run `capture-pg-v3-20261008-112125-4ba6586045bfb6f5b79ea27b` used plan SHA `f119e91864c28bfa5ca375b2f307705cdb31f35e9bbd2723d8b180a6af9065fc` and preserved raw evidence SHA `d87dde87664cbcd2538e67890e3072b04a023e6441842691510bde99642f3441` (16 files). Independent review SHA `106f937101ef44733b9500483f48136d0b7a81c08353d32cc2eecb5a6be610c5` and root acceptance SHA `b768bc62b9e8da9e29ff413986e5c706f43ff929c7e93d44e60b5abfcbe3bd6e` accept bounded synthetic layout and recorded cleanup only. Ten stages PASS/exit0; two exact tests PASS with zero failures/errors/skips; JUnit duration 111.803s. Collector/verifier ran 59.337s/14.440s with cgroup peaks 510783488B/425926656B; verifier SQLite reached 196059136B (47866 pages), above64MiB. Six exact owned resources were removed; final and fallback inventories are empty. Both dedicated roles used the pinned SQLite runtime, 2GiB memory, zero swap and 64MiB scratch tmpfs.

Review scope is bounded: five referenced raw outputs/logs were not copied for independent rehash, payload bodies were not all locally re-read/decoded, and secret removal is inferred from the frozen producer cleanup path. This synthetic run is not a full release gate, production fit, or trusted-origin evidence; corpus, source origin, search metrics and full EIS coverage remain UNKNOWN.

Codec5 plan review SHA `0c1e07f3690f2d01a8694ab87f0ff9adabfe9cbf72d191b36c4fa828b57323c9` accepted exact bindings for preparation only; root supervisor/plan acceptance SHA `43144ec8d711286ce3cb3848c595cb9c86866ab609a14954e01591f15d2b5e3b` binds the run. Execution plan SHA `275f2ae15098e73fbf1b80c92bf218fc1f5814c351707215dda09976ba7b51ba`, transport plan SHA `d416ee4bd0a2032795dfc8fc26c7d9a9fc0acbfaff68e98fbd483c549229c5f3`, supervisor SHA `c568c9931aaecdac4e56a8f8eaef6b082429313eec733b672ae7e3bd2d1a9157`. Stage receipt SHA `943131008e428befe296fbfac71ca014618dd744ca80874633e794206ec7dc12`; dispatch receipt SHA `763dee112c257c852a8db28f0759f5f446336d834c9939674d5dfe1969ee6825` records one dispatch, PID `4166123`, run `codec-pressure-813defa947f3e133266be43c`. At this update, terminal status and all 14 case outcomes remain UNKNOWN; no retry or cap increase is claimed.

No actual production plan or capture exists; the production gate is closed. M2 remains incomplete and M3–M5 are NOT_STARTED. This documentation update postdates archive12 and is not included in it.

### Codec5 bounded run accepted; production capture remains gated — 2026-10-08

The single run `codec-pressure-813defa947f3e133266be43c` was accepted for the bounded codec mechanism and recorded cleanup only. Independent review SHA `5b733830ed9a730e31b7d3f2d8ee27a1b7b908c44d5ac774d0f8b79820b0381f` and root acceptance SHA `7a58179474435bdf36741fe820ebf0cb825dc46c76a5bc2c51b29d5a44e44b1f` bind the result; the six-file raw preservation manifest SHA is `c4446eaea445876d1dad8a16db2e462766287ddfead86b2f4d10231423450346`. The run completed all 14 planned cases: 11 roundtrips (T01–T08, T10–T11, T14) and three expected typed refusals (T09, T12–T13). Runner exit was zero in 692,008 ms. Every case reported a 2GiB memory limit, zero swap and zero OOM events; maximum whole-case cgroup peak was 1,838,174,208 bytes, 309,309,440 bytes below the cap. This supports the fixed codec cases only, not a universal memory bound.

The independent reviewer found the successful encoded/decoded byte counts and hashes, fragmentation sizes, typed refusal boundaries and the result's bindings consistent with the frozen plan and source archive12. The raw preservation contains six JSON records, not payload bodies or successful container IDs. Per-phase timings were not persisted. Both cleanup fallback records were `NOT_NEEDED`; they were not separate empty-inventory scans. Cleanup acceptance relies on the reviewed producer execution evidence, not a new live inventory inspection. The run establishes neither a PostgreSQL raw-width attestation nor trusted source origin, product semantics, search-quality metrics, full EIS coverage, or production fit; each remains UNKNOWN.

PG7 remains a separately accepted bounded synthetic PostgreSQL layout/cleanup run. Production controller4 code preparation handoff SHA `49be2eafc56c80af5e9cbad160a5641e1d82de3b267f616ebb515265cf4904bb` and independent review SHA `fa3e031d628b94942c93f0059639cf5a1f05f5eead9353f5c78a2db3b99b290c` are accepted for preparation only. The exact-plan builder2 handoff SHA `a7a092f07039dc28adea05f4540f513d05af45f9956a031373b405e098faeec4` is awaiting independent review; no exact production plan, fresh production facts, stage, or capture exists. The production gate remains closed; M2 is incomplete and M3–M5 have not started. This documentation update postdates archive12 and is not included in it.
### Production4 capture INCOMPLETE; failed evidence and cleanup audited — 2026-10-08

The one dispatched production4 attempt `trusted-capture-v3-b7628c8735cb464af3e14a70` used capture `eis-corpus-v3-b7628c8735cb464af3e14a70` and execution-plan SHA `92c6d86fab5e4f60a1977654ee8207c77235f694b5f6801e0b46a2da75d4f470`. The preserved controller result is `INCOMPLETE` with `CAPTURE_PROCESS_FAILED`; the package-incomplete record says `OperationalError:CAPTURE_FAILED`. The package manifest is absent and verification did not start. The preserved raw manifest `cb6b376be45da80bf71222332541b4320da52c0040256a4f5edf5972ab34edda` binds seven available metadata records and three missing records (`package-manifest.json`, `scratch-identity.json`, `verification.json`). No retry was made. The partial package is not a complete corpus and cannot be used for benchmark metrics.

Root published the exact cached terminal envelope in `production4-cached-terminal-publication-v1.json` (SHA `6237bbcd39ee37dbe8460fa70964b16bceecbccdadc8df16268d9b38a4138659`); this was a local cached publication with zero additional external calls, not a new remote observation. Independent preserver review SHA `3d30d810e7ad35bbc2e660fa5260cee470268983b096d678a6d851645f4fe02b` accepted cached terminal metadata preservation only and confirms the earlier v2 refusal was due to three format literals that disagreed with the frozen producer; corrected v3 validated the seven-record envelope. Independent failed-run review SHA `165953d992c6b4f7d2972fd7d6d71d777df7497599c9e3a98038b05b31ed65a5` accepts failed evidence and recorded cleanup only. The observer reports 137 physical payload files / 944,827,770 bytes; those payload bodies were not independently preserved or rehashed. Collector exit2/controller exit1, no verifier start, and seven exact raw records are corroborated. Whole-cgroup peak was 1,142,669,312 bytes with zero OOM events. Exact capture-container removal is recorded; the original envelope readback also found empty owned inventory and absent credential/scratch/journal. Cached publication does not refresh those observations.

The bounded SQL `FETCH` timeout is log-window corroboration only; its causal link to this `OperationalError` is UNKNOWN. Exact cause diagnosis remains next. Capture origin, trusted corpus, production fit, search metrics and full EIS coverage remain UNKNOWN. This failure does not change the separately accepted codec5 mechanism run or synthetic PG7 result. M2 remains incomplete and the production gate stays closed. This update postdates archive12 and is not included in it.

### Source6 rejection and Source7 bounded timeout-result repair — 2026-10-08

Source6 independent review SHA `3e1416844651b0b4c7c5ec00a8afae52fe43eadb8f1f0d64195a962a56907f4c` rejected readiness for fresh PG on S6-1: the timeout-setting SELECT inherited streaming options and left its results unconsumed/unclosed. Exact16 Source6 files remain retained outside the managed checkout. This is a confirmed local lifecycle defect; it does not establish the cause of production4's historical failure. The separately observed EXPLAIN DECLARE supports a narrow-key sort followed by indexed late payload lookup for that session only; it is not runtime or production-fit acceptance.

Source7 handoff SHA `104969ed3ec8f645da2eaedc02f00b460dc17dfdff84ce0d47b0401ae0a71dd6` binds the V3-only repair: per-execute `stream_results=False` and `yield_per=None`, scalar consumption and explicit close, without changing the live payload connection options. A typed internal wrapper preserves the first safe failure when secondary close also fails. V1/V2, canonical codec, SQL selection/order and all resource/deadline caps retain their boundaries. Four new lifecycle controls failed before the fix; the final scoped suite has 125 PASS with zero skips, Ruff and four AST checks PASS. One existing high-water test fake was adapted to the new Result contract without changing its assertions.

The isolated PG test is extended to call the actual timeout helper repeatedly with a live payload cursor, check stable `pg_cursors` counts, unchanged connection options, an effective timeout and exact canonical byte parity. It is collected but NOT_RUN at this snapshot. Independent Source7 source review is pending. Curator5 and harness6 prep review SHA `41509524cd634c48b175b49d8fceac6dc4a9104197adbe5afdd99cfbe63ab902` accepts preparation for explicit Source7 binding only; the frozen curator default still names rejected Source6 and must not be used. Archive13 is not yet created. Trusted corpus/origin, production fit, search metrics and full EIS coverage remain UNKNOWN; M2 incomplete, M3–M5 not started.


### Source8 preserves the primary diagnostic across cleanup failures — 2026-10-08

Independent review of Source7 confirmed the core timeout-result fix, but identified S7-1: repeated `CaptureCollectionError:` prefixes across timeout-result close, payload cursor close and writer abort errors could exceed the unchanged 200-character safe-message guard and erase known SQLSTATE/backend context. Root reproduced the actual collector failure before the fix. Source8 removes one already-applied safe prefix before reapplying it; the cap is unchanged. The four-fault collector regression retains the first failure and all three fixed cleanup suffixes.

Source8 handoff SHA `2b84e7dbc900d519a820e55be1f983c67e134839ef4d0f137923667daf547482` and exact16 retained files bind this bounded repair. The final local scoped suite has 126 PASS, zero skips (40.79s), Ruff/AST PASS. SQL, codec, isolated PG test, legacy plans and resource/deadline limits are unchanged from Source7. Independent Source8 acceptance and actual PG remain pending; archive13 has not been created. The next fresh preparation must explicitly select Source8 and its accepted digest; neither rejected Source6 default nor Source7 may substitute for it. These results do not establish the historical production4 cause, trusted corpus/origin, production fit, search metrics or full EIS coverage.

### Source9 isolated PostgreSQL verification of the Source8 SQL — 2026-10-08

Scope: verify the existing repair and decide readiness for a fresh working-snapshot
plan; no production capture, commit, deployment or M2–M5 implementation. Root owns
the PG fixture, bounded run identities, this evidence/live status and handoff;
Astra is the single independent reviewer. The Source8 storage SHA remains
`3f7f75a9afd097bf1c63491afe5b9b8fac9171191da4db3295cb68f8277999b6`.

PG8 used exact Source8/archive13 and terminated with 2 PASS, 1 FAIL, 0 skips.
The new equivalence test failed before schema/query creation because the pinned
PostgreSQL Alpine image lacks `en_US.utf8`; both existing capture tests passed.
Its 11 preserved raw files and four-resource cleanup remain retained. This is
a fixture/environment mismatch, not evidence that old/new SQL differ.

Source9 changes only `tests/integration/test_eis_capture_ordered_payload_pg.py`:
choose an installed deterministic UTF-8 English collation from the exact
`en_US.utf8` / `en-US-x-icu` allowlist and refuse if neither exists; prove its
native order differs from explicit C, use actual Unicode keys and persist JUnit
observations. All other15 frozen files, SQL, wire bytes, legacy/V3 plans and caps
remain exact Source8. Handoff SHA
`58e083a93f16662e5aed05b1c625852baffdbbdadc3ce7dceb1ceba229f2e556`;
PG-test SHA `63db501392958687d05cf7e00a88452890418dbc7bc017843ebe9d5575cc1337`.
Existing curator5/harness6/phases4 were reused. Only fresh stage/launch/observe/
preserve identities were cloned after the reproducible failure: prior archive,
stage and launch paths are exclusive and must not be overwritten. Existing
retargeted transport47 and preserver19 controls passed (one existing Windows
FIFO skip); no new tool behavior or resource cap was introduced.

PG9 run `capture-pg-v3-20261008-142837-6a5ae9dff8bcb6f2c34e9236` used archive14
SHA `cae58580d184faf235eda7460f3c73e41406c906522d9e65cab3bb8871f1e20d`,
proof5 SHA `d661cac3f3b1a464ec8266b60b3fb45b6e18ee6eadff543ccba4b842ad1113b5`
and exact launch-plan9 SHA
`228fbb4e052645892fa58f035c72a1d82848a308a8078ecbf3bd1dcc84a33d1d`.
The same reviewer accepted exact Source9/plan9 preparation. Existing harness6
executes both PG modules with `--require-postgres`, then public V3 capture/verify.
All10 stages PASS/exit0; terminal `DIAGNOSTIC_PASS` and collector/verifier exit0.

| Actual isolated PostgreSQL observation | Result |
|---|---|
| PostgreSQL / fixture locale | 16.15 / `en-US-x-icu` |
| Executed PG tests | 3 PASS, 0 failures/errors/skips, JUnit114.409s |
| Old/new ordered equivalence | Exact16 canonical rows; SHA `1378fdf374fc853eb4665fd2ed7704cf7fac63c0716554b0343cc788c1566577`; both EXCEPT ALL directions empty |
| Tenant/snapshot | Own16/foreign16 fixture; forged foreign selection empty under non-bypass FORCE RLS; concurrent committed update invisible inside RR and visible afterward |
| Timeout/service cursor lifecycle | Three actual helper calls with live payload;30s effective timeout; unchanged connection options; portals1 during read and0 after close; full payload byte parity |
| Dedicated V3 package | 25 relations,18115rows; each source count equals captured rows;292004849B payload/63data files; maximum physical file8388608B |
| Large-row cohort | 8 audit rows raw9602440B/encoded10602694B; ordinary44 raw6419955B/encoded9780760B and223 raw7025339B/encoded9648689B; fragment roundtrips match seed hashes |
| Capture / offline verify | COMPLETE59.412s / CAPTURE_CONTENT_VERIFIED14.589s; reasons empty |
| Whole phase cgroup peak, PostgreSQL excluded | Collector497979392B; verifier423694336B; each cap2147483648B, swap0, all OOM counters0 |
| Transient SQLite/pending | Membership495616B; pending10602694B; verifier195919872B (>64MiB); closed and removed under existing caps |
| Cleanup | Six exact owned resources removed; final/fallback inventories empty; secret/scratch cleanup PASS |

Existing limits remain: batch<=8/64MiB raw, ordinary8MiB/audit32MiB raw,
encoded row64MiB, physical8MiB, payload4GiB/512files, metadata16MiB,
1Mrows/relation, capture900s, PG statement30s/lock1s, RAM2GiB/zero swap and
tmpfs64MiB. This bounded run does not stress every maximum simultaneously.
The package manifest SHA is
`eb77e254917e7b1ddc9fe5c17b5d7d7953a99b38262f4bc9e9d344186fb3e513`;
verification SHA `463d0d4d0906dd4443aca777c193eef7560ec81c1f4a444b94857b4de24b3a83`.

Raw16 preservation is under primary-workspace
`tmp/improvement-program/m2/capture-format-v3-pg-preserved-v5-6a5ae9dff8bcb6f2c34e9236-228fbb4e0526/`;
receipt SHA `8736c7dd2ff71362defe47f25c954b596a14fdfc49573dfd7ecae64538689e48`.
Root rehashed all16 preserved files and all16 current Source9 pins successfully.
Independent final evidence review SHA
`27c084abd889701934df8886b798b28ba6c60d8a8a00bc2e5102329a206e9ca3`
accepts the bounded PG9 result and readiness for fresh exact working-snapshot
preparation, with no blockers. Root accepted this same bounded scope in
`capture-format-v3-pg-root-acceptance-v9.json`; the preparation receipt remains
frozen separately. Local126 tests, Ruff, mypy21files,9doctests and documentation
checks passed; these local checks do not establish a successful working export.

Readiness is limited to preparing one fresh exact production capture plan.
No working snapshot was attempted here. Actual
production fit, trusted corpus/origin, search metrics, full EIS coverage/replay
and the historical production4 failure cause remain UNKNOWN; the release gate
stays closed and M3–M5 remain NOT_STARTED. Offline raw-width validation remains
DECODED_LOWER_BOUND_ONLY with source attestation UNKNOWN. Raw preservation covers
metadata/JUnit/reports; payload bodies are not locally retained or independently
rehashed here (the existing producer/verifier package seal is recorded).

## Source9 production5: confirmed capture deadline blocker (2026-10-08)

User scope: prepare the exact plan and obtain one complete working-database
snapshot with package verification, or a confirmed blocker; no M2–M5 expansion.
Root owns the fresh execution bindings, evidence, live status and handoff; the
same Astra reviewer owns the independent plan/result reviews. Source9/archive14
and all collector/codec/SQL/plans/caps remain unchanged. Accepted PG9/codec tests
were not rerun.

Existing controller4 hardcodes archive12/source5; its exclusive stage/run paths
were already consumed. Production5 therefore uses six mechanical identity/hash
rebindings of the existing controller/launcher/stager/dispatcher/observer/latest
preserver. Existing builder2 pure `_plan` constructs the plan; its historical
Source5 dependency validator was not relabelled as Source9 acceptance. Fresh
read-only target facts, Source9 archive16 pins, unchanged archive12/14 encoder,
exact replacement bytes and wrong-tenant/archive/memory refusals were checked.
Independent final-plan review and root exact acceptance preceded one dispatch;
stage readback16 inputs matched their digests. No grants, migration or deploy.

Run `trusted-capture-v3-b192ae9787d2ece2750bdc85` uses archive14 SHA
`cae58580d184faf235eda7460f3c73e41406c906522d9e65cab3bb8871f1e20d`
and execution-plan SHA
`c90c6b554e4f98dd3fd0c19aaebd6b85f5ae824b005c4f773170d7e82f05ea27`.
The actual target is the separately pinned running production API/PostgreSQL,
database `procurement`, tenant `local-eis-supplier`, role `procurement_app`.

| Actual working-database observation | Result |
|---|---|
| Snapshot result | **INCOMPLETE**, capture exit2; controller `CAPTURE_PROCESS_FAILED` |
| Confirmed cause | Typed `CaptureCollectionError:CAPTURE_TIMEOUT`; global collector900s budget exhausted; outer controller did not time out |
| Partial payload | 3080666909B,396 physical files:385 JSONL +11 fragments;23 of25 planned relations represented |
| Partial row accounting | 434829 counted JSONL lines in21 relations; not semantically verified or a complete row count |
| Missing count authority | Fragmented audit/223-notice rows deliberately UNKNOWN without terminal descriptors; procedure-events/sync-targets unrepresented, not proven empty |
| Terminal package check | No COMPLETE manifest, package seals or verification report; offline verifier NOT_RUN |
| Time | 909.119246s from launch to terminal transport completion, including startup/cleanup; exact collector phase duration not instrumented |
| Cgroup memory | Peak2003963904B (1.866337GiB), cap2147483648B; swap0, all OOM/max counters0 |
| DB isolation evidence | PostgreSQL16.15/schema20261006_08; DB transaction clock; snapshot `119862:119862:`; READ ONLY/REPEATABLE READ; RLS on; non-superuser/non-bypass app role; exact tenant setting |
| Transient state | Membership last observed12496896B, closed/removed; pending peak18904529B, removed; cleanup PASS |
| Cleanup | Exact capture container removed; final/fallback inventories empty; credential/scratch/journal absent; API/PG still running |

The source `_PackageBudget` emits this fixed reason only when its global
monotonic capture deadline expires. This is not evidence of a PostgreSQL30s
statement timeout, OOM, payload4GiB limit or physical512-file limit. The timing
split between SQL/fetch/encoding/disk remains UNKNOWN. No speculative source
change, cap increase or second capture was justified or attempted.

Seven raw metadata files were preserved and rehashed in primary-workspace
`tmp/improvement-program/m2/capture-format-v3-production5-preserved-v1/`.
Preservation-manifest SHA
`c3a8b4544e4a277515f067a7d2c08f4a831b2904ab9ce3b1b9008ad9356f3581`;
typed incomplete-record SHA
`d6937e762063801a948f1ef6e9d7b7c619fe5b4bf7777ddd8ad248a69ce25e6f`.
Exact partial composition, runtime/cgroup/cleanup and limitations are retained
in `capture-format-v3-production5-confirmed-blocker-v1.json` in the same m2
evidence root. Partial payload remains private on the remote output path; it
has no terminal manifest and must not be promoted to a verified corpus.

The requested snapshot remains **INCOMPLETE**; the alternative outcome is a
confirmed900s blocker. Next action: agree an explicitly smaller working corpus
and its separately reviewed exact scope under the same900s/2GiB limits. This is
a scope proposal, not an executed subset or a complete full-tenant snapshot.
Working content/origin acceptance, production fit, replay/search metrics and
full M2 remain UNKNOWN/incomplete; M3–M5 were not started. The historical
production4 failure cause remains UNKNOWN.

Production5 actual-result review SHA
`e1f1153517aa4eeec111914c0731030af151ee1fe31bc7664994c172c0925c34`
accepts the failed-run evidence and cleanup, with no new diagnostic/cleanup
blockers. Root records this bounded decision in
`capture-format-v3-production5-actual-root-acceptance-v1.json`; it does not accept
snapshot content or origin. The prior handoff is preserved and current handoff
now stops at the confirmed blocker. Local acceptance and remote launch wall
clocks differ: cross-host chronological order is not attested by timestamps;
the reviewed dispatcher enforces acceptance before dispatch. The909.119246s
interval above uses only remote launch/completion timestamps.


## Production6 full-scope resource revision — 2026-10-08

The user explicitly superseded the production5 smaller-corpus proposal and
approved one full25-relation capture with3600s/4GiB, sequential offline verify,
and16GiB/4096 physical payload files. Row/block/batch limits, tenant scope,
read-only REPEATABLE READ/RLS and relationship closure remain unchanged.
Source10/archive15 changes only the resource profile and its enforced deadlines
and disk admission; accepted Source9 SQL/codec/PG9 mechanisms were not rerun.
The resource contract and rationale are recorded in
[contract119](119-eis-capture-v3-contract.md) and
[ADR0109](../../adr/0109-bounded-eis-capture-v3-state.md).

Affected checks:8 targeted tests PASS, Ruff/mypy PASS; controller memory/cgroup,
profile-matrix and negative-plan controls PASS. Existing launch route6 retains
exclusive run paths and exact bytes, phase3660s/overall8000s/cleanup300s,
launcher8060s, idle-worker3900s and full-package sealing limits4104files/
16GiB+32MiB. Independent preparation review:
`production6-final-plan-review-v1.json`, SHA
`2a451a4d7d5d75cbe2d145d2d709495238038fcad669b1a9ca65f6520584c7bc`.

Exact execution-plan SHA
`e32d8559ea5ed1047112030cf98001e970ababd5f551aac74f52baa111831492`;
run `trusted-capture-v3-9bb33b5f16d7a85901f3414c`;
archive15 SHA
`a95bcecec6f21fc04a719db2c83ef674b2a119810275b6a19206fd59711192b8`.
Root exact acceptance precedes the one dispatch by reviewed control flow;
cross-host wall clocks are not used to attest chronological order.
Prelaunch MemAvailable6464634880B exceeded required5905580032B
(4GiB worker plus1.5GiB growth reserve); free disk209849282560B exceeded
collector admission23706206208B. The controller repeats memory admission
before capture and, after removing collector, before network-none verifier.
Actual terminal status is recorded below when available.


### Production6 actual working snapshot — COMPLETE

One actual PostgreSQL16.15 capture completed on schema20261006_08,
tenant `local-eis-supplier`, app role `procurement_app`. Transaction clock
`2026-10-08T15:40:01.646377Z`, snapshot `120409:120409:`; READ ONLY/
REPEATABLE READ, RLS on, superuser/bypassrls false. No scope reduction or retry.

| Actual observation | Result |
|---|---|
| Package | **COMPLETE**; independent network-none offline verifier `CAPTURE_CONTENT_VERIFIED`, no reasons |
| Scope/composition |25 of25 planned relations,800444 logical rows:800439 inline +5 fragmented;964 JSONL +13 fragment files |
| Payload |7804849674B (7.268833GiB),977 physical data files; source_count=manifest rows=verified rows for every relation |
| Capture time |2270.772566s (37m50.773s), exit0; below3600s |
| Offline verifier time |369.852240s (6m9.852s), exit0; runs after collector removal |
| Total time |2702.432703s (45m2.433s), remote launch-to-terminal including startup, seals and cleanup |
| Memory peaks |Collector2319675392B (2.160366GiB); verifier2632527872B (2.451733GiB), each below4GiB |
| Resource enforcement |4GiB memory.max, swap0; all OOM/max counters0; CPU1/pids128/tmp64MiB unchanged |
| Fresh memory admission |Before collector6385848320B; before verifier6468935680B; each exceeds5905580032B including1.5GiB reserve |
| Fresh disk admission |Collector209820196864B available /23706206208B required; verifier201952305152B /13975420928B; PASS |
| Transient state |Collector membership37343232B, pending peak18904529B; verifier SQLite720850944B; connections closed/files removed |
| Byte integrity |Full979-file package sealed before/after verifier:7805335565B; identical tree SHA `d9c1b29a5c00a0169ccc423be4ca80b98b85494d4561e5338a4084bebd459473` |
| Cleanup |Collector removed before verifier; verifier/credential/scratch/journal absent at terminal; owned inventory empty; API/PG still running |

Per-phase times are monotonic Docker-exec command durations including Python/CLI
startup. They are not SQL-only timings. Both physical512-file and4GiB payload
old caps would have been insufficient; the approved4096/16GiB profile was needed.
Individual row/block/batch caps were not raised. Current membership:44-law267484,
223-law14027; future versions0/0. Full per-relation counts and physical composition
are in `capture-format-v3-production6-actual-result-v1.json`.

Eight raw metadata files were preserved and rehashed in
`tmp/improvement-program/m2/capture-format-v3-production6-preserved-v1/`;
preservation-manifest SHA
`20e7c730c0974271858c227c94309eef4ecbb6068e70a5b42f467b0e4567b1fb`.
COMPLETE package-manifest SHA
`143e11fa6bf30626fee13c565a16a92229cb2c70c58b341d1cc5fc2204845f38`.
Incomplete record and scratch-identity journal are absent as expected after
successful completion/cleanup. Payload remains private on the VPS under the
exact run output path; local preservation contains metadata, not a payload copy.

The package is complete for the exact planned25-relation corpus, not an
unrestricted whole-database dump. The offline report deliberately retains
`capture_origin_trust=UNKNOWN`, `source_raw_width_attestation=UNKNOWN` and
`DECODED_LOWER_BOUND_ONLY`. External operator origin acceptance requires the
independent actual review and root record outside this untrusted package.
Existing shared collector network is not claimed as DB-only egress. This result
does not establish deployed-code parity, replay/search metrics, full M2 or
release acceptance. M3–M5 were not started; no commit or deployment was made.


Production6 independent actual review **ACCEPT**, no blockers:
`production6-actual-result-review-v1.json`, SHA
`710172c4268c322320737c0f360c7efc25108bc5492736b0ba8929017aab15ad`.
Root accepted exact COMPLETE content and operator origin in external immutable
`capture-format-v3-production6-actual-root-acceptance-v1.json`, SHA
`f2f8d5c26f0fa3aadad9871d5ea4e53d324af4a96de7a9a0678073c6f8da9fd7`.
The anchor binds exact manifest/capture-plan/execution-plan, collector/verifier,
transaction/runtime/schema/tenant, raw execution/audit digest, independent review
and repeated full-byte seals. It is operator trust outside the package, not a
digital signature; raw verifier UNKNOWN fields remain unchanged. The earlier
actual-result record was created before review and intentionally retains that
historical pending-review status; this root record is the final acceptance.
Next action: restore only this accepted exact package into isolated disposable
PostgreSQL and verify replay/read-closure parity through a separately bounded
contract. No automatic M2–M5 continuation or new capture is authorized here.

## Production6 isolated restore and deployed search observation

The accepted production6 package is reused without another export. Root owns
`scripts/eis-search-production6-replay.py`, this evidence document and the live
plan. The existing decoder verifies inline and fragmented rows, and PostgreSQL
COPY restores the exact projected columns. The existing benchmark-v2 command
replays saved benchmark evidence rather than loading a corpus into PostgreSQL;
there is no complete PostgreSQL restore command for this package. The bounded
one-corpus worker uses the accepted decoder and existing SSH/Docker route; it
adds no generic restore platform, product gate or deployed search change.

The frozen suite `production6-isolated-replay-plan-v1.json` (SHA
`ae2969110cf59b8bc980876a70e029db8eb0711b1e3e212eee3861485e173cb2`)
contains nine cases: paper, A4 office paper and document-printing services;
44-FZ uses both ALL_CACHED and NOT_EXPIRED_OR_UNKNOWN, and223-FZ uses its current
ALL_CACHED behavior. Three repeats,100 results/page,30s wall/statement timeout,
1s lock timeout and at most20 continuations are fixed before measurement.
Every call has a persisted start, result/error and monotonic duration; terminal
accounting covers all27 traversals, including NOT_ATTEMPTED/ABORTED/error/budget
outcomes. The fixed search clock is package T,2026-10-08T15:40:01.646377Z.
The first observation follows restore/ANALYZE/full readback and is not machine
cold. SQL_STORAGE timings exclude HTTP/UI; independent labels are absent, so
precision and recall remain UNKNOWN.

Isolation uses a fresh internal network, no published ports or production DSN,
and only a new PG16.15 container and worker. The exact API image and deployed
Python source tree are copied and hashed before/copy/after; a fresh bytecode
prefix and loaded-module source hashes prevent copied pyc from bypassing parity.
The app role is SELECT-only, non-superuser/non-bypass, READ ONLY with forced RLS.
Worker4GiB/CPU1 and PG1GiB/CPU1 run with zero swap; fresh memory admission after
PG starts requires4GiB plus1.5GiB reserve. Preflight also requires50GiB free disk. One7200s controller deadline
includes a300s cleanup reserve. The isolated data directory and reports remain;
owned containers/network are removed after measurement.

First dispatch v1 stopped before any PG/network/search: Docker cp preserved
root-owned0600 source files, so controller source hashing raised PermissionError.
Origin and copied uid/gid/mode matched0:0/0600. All27 traversals were NOT_ATTEMPTED;
owned-container inventory was empty and no PGdata directory existed. Diagnostic:
`production6-replay-first-failure-v1.json`. No data or search failure is inferred
from this preflight refusal. V2 corrects only private-copy permissions through
the existing pinned API image, network-none with only that copy mounted; bounded
finally cleanup tracks this temporary container. The first stage and diagnostics
are preserved. Worker/codec/suite bytes are unchanged; no automatic third cycle.

Independent exact preparation review v1 SHA
`5e10cdd249f5c07a1dac25dbc131a595f9371c4bd00c279402537fac50fcf410`;
justified v2 delta review SHA
`c794e4a829441552f328404fce0e791125f8e70de597143f1a161fc06417d385`.
Root exact acceptance precedes dispatch by checked control flow. Final controller
SHA`8a53c50d3e4143a8e882f492218fb0e72308738e56a40529057a39d463a444ef`;
worker SHA`a8ab3a01fbf0bcdb9329ff28370e5a5b0f19c6ad8a05198644856505ae31af05`.
Stage-v5 readback matched all four pins.

Actual v2 result: **corpus restore COMPLETE; deployed SQL_STORAGE search
reproduced; all-success/full-traversal suite INCOMPLETE**. The controller's
`RESTORED_AND_SEARCH_OBSERVED` status records completion of the bounded observation,
including error and budget outcomes; it is not an all-query PASS or M2 acceptance.
No second export was made. All27 planned traversals were attempted:12 COMPLETE,
12 INCOMPLETE_BUDGET,3 INCOMPLETE_ERROR;327 calls,324 responses and3 wall timeouts.

| Restoration/parity check | Actual result |
|---|---|
| Restored corpus |25 relations,800444 logical rows; complete exact production6 projection |
| Integrity before/after search |All25 canonical ordered row hashes/counts equal manifest and each other |
| Schema/closure |Projected columns/types/nullability verified;25 foreign keys validated |
| Projection omissions |Only `content` in `eis_223_blobs` and `eis_feed_archives`; parent keys retained; not a full physical DB backup |
| PostgreSQL runtime |16.15, `en_US.utf8` collation/ctype, UTC; matches package |
| Deployed code |209 Python files exact before/copy/after;95 loaded module origins/hashes verified, fresh bytecode prefix |
| Source tree digest |`b7b965f183c937385a0152e834e47af6a4cf4f210f06cb678e61887e462def8b` |
| Tenant/write isolation |Foreign tenant0 rows in every relation; READ ONLY/RLS on; non-super/non-bypass app; two writes refused42501 |
| Restore time |506.208929s; includes data/schema/index/FK/ANALYZE work |
| Canonical readbacks |Before493.663185s; after507.699048s |
| Search calls total |4741.280872962s; sums actual call durations, excludes result serialization/reporting |
| Controller total |6287.272467s (104m47.272s), including startup/readbacks/cleanup; below7200s |
| Final worker cgroup |peak1438556160B (1.339760GiB), memory.max4294967296B, swap0, all events0 |
| Final PG cgroup |memory.max1073741824B; peak1073750016B (limit+8192B);304947 max events; OOM/kill0, swap0 |
| Fresh admission |6734663680B available,5905580032B required after PG start; PASS |
| Cleanup |Both owned containers and internal network removed; residual inventory empty; exact production API/PG still running |

Times below are seconds for each whole measured traversal, three fixed repeats.
`N` means NOT_EXPIRED_OR_UNKNOWN; `A` means ALL_CACHED. Matched is the engine's
reported count, not independently relevant results. Read is the observed prefix
per repeat. Budget outcomes stop at21 pages/2100 results with a nonempty cursor;
no missing pages are treated as retrieved. Each call's raw result/error and time
is preserved separately.

| Case | Law/query | Scope | Matched/read | Seconds, repeats1/2/3 | Outcome each repeat |
|---|---|---|---|---|---|
| q01 |44 / бумага |N |741/741 |72.608 /66.211 /56.430 |COMPLETE |
| q02 |44 / бумага |A |5080/2100 |347.178 /346.072 /340.809 |INCOMPLETE_BUDGET |
| q03 |44 / офисная бумага А4 |A |6570/2100 |522.668 /520.986 /519.633 |INCOMPLETE_BUDGET |
| q04 |44 / офисная бумага А4 |N |954/954 |90.338 /87.308 /86.718 |COMPLETE |
| q05 |44 / услуги по печати документов |A |UNKNOWN/0 |30.002 /30.003 /30.009 |INCOMPLETE_ERROR: TimeoutError |
| q06 |44 / услуги по печати документов |N |7930/2100 |376.495 /381.520 /382.383 |INCOMPLETE_BUDGET |
| q07 |223 / бумага |A |216/216 |4.179 /4.281 /3.992 |COMPLETE |
| q08 |223 / офисная бумага А4 |A |292/292 |4.875 /4.974 /4.822 |COMPLETE |
| q09 |223 / услуги по печати документов |A |2542/2100 |144.589 /141.675 /140.524 |INCOMPLETE_BUDGET |

All eight responding cases returned the same ordered IDs over the three repeats,
without duplicates. This establishes only prefix stability for budget outcomes;
q05 result stability is UNKNOWN. Its three first calls hit the30s wall guard:
`TimeoutError`, SQLSTATE null. This is not evidence of PostgreSQL57014 or a
localized SQL execution defect. The repeats were preplanned measurements, not
implicit retries. PG memory pressure is real and prevents a claim that PG stayed
below its cap; no causal attribution of q05 solely to memory is established.

A concrete semantic collision appears in q01-r1-p01: notice
`0105100002126000116`, title “Услуги по оценке арестованного имущества 2027”,
is STRONG for “бумага” through the item “Услуги по оценке Векселя, облигации,
акции и др. ценные бумаги”. Evidence locator ends
`purchaseObject[42]/name`; raw response SHA
`70d64a087484bd6434e922aee4ce271b24affe8d6ae245676985b7df2be08d00`.
This conflicts with the frozen paper-goods intent; it is an observed example,
not a labeled precision denominator. For q03 the engine reports2304 STRONG and
4266 PARTIAL; these categories are not ground truth.

Inspection of the exact deployed search source confirms that page limiting
happens after visiting/comparing the query's candidates; every continuation
repeats that work. `production6-replay-search-code-path-v2.json` records exact
module hashes/lines. The measured phase includes SQL/fetch/comparison; no profiler
was introduced, so the particular limiting phase for q05 remains UNKNOWN.

Corpus completeness is relative to the accepted package. The44-law summary has
267484 current notices,39903 in N scope,227581 expired exclusions; planned windows
151771, pending141051. Source freshness and EIS coverage remain UNKNOWN,
comparison PRELIMINARY. Precision/recall are **not measured** without independent
labels. This is a SQL_STORAGE copy-environment observation (CPU1 each, PG1GiB),
not HTTP/UI validation, machine-cold latency, production SLA or full M2 acceptance.

The restored stopped data directory remains privately on the VPS:
`/home/syurai/vibe-seller-state/improvement-m2-20261007/production6-isolated-replay-v2/pgdata`.
Containers/network are removed; it is not a running public database service.
Terminal raw files are preserved in
`tmp/improvement-program/m2/production6-isolated-replay-preserved-v2/`:995 files,
615630800B; local sizes/SHA match stable remote inventories before/after transfer.
Preservation-manifest SHA
`34629ca1b65b86cd4030978019c5671496de4210b10bf0ecd8fcb4f66a4f6be2`.
Root independently reconciled327 starts/attempts, raw response SHA/IDs, cursor
chains,27 terminal classifications, no duplicate IDs and per-case times in
`production6-isolated-replay-actual-result-v1.json`, SHA
`8f3cec0e39d77f4d683f8346e0f946f7a456a13c4f630e7e37dbc3ae644a2a5f`.
Independent actual review **ACCEPT for exact restore and bounded observations**:
`production6-isolated-replay-actual-review-v1.json`, SHA
`7c70a674bda49a3c64ee2156c7c95c09fda2cdc9d8f5fd476cadac0c40244e2f`.
It independently rehashed all995 raw files and reconciled query/version identities.
Root's separate immutable final binding is
`production6-isolated-replay-actual-root-acceptance-v1.json`, SHA
`3d63876dab9d52d28c161c1c628f46c26a83324688995cc6e546d7bf6b031e6c`.
The earlier derived summary retains its historical pending-review field; this
external root record binds the final review. All-success/full traversal remains
INCOMPLETE and full M2 NOT ACCEPTED. Affected pure Decimal JSON/schedule controls
and Ruff passed; accepted capture/PG9 suites were not rerun. These local checks
are not evidence of a working production export.
Next action: localize q05 SQL/fetch/comparison cost on this retained corpus in one
bounded investigation, without another export or generic runner expansion.

