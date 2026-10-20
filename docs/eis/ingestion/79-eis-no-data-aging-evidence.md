# S196 — возраст пустых окон и доказательства ответов ЕИС

05.10.2026. Owner root; VERIFIED, host diagnostic установлен.

## Что добавлено

Повторяемый серверный отчёт `scripts/server-eis-no-data-report.sh`:

```bash
bash scripts/server-eis-no-data-report.sh \
  --first-day 2026-07-07 --last-day 2026-10-04
```

До90 завершённых MSK дат; только planned exactDate+03:00 PRIZ, пять families
44-ФЗ, candidate codes01..99. Не включает hourly/current-day,223-ФЗ, другие
subsystems, иные offsets или более старые даты. Нельзя переносить его denominator
на всю очередь или весь ЕИС. Агрегаты: latest NO_DATA, due>=24h внутри последних
7дат, due вне7дат, cooldown<24h, oldest due age. <=20 samples сохраняются только
в private evidence; stdout содержит aggregates/hash/path. Даты/families с нулевым
NO_DATA не выдаются как покрытые: их просто нет в sparse census.

PostgreSQL READ ONLY REPEATABLE READ/SQL30s; same tenant/latest timestamp+UUID/
planned target/no LEGACY_CANONICAL. Variant transport не закрывает окно. Valid
source SHA обязателен, будущая попытка блокирует proof. До450 cohort aggregates,
20samples, immutable JSON0600 <=1MiB. Source requests0/DBwrites0.

## Проверки

Локально53PASS/1PGskip; на VPS isolated PostgreSQL54PASS05.10.2026 11:25:35UTC.
Тестовая БД отдельная, source credentials отключены. Проверены latest outcome,
UUID tie, tenant collision, canonical vs variant, malformed date, cooldown,
MSK7day/90day boundaries, read-only/count parity и immutable proof. Ruff/mypyPASS.
Root self-review; independent agent review не заявляется.

## Почему повторный NO_DATA не даёт полного охвата

В текущем sync path сохраняется hash пустого SOAP-ответа; тело не удерживается
этой ветвью. Hash сам по себе не позволяет заново разобрать ответ и не доказывает,
что источник перечислил всё. Независимое сравнение с другой source выборкой ещё
не выполнено. Полный ЕИС/absence/registry/freshness остаются UNKNOWN.

## Измерение и установка

Candidate snapshot: 05.10.2026 11:27:13.528553UTC, 131 sparse day/family cohorts.
Проверен диапазон 07.07–04.10.2026; только объявленные date keys.

| Latest planned NO_DATA | Количество |
| --- | ---: |
| Всего | 7341 |
| Due>=24h, внутри последних7 завершённых дат | 1096 |
| Due>=24h, старше последних7дат | 4399 |
| Cooldown<24h | 1846 |

7341=1096+4399+1846. Oldest due attempt age623326s (~7.21days).
Возраст попытки отличается от возраста **даты окна**. 4399 окон находятся вне
recent reserve, но допускаются general fill; census не доказывает, что каждое
никогда не будет выбрано. Доля и задержка их rechecks этим report не измерены.
Полный journal за пределами90dates и неплановые/hourly keys не учтены.

Private0600 proof `/var/lib/eis-browser/research/rejected/`:
`s196-no-data-6bf7f772-0a72-4f59-b9b3-ef97dd9e42a2.json`, SHA256
`7f23c4855776dc854f6eb7d9d1ce256f1d166f28d3c4833d90d855a5cdcf4aca`.
Source requests0/DBwrites0. Ordinary cron продолжает работать; новый snapshot
может иметь другие counts. Candidate receipt не заменяет post-install hash check.

Следующий slice выбирается по observed due backlog; сохранение raw response и
независимое corroboration имеют отдельные контракты, не подменяются новым report.

### Проверка установленной версии

11:30:55.590283UTC:7345NO_DATA=1093recentdue+4404olderdue+1848cooldown;
oldestdueage623548s. Private `s196-no-data-b83186e9-286b-48f6-8fda-4e5b5e911d84.json`,
SHA256 `d33c2e7ae72348f032623055da6d93791d8af9e6a476b1628261b2049983bfdd`.
Этот snapshot заменяет candidate для текущих counts; два census нельзя складывать.
За интервал продолжался ordinary cron. Диагностика в обоих snapshots source0/DB0.

11:30:58UTC: atomic host9/hashPASS, unchanged host22/API2/worker2hashPASS;
S195 API/worker и web images verified, cron checksum unchanged, HEAD20261004_03,
health200/testDBremoved/OOMfalse. API1GiB/web768MiB; DB4294671383bytes,
free258531803136bytes. Source budgets/resources/schema/runtime не менялись.
Backup existingdocsSHA
`fea5fed9aafa35360c14858bb5c10d7c311c35dd0f11ae59b257ffdf1fad9f28`.
Private state `s196-deploy.log` SHA256
`8171a20ffb4e12497de054d03afbcf2e371cb8e82b3e110c21baa4bc499027cc`.

NextS197: выделить bounded fair share для older due NO_DATA внутри текущего
60window budget, сохранить new/FAILED/transient lanes. Это теперь опирается на
наблюдаемые4404окна вне recent reserve. FullEIS/absence/corroboration UNKNOWN.
