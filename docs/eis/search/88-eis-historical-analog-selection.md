# S205 — исторические кандидаты в аналоги

Owner root; Astra independent read-only review. Backend завершён 2026-10-05.
UI выбора позиции/исторических кандидатов пока не реализован.

## Контракт

`POST /v1/tender-discovery/eis-analog-candidates` — read-only запрос по exact
`target` (purchase number/version/XML SHA), `source_index`1..25, `query`1..120,
`lookback_days`1..730 (default365). Tenant — bearer principal; extra company_id
запрещён. Это подбор для выбранной позиции извещения, не всего смешанного лота.
Факты и сравнения возвращаются типизированно с XML SHA/member/locator provenance.

Используется существующая сохранённая проекция `lot_items`, без чтения ZIP,
новых source calls, заданий, audit/projection writes или новой схемы БД.
Отдельная SQL выборка в одном consistent tenant read:

- target исключён по номеру до LIMIT;
- только latest сохранённые версии той же семьи извещения без source hold;
- deadline≤checked_at означает истёкший срок, не завершённый/исполненный контракт;
- публикация в закрытом интервале [target publication−lookback days, target publication];
- overlap persisted lexical keys либо отсутствующая derivation;
- сортировка publication DESC/purchase number ASC, LIMIT21; гидратация первых20.

Overlap не означает точного совпадения запроса. Такой префильтр может пропускать
совпадающий KTRU с другим названием: lexical recall/sample completeness UNKNOWN.
Слова запроса проверяются существующим lexical validator. Нельзя использовать
обычный `search_eis_index(limit20)` как ограничение работы: он разбирает всех
кандидатов, а его рейтинг отдаёт предпочтение действующим карточкам.
Пропущенная target publication не заменяется now; возвращается явный UNKNOWN
с пустой выборкой и причиной. Future target publication отклоняется.
Исторический exact target допустим; latest predicate относится к кандидатам.

## Измерения отбора

В каждой рассмотренной позиции шесть измерений PASS/FAIL/UNKNOWN:

| Измерение | Предикат |
| --- | --- |
| SUBJECT | Оба KTRU есть: полное точное совпадение; конфликт FAIL без fallback. При отсутствии одного KTRU: точный OKPD2 + целое имя после casefold/whitespace normalization. Недостающие значения UNKNOWN. |
| VOLUME | Положительные конечные Decimal, одинаковая нормализованная строка единицы; candidate quantity ∈[target×0.5,target×2], включительно. |
| PERIOD | Source publication внутри явного интервала. |
| HISTORY | Истёкший source deadline; это не award/contract result. |
| TECHNICAL | UNKNOWN: полная спецификация не проверена. |
| DELIVERY_REGION | UNKNOWN: регион доставки не извлечён. Регион окна публикации не подменяет адрес поставки. |

Любой FAIL даёт EXCLUDED/FAIL; остальные строки NEEDS_REVIEW/UNKNOWN.
Полностью подтверждённых аналогов и рейтинга не создаётся. Порог0.5..2 и
нормализация единицы — внутренние retrieval filters, не юридическое правило
и не доказательство физической/технической эквивалентности.
Policy `eis-analog-retrieval-v1`, effective2026-10-05; ADR0085.
У критериев представлены оба исходных значения и источники. Root/name evidence
у UNKNOWN technical/region обозначает документы рассмотрения, не выдуманный
локатор отсутствующего географического поля.

Число выбранных извещений, рассмотренных позиций, исключённых строк и строк
на проверку показывается отдельно. Это не число конкурентов. Все exclusion
counts относятся к рассмотренному фрагменту, не ко всей ЕИС.
Максимум25 позиций на карточку; полное исходное число и uninspected positions
явны. Lot association/supplier identity/current competition/profit/participation
и полнота/свежесть остаются UNKNOWN. Протоколы разных документов не объединяются.

## Ограничения ресурсов и проверка

До чтения JSONB payload проверяются SQL octet_length:256KiB на извещение,
2MiB total с target. До21 metadata refs, до20hydrated notices/500positions,
response≤4MiB, member255UTF8bytes, scalar/locator500characters.
15s foreground budget с checkpoints/remaining timeout; SQL statement≤5s,
lock1s. LIMIT ограничивает возвращённые refs/память, не число сканируемых БД
строк и не доказывает латентность. Истечение DB timeout →safe503;
integrity/resource failures →422, не пустой «успех».

27 local synthetic source/API tests PASS. Isolated PostgreSQL gates:
193 PASS in15.03s, VPS2026-10-05T17:45:22Z; schema20261005_01,
disposable test DB removed. Independent Astra review closed without remaining
material findings. SQL missing derivation uses the outer-joined nonnullable
company key, avoiding an incorrectly auto-correlated EXISTS subquery.
Raw quantity is limited to64characters before Decimal conversion; typed Decimal
is finite, at most30digits and absolute exponent12, including string inputs.
Scoped Ruff and mypy(two modules) PASS. Installed source0 measurements below.

Предварительный direct source0 прогон на трёх свежих бумажных карточках:
5836/3368/3194ms, по20извещений/82позиции, review_rows0/1/1. Это ограниченная
сохранённая выборка, не поиск по всей ЕИС.

## Установленная проверка VPS

Deploy2026-10-05T18:39:45Z: atomic12files/host82/API18/worker18hashes PASS;
health200, schema20261005_01 unchanged. Overlay only3modules; no dependency
updates/new tables/source budgets. Backup:
`/home/syurai/vibe-seller-state/backups/s205-before-20261005T183940Z-code.tar.gz`,
SHA256 `ff14a9b2ff02a690b6ac6c5a73e9489d8648403cad44db8b2f19ea556d784106`.

Installed HTTP+direct exact-time equality proof2026-10-05T18:41:41Z:

| Target, source position1 | HTTP ms | Direct ms | Notices / positions | Excluded / review | Response bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0373100108126000488 | 4066 | 4001 | 20 / 82 | 82 / 0 | 643277 |
| 0373100015026000007 | 3291 | 3259 | 20 / 82 | 81 / 1 | 637300 |
| 0348200080326000021 | 3236 | 3246 | 20 / 82 | 81 / 1 | 639247 |

All requests `query=бумага`, lookback365; target publications2026-10-05.
All selection_truncated=true: these are first20 leads from saved corpus,
not all historical matches. Uninspected positions within selected notices0.
Each exclusion has source criteria; overlapping exclusion reasons are not summed
as independent rows. Review1 remains UNKNOWN due to delivery/specification.
HTTP200/no-store; every criterion identifies both XML sources, any FAIL excludes;
source_requests0/DBwrites0. Measurements are VPS loopback, not browser/nationwide SLA.

Each direct read52SQLstatements: SELECT4/SET LOCAL26/WITH22;
SQL total3807/3071/3097ms. SQL text/parameters/credentials not retained.
Proof `/var/lib/eis-browser/research/rejected/s205-paper-live-proof.json`, SHA256
`72943f7cd6f56e80fdf16007e0f899b0252b52aeeef2ba85a23b37e3cdc33381`.
Individual raw typed reports remain VPS-only,0600, `s205-paper-report-{1,2,3}.json`:
SHA256 respectively `a3ecaffd7299ffcfad410cea4cd265922e7bdef4ee795b0d4ee126ec578bbe1e`,
`f4f178bdc758cf541f38cace01d2defa603eb4b0496a8767dd62f7623f017b1f`,
`456dbf035617c49431230363b8f4da1602dd6f3761e5725fd85304b8b926c936`.

Image pins:

- API `sha256:4d5ea30e46c29bf05bd74b1dccd70c857423fba47ebaa7e2294132eab678cb69`.
- Worker `sha256:51291ca5fa1e2e28c8165a3ad333824b6ebc468f2a81a2e996644f67a654efa6`.
- Web remains S204 `sha256:861e3e8f348d1d74f0d20d1f07cc3cda83798465dd13af8a8efe67e458ddf359`.

Ops2026-10-05T18:41:42Z: DB4927994903/free257592745984bytes,
testDB0/head01/health200; ordinary223marker=true/priority=false, not removed.
API1GiB/web768MiB/worker2CPU2GiB, cron/source budgets unchanged.
Proof `s205-operations-proof.json` in the same VPS directory, SHA256
`0c1ed707679eb966bb3420b8d25807f65981c3a18a398b00404a49fa65e2fb69`.

Documentation seal2026-10-05T18:42:53Z: atomic6docs/host82/API18/worker18/
web9hashes PASS; installed image/cron pins PASS, API/web running/OOMfalse,
API1GiB/web768MiB unchanged. Seal backup SHA256
`74538caac08146d45bd046fd0e246e32842a4aa0bdcdc83f161f50943f8d39bb`.

## Следующая итерация

Следующий S206: убрать повторную проверку holds для уже отфильтрованных
кандидатов внутри одного REPEATABLE READ. Astra подтвердил эквивалентность:
selector использует тот же полный predicate; повтор20hold queries/20SET LOCAL
не усиливает integrity. Сохранить target assertion, весь selector predicate,
tenant-wide receipt/audited projection checks и budget перед hydration.
Acceptance: идентичные reports при фиксированном времени, hold/integrity/RLS
регрессии, измерения числа SQL и первых/повторных чтений этих же трёх refs.
Ускорение пока не подтверждено. Затем S207 — UI выбора target position и
объяснений подбора; после — delivery/specification comparability и отдельная
immutable проекция protocol observations. Прогноз вероятности требует калибровки.
