# ADR0078 — один ранний слот для старых NO_DATA

Effective date: 2026-10-05. Owner root; accepted, deployed/bounded verification.

## Основание

S196 installed census11:30:55UTC:4404 due NO_DATA в planned date scope находятся
вне последних7 завершённых MSK дат. Они остаются general fill, но NULL-first
historical first attempts могут оттеснять их повтор. Hash/cooldown не доказывают
отсутствие закупок. Источник внутреннего факта — [S196](../eis/ingestion/79-eis-no-data-aging-evidence.md),
proofSHA d33c2e7ae72348f032623055da6d93791d8af9e6a476b1628261b2049983bfdd.
Это scheduling policy, не юридическое правило и не расширение source permissions.

## Решение

При selector limit>=30 резервировать один oldest due older NO_DATA из обычного
fill. Для limit<30 дополнительный reserve0; предел выбран так, чтобы не вытеснять
ceil(60%limit) свежих первых попыток при заполненных repair/transient lanes.
Один latest tenant attempt(timestamp DESC/UUID DESC), planned exact date key,
valid64hex SHA, age>=24h, source date<todayMSK-7, no LEGACY_CANONICAL. Guarded date
cast; malformed/current/future dates не проходят. Variant transport не завершает
окно. Сортировка attempt ASC/key ASC; нет date-expiry для older lane.

Fallback: older reserved first, recent repairs, historical transients, ordinary
fill. Daily: original old anchor и firstnew сохраняются; oldestempty добавляется
перед repair tail и получает раннюю позицию при прежнем3new/2other interleave.
Если сам anchor eligibleolderNO_DATA, он уже выполняет reserve, второй ранний
empty slot не добавляется. Ordinary fill по-прежнему может выбрать другие due
empty: cap1 — reserved lane, а не ограничение всех NO_DATA в result.

При L60 и достаточных всех lanes:36new+3recentempty+9recentFAILED+3transient+
1olderempty+8ordinaryold(includinganchor)=60. Без dailynew:1olderempty+12repair+
3transient+44ordinaryfill=60. Unused слот возвращается fill; каждый реально
обработанный ключ расходует существующий parent60 budget. Повторный выбор
selector не гарантирует HTTP completion: priority yields/resource/source failures
могут прервать сегмент. Reserve применяется persegment, не perparent; S194 общий
60windowbudget сохраняется. No increase cadence/concurrency/download volume cap.

Append-only attempt/sourceSHA/cooldown unchanged; NO_DATA remains UNKNOWN.
Successful intake требует canonical receipt и index parity, не одного SYNCED.

## Проверка

66Linux tests PASS11:55:43UTC (27unit+39isolatedPG), Ruff/mypyPASS. PG проверяет
29/30/31/32/60 quotas с active/inactive daily, latest ties/tenant/guarded dates/
canonicalvsvariant/24h/midnightrollover/anchor dedup/cooldown/read-only.

SameRR shadow11:55:44UTC:old0/candidate1olderempty, recentempty3 unchanged,
unique60, historical firstattempts57->56. Firstnewlane inactive onactualsnapshot;
fresh36 contract proven by PG, not live snapshot. Query12.294s vs11.816s, no SLA
or speedup assertion. Source0/DB0; private proofSHA
9bcac99222f5ca049828874f8a24f6de67d11a2e99a93d98983f60c627d44571.

Pinned one-module rollout11:58:44UTC atomic8/host28/API2/worker2hashPASS.
Predeploy60oldestkeysSHAfd6b0f3dfa46fd99b3b77b1b359c5bebfd7b5bc85ae9057f0191bbe774157b91.
Actualordinarycron12:01:17UTC:oneolderempty rechecked/newID/newsourceSHA/24hreset,
latestNO_DATA/no canonical or newversions/index/events. TypedproofSHA
71a62555c6faf8d7cb29e644d24303d3201da776a45c997bf3eb5e1c91037e97.
Actualfreshnewlane inactive; no terminalparent/SLA/absence assertion.
Independent source corroboration/fullEIS/registry/freshness UNKNOWN.
