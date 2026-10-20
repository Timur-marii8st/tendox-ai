# S180 M1 — полный транспорт44 и явная проекция карточек

Дата: 04.10.2026. Operator M1 deployed and verified; production proof и HTTP smoke PASS.
Контракт: [ADR0063](../../adr/0063-eis-44-retained-variant-projection.md).

## Что реализовано

Operator API `project_retained_notice_variants(storage, company, receipt_id,
archives, actor_id=...)` работает с уже сохранённым и проверенным S178 receipt.
Он заново сверяет все ZIP/XML с exact audited diagnosis, разбирает полный
snapshot карточки установленным parser и записывает один immutable decision
на каждую purchase number/version. Сеть ЕИС здесь не используется.

Полный transport parent имеет `intake_kind=VARIANT_TRANSPORT`: сохраняются все
архивы, все member counts, source URLs/prepared response SHA. Canonical FK
продолжает ссылаться на реальные исходные байты. Две новые tenant tables:
`eis_notice_projection_batches`, `eis_notice_projection_decisions`; migration
`20261004_03` содержит frozen DDL, RLS/FORCE и immutable triggers.

`PROJECTED` означает новую source projection; `REPLAYED` — existing sameSHA/type
и совпадающий полный parsed snapshot (другой source_member допускается);
`HOLD` сохраняет явную причину. Это не supplier eligibility PASS и не
рекомендация участвовать. Deadline/КП/экономика/hard gates прежние.

Все batch writes — одна транзакция под tenant→ledger lock: полный transport,
все decisions, новые canonical rows/search keys и audit. Поздняя ошибка
откатывает весь набор. Replay сверяет exact immutable payload/basis/transport/
canonical snapshot и не пишет новые rows. Replay старого решения после нового
конфликта сохраняет историю; live guard заново удерживает карточку.

## Допуск источника

Из всей истории tenant для pair должен существовать ровно один distinct
type/XMLSHA, известный source document id и успешно разобранный полный snapshot.
Existing different canonical SHA/type/content удерживается без overwrite.
Недостающая identity или parser failure не теряется: явный HOLD. Неизвестные
number/version или нарушение общего binding/budget отклоняют целый batch.

Общий guard снимает hold только при совпадении decision с canonical SHA/type,
точного origin с receipt этого batch, known-id singleton во всей текущей
истории и exact decision membership в типизированном batch audit. Отдельно
проверяется incomplete receipt: повреждение удерживает весь tenant.
Новый другой SHA/type, orphan origin или unresolved newer version снова
блокирует поиск, документы, cached projection и экономические consumers.
Resolved origins >20 не превращаются в ошибку только из-за лимита списка
metadata; все потребители используют одинаковый SQL verdict.

## Покрытие и ресурсы

Все восемь checkpoint/completion reader sites исключают VARIANT_TRANSPORT:
has_ingested_window, legacy ingest replay, sync journal, обе corpus lanes,
freshness status, completed windows и indexed windows/latest ingestion.
Legacy replay явно отклоняет transport parent. Старые FAILED не переписываются
и subset не становится SYNCED. Source hook автоматически пока не включён.

Лимиты: ≤20 ZIP, ≤64MiB compressed/128MiB expanded, ≤2000 occurrences,
≤16MiB суммарных compact UTF8 parsed snapshots, ≤2MiB snapshot каждой карточки,
≤24MiB batch audit payload. Raw corpus остаётся на VPS. Notebook получает код
и небольшие результаты проверок. Полнота и freshness всей ЕИС UNKNOWN.

Новый guard читает bounded audit JSON для exact membership; прежнее описание
S179 «metadata only» применялось до discharge и не описывает этот новый путь.
Нужен performance proof на полном retained batch, а не только singleton fixture.

### Измеренные gates до rollout

176 Linux/68 PG tests (244) PASS; Ruff runtime/migration/tests и mypy9modules PASS.
Exact real5ZIP/499XML/498pairs:497PROJECTED,1HOLD; new canonical/searchkeys497,
audit1/batch1/decisions498. Sourcecalls0; ledger/attempt/target deltas0; old8FAILED
неизменны, checkpointfalse; replay всех13table deltas0. Projection12.879s,
весь proof29.193s с двумя searches/replay/Chromium. Peak583,127,040B/2GiB.

Прежний audit-array comparison давал56.164/59.143s на492current cards. Два
MATERIALIZED CTE раскрывают exact audited array и проверяют source pairs один
раз, сохраняя полную JSONB equality и live global-conflict gates. Новый результат
бумага936.03ms/11matches, серверное оборудование882.14ms/26matches.
EXPLAIN500selector349.207ms/planning45.675ms; functionscanloops1/498rows.
Это измерение одного retained batch, не fullЕИС SLA и не расчёт прибыли.

Proof `/var/lib/eis-browser/research/rejected/s180-isolated-optimized-proof.json`
SHA256 `58e7fb1f215f31076faff93471545f0f1ebbce5156e327e8d7f1271d5fe97786`.
Baseline `/var/lib/eis-browser/research/rejected/s180-isolated-proof.json`
SHA256 `16aa9f15883c855a0e1271428ac6856b8bb0cbb4687d3301f302d05ddd68f100`.
Census `/var/lib/eis-browser/research/rejected/s180-snapshot-census.json`
SHA256 `87ebfd807e971938d9ec6109852fb3ce12e4a27204f498498627ddc8a7da7dd5`:
UTF8compact13,002,894B vsASCII17,192,234B, maxUTF8card1,152,449B. Aggregatecap16MiB
прежний; cardcap2MiB обоснован измерением. Production gate выполнен ниже.

### Production deployment и проверка

HEAD20261004_03, API+worker rebuilt04.10.2026 10:41UTC; host21/runtime11 hashesPASS.
Backup code `/home/syurai/vibe-seller-state/backups/s180-before-20261004T104122Z-code.tar.gz`
SHA256 `45068cfa9b09bdb0415e9d46485e68cae80f74d25631886d81ff73d8b9efdd99`;
schema `s180-before-20261004T104122Z-schema.sql`
SHA256 `4f52ac4078f6423c0847045f72b7900b1beed6a191dc8399a089f52bfc3a8f31`.

Real production proof10:46:19UTC: persisted batch497PROJECTED/1HOLD, complete
5ZIP/499XML/498decisions. Повторный прогон всех13table deltas0/sourcecalls0,
original retained files неизменны. Conflict held; singleton usable. Old8FAILED
сохранены, exact target planned=true/pending=true/complete=false. Первая capped
страница journal gaps не содержит этот target: наличие gap доказано exact SQL
и has_ingested_window=false; отсутствие на capped page не означает completion.

Индекс44 содержит128803current purchase numbers,4929ordinaryindexed windows,
143196pending targets. Бумага2477matches/5814.25ms; серверное оборудование
5232matches/12312.86ms. Heldcurrent0: конфликтующий pair не имеет canonicalrow,
при этом его ledger hold остаётся. EXPLAIN500selector330.618ms/planning50.449ms,
arrayloops1/498rows; peak539,467,776B/2GiB+Chromium. Это saved-index comparison,
не fullЕИС, свежесть или profitability SLA.

Proof `/var/lib/eis-browser/research/rejected/s180-retained-proof.json`
SHA256 `ba6ff88a151bcfa1e719dbd82126e6396298b155bb261749553137e6b6e17c1b`.
Live source hook не включён; ordinary checkpoints/FAILED/history не изменены.

Final authenticated API smoke10:46:57UTC PASS:44current128803, бумага2477matches/
5811.2ms, серверное оборудование5232matches/12215.99ms;223current2882, бумага59/
218.47ms, сервер184/573.25ms. Все четыре поиска no-store; health200/anon401.
Coverage/freshnessUNKNOWN, priority/223refresh markersfalse; sourcecalls0.
HTTP hold sample отсутствует: конфликтующий pair не имеет canonical row;
нового доказательства HTTP422 этот smoke не даёт. Negative PG gates выполнены.
Proof `/var/lib/eis-browser/research/rejected/s180-api-proof.json`
SHA256 `f22c830afcd3eb0d7b09d7c70c655996560acf246fc5fc9fcc5b9b2e5c88d76c`.
Изолированная test DB `procurement_eis_test_20261004_s180` удалена после gates.

## Проверки и следующий milestone

Negative gates: divergent/singleton, existing differentSHA, sameSHA replay/
origin preservation, later same/newer variants, cached consumers, cross tenant,
owner immutability, global downgrade (включая transport-only), ошибочное named
CHECK, exact audited decision tamper, >20 resolved origins и late write rollback.
Frozen migration roundtrip проверяется на отдельной test DB.

Следующий S180 M2: bounded live hook и честный typed partial admission в refresh/
coverage reports; явные unresolved pair counts, source cadence/retry semantics,
без закрытия gap по subset. Затем активные ранние даты/backfill/parity и отдельное
ускорение comparison большого индекса. M1 не означает полного охвата ЕИС.
