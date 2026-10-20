# ADR0077 — возраст NO_DATA и границы доказательства пустого окна

Effective date: 2026-10-05. Owner root. Status: accepted, diagnostic deployed/verified.

## Контракт

S195 резервирует повтор последних семи завершённых MSK дат. Дата окна может выйти
из этого резерва; старые due NO_DATA остаются допустимыми для общего fill, который
может долго выбирать новые historical targets. Это не доказывает starvation для
каждого окна: нужна наблюдаемая возрастная статистика.

Добавляем отдельный host diagnostic: до 90 завершённых дат, candidate codes01..99,
пять notice families 44-ФЗ PRIZ, только exactDate+03:00. Последний tenant attempt
выбирается по timestamp DESC/UUID DESC **до** фильтра NO_DATA, пересекается с
planned targets, исключается любой LEGACY_CANONICAL receipt. VARIANT_TRANSPORT
не означает canonical completion. Некорректная дата защищена CASE/
pg_input_is_valid; malformed keys вне объявленного scope.

Один READ ONLY REPEATABLE READ snapshot, SQL timeout30s. Агрегаты по дате/family
считаются в PostgreSQL; <=450 cohorts и <=20 oldest due samples выходят из БД.
Суммы, chronology, >=24h boundary и membership последних7дат проверяет typed
report; missing SHA/future timestamp блокируют отчёт. Частичный census не выдается
за полный. Immutable UUID proof0600, <=1MiB. Source requests0/DBwrites0.

## Ограничение доказательств

В `sync_eis_window` ветвь NO_DATA возвращает только SHA parsed SOAP response.
`_parsed_post` получает raw bytes, проверяет HTTP/size/token reflection и парсит;
тело ответа не возвращается и эта ветвь не сохраняет его. Это проверка кода
05.10.2026, а не утверждение об отсутствии любых сторонних server logs.
Журнал позволяет доказать факт попытки и связать hash. Отчёт не проверяет raw
response, независимый источник, фактическое отсутствие закупок или полный ЕИС:
`response_body_retention`, `independent_corroboration`, `source_absence`,
`coverage`, официальный реестр регионов — UNKNOWN. Повтор того же SOAP метода
не является независимым подтверждением отсутствия.

## Порядок продолжения

Сначала измерить due backlog вне7days. Затем изменить только подтверждённый
scheduling gap отдельным bounded контрактом; raw response retention нужен для
воспроизводимого разбора source reply. Независимое corroboration потребует другой
проверенной source выборки с сопоставимыми scope/date semantics. Охват публичного
поиска ЕИС не объявляется равным охвату getDocsIP.

Runtime images/schema/source budgets/cron этим diagnostic не меняются.

## Evidence

54 isolated Linux/PG tests PASS11:25:35UTC/Ruff/mypyPASS. Candidate tenant census
11:27:13UTC,90dates/131cohorts:7341NO_DATA=1096recentdue+4399olderdue+1846cooldown;
oldest due age623326s. ProofSHA
7f23c4855776dc854f6eb7d9d1ce256f1d166f28d3c4833d90d855a5cdcf4aca.
Это основание следующего bounded slice — fair reserve для older NO_DATA внутри
существующего total budget. Более широкий source intake этим ADR не допускается.

Installedsnapshot11:30:55UTC:7345NO_DATA=1093recentdue+4404olderdue+1848cooldown,
proofSHAd33c2e7ae72348f032623055da6d93791d8af9e6a476b1628261b2049983bfdd.
Rollout11:30:58UTC host9/unchangedhost22/API2/worker2hashPASS, runtime unchanged.
