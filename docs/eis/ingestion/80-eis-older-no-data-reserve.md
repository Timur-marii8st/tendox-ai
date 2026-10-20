# S197 — старые пустые окна получают раннюю повторную проверку

05.10.2026. Owner root; VERIFIED, deployed selector/recheck slice.

## Изменение

S196 выявил4404older due NO_DATA вне7day reserve. Для selector budget>=30 выделяем
один ранний slot из обычного historical fill. Бюджет60/windows, concurrency,
cron и ресурсные лимиты сохраняются. Сегменты<30 не получают дополнительного
резерва. Точная eligibility и формулы — [ADR0078](../../adr/0078-eis-older-no-data-reserve.md).

Latest timestamp+UUID выбирается до outcome filter; same tenant/planned/exactdate,
guarded day<todayMSK-7, >=24h, validSHA, no canonical. Variant не завершает окно.
Старейшая attempt выбирается первой. Daily anchor counts toward reserve, duplicates
не добавляются. Unused capacity возвращается ordinaryfill.

При достаточных lanes и L60:

| Lane | Ключей |
| --- | ---: |
| Свежие первые попытки | 36 |
| Недавние пустые ответы | 3 |
| Недавние FAILED | 9 |
| Старые source transients | 3 |
| Старый пустой ответ | 1 |
| Обычный старый backlog, включая anchor | 8 |

Без свежих первых попыток общий предел всё равно60; reservedolder first позволяет
дойти до него до типичного раннего yield. Выбор не равен фактической обработке;
interruption/source failure может остановить окно. Reserve1 persegment, parent
может выбрать несколько таких окон в разных segments в пределах общего60budget.
Additional NO_DATA могут попасть в generalfill; reservation не является total cap.

## Проверки до установки

66tests PASS11:55:43UTC:27unit+39isolatedPG, testDBremoved, sourcecredentialsunset.
PG latest/UUIDtie/tenant/canonical/variant/cooldown24h/MSK7dayrollover/
30activation/29legacy/31/32/60quotas/freshshare/anchor/readonly gates. Ruff/mypyPASS.
Root self-review; independent agent review не заявляется.

SameRR shadow11:55:44.750042UTC:60unique before/after, recentempty3 unchanged,
olderempty0->1, historicalunattempted57->56. Candidate first key was Sep27 EF
window(region50), oldfirst Sep28CancelFailure. No dailynew remained onlive snapshot;
PG establishes fresh36 behavior. SQL12.294s vs11.816s is background timing, no SLA.
Diagnostic source0/DB0. Private `s197-shadow-381c0175-46e4-4c38-bc09-6a745608a08b.json`
SHA256 `9bcac99222f5ca049828874f8a24f6de67d11a2e99a93d98983f60c627d44571`.

## Production evidence

Pinned module rollout11:58:44UTC:atomic8/host28/API2/worker2hashPASS,
HEAD20261004_03/cronunchanged; rollback tags `vibe-seller-api:s197-base` and
`vibe-seller-worker:s197-base` retain S195 images. Code/docs backupSHA
`81253e9cde1284bbac012e3ea4dd7d145a26bf7f769c59d58fd6bce8ae530acf`.
API image `sha256:f34db66901b1fff355176ca2275980bff47e814a38a531073f57ab81be91892c`,
worker `sha256:5e7c366bfd8cd4d1991b73526f8ae9d49d6d5d462c0979eaadab21bd4898c90c`.
One module overlay; web/dependencies/schema/source transport unchanged.

Predeploy11:58:38.207152UTC source-free typed baseline of **60 oldest eligible**
older NO_DATA with exact priorattemptIDs/time/SHA, not census ofall4404:
`s197-before-d5e4c21b-1e78-42d3-bc5c-0def64d4aa4a.json`, SHA
`fd6b0f3dfa46fd99b3b77b1b359c5bebfd7b5bc85ae9057f0191bbe774157b91`.

### Actual ordinary cron recheck

12:01:17.284213UTC:one prior older NO_DATA from frozen60key baseline was rechecked
by actorserver-corpus-worker. Exact same tenant/window, different attemptID, new
valid sourceSHA, attempted_at>=prior.attempted_at+24h. Latest outcomeNO_DATA,
new24h cooldown started; canonical0,versions/index/events0. Source requests0/DB0
refer to the diagnostic, not background cron. No manual source pass.
Private `s197-recheck-observation-2715009f-6e17-4c3e-8150-fbc0f2d8942e.json`, SHA
`71a62555c6faf8d7cb29e644d24303d3201da776a45c997bf3eb5e1c91037e97`.
Earlier12:00:17 observation had0; cumulative snapshots are not added. No terminal
parent/sourcecapacity/throughput assertion. Parent60budget remains S194 contract.

Typed observer binds prior/new attempt evidence and latest snapshot; canonical
branch, if present, requires same sourceSHA and checkpoint between baseline and
new journal timestamp. It was **not exercised by this live NO_DATA response**.
Canonical receipt is written before journal.record; it must not be required to
occur after the journal timestamp. Newdata/completeness is not inferred from retry.

12:01:06.920434UTC operations:health200/HEAD03/testDBnone,
DB4336122903/free258470707200bytes. Ordinary regional markertrue/priorityfalse,
foreign markers not removed. Private `s197-operations-proof.json` SHA
`966cc47c6398a85553ed4c90ee2787a21641e096403ecba2e8168fff0e47ed94`.
API1GiB/web768MiB/worker2CPU2GiB remain; source/runtime frozen after66test gate.

Повторный
NO_DATA остаётся UNKNOWN; hash не заменяет raw response или независимый источник.
Полный ЕИС/registry/absence/freshness не доказаны.

Следующий шаг: retention raw NO_DATA SOAP для воспроизводимого source разбора;
это ещё не independent corroboration и не canonical completion.
