# Продолжение выдачи и ограниченная сверка охвата ЕИС

Дата: 2026-10-07. Владелец: root. Статус: INSTALLED на www.syurai.su;
activation `2026-10-07T06:14:29.714555Z`. Зависимости: saved-index contracts,
[обзор выдачи](112-eis-discovery-overview.md), [ADR0106](../../adr/0106-eis-search-continuation.md).

## Owned files и acceptance

Backend: `storage/eis_search_pagination.py`, `storage/eis_index_query.py`,
`storage/eis_223_index.py`, два GET handlers в `api/app.py`.
Web: `tender-discovery/{paged-results,indexed-search,indexed-223-search,result-explorer}.tsx`,
pagination actions в `actions.ts`, saved-search client/types в `lib/procurement-api.ts`.
Tests: `test_eis_search_pagination.py`, `test_eis_search_pages_api.py`,
`integration/test_eis_search_pagination_pg.py`, `web/tests/eis-search-pages.test.tsx`,
discovery test config/script. Docs: этот файл, ADR, тематические индексы, live-план.

Acceptance: чтение всех совпадений дальше 100; прежний глобальный порядок без
дублей/потерь; tenant/query/law/scope isolation; явный restart при изменении
evidence; поздние импорты не смешиваются со старым снимком; READ ONLY/source0;
FAIL/UNKNOWN, источники и точные денежные строки сохраняются; полнота UNKNOWN.
UI сохраняет выбранные фильтры и сравнение при загрузке следующей сотни.

## Проверки

- 100 focused Python tests PASS: helper, API, 44/223 legacy query regressions.
- 24 PostgreSQL runtime tests PASS, без skips, отдельная БД
  `procurement_eis_test_20261007_search_pages`; БД удалена после проверки.
  По 205 синтетических записей обоих законов в трёх страницах, late imports,
  legacy order parity, tenant mismatch, новый cancellation → restart и FAIL.
- 7 Node filter/render/merge tests PASS; scoped Ruff/mypy/ESLint и TS PASS.
- Browser на собранных candidate images: 44 100→200 с сохранением выбранного
  способа; 223 100→141 и исчезновение continuation button; desktop и mobile
  без горизонтального overflow. Снята галочка queue refresh: source0.
  Screenshot: `tmp/discovery-overview/server-pages-desktop.jpg`.
- Локальный Next production build PASS; оба candidate images построены на VPS.
- HTTP ASGI check **из candidate API image** на saved production index: 200/no-store,
  continuation SHA/clock consistency, 401 без auth, 422 при другой query/oversize.
  44: 100+100 из 764; 223: 100+41 из 141. Source calls0, DB writes0.

Первый широкий PostgreSQL запуск FAIL: ошибочная family новой cancellation
фикстуры исправлена; шесть прежних migration-downgrade тестов из
`test_eis_223_index_pg.py` упираются в более новый guard
`20261006_12_supplier_serp_fallbacks.py` (`supplier SERP fallback evidence must be preserved`).
Guard не ослаблялся. Повторно выполнены релевантные runtime тесты этого файла,
весь notice-index module и новый pagination module. Общий migration gate PASS
не заявляется; этот срез миграций не содержит.

## Saved production index: полный проход по запросу

Из временного контейнера: существующий API image с тремя readonly overlays,
только app-role DATABASE_URL внутри контейнера, `company_id=local-eis-supplier`.
Источник ЕИС не опрашивался, sync/jobs не создавались. Режим 44 —
`NOT_EXPIRED_OR_UNKNOWN`. Это снимки, а не постоянно актуальные числа.

| Закон / UTC snapshot_at | Совпадений | Страницы | Уникальных | Время включая legacy oracle |
| --- | ---: | --- | ---: | ---: |
| 44 / 2026-10-07T05:24:04.340206Z | 765 | 7×100 + 65 | 765 | 54.887 с |
| 223 / 2026-10-07T05:24:59.227396Z | 141 | 100 + 41 | 141 | 2.097 с |

Первая сотня каждого закона совпала с legacy oracle; SHA всех страниц одного
поиска одинаков. Небольшие изменения числа 44 между проверками связаны с
временем, новыми импортами и режимом срока; конкретная причина каждого
исключения не исследовалась. Снимок не доказывает свежесть всей ЕИС.

44 snapshot SHA: `eb1b69b49acb1462deb276a64918ee4ca47ac26d7c61d31afc2038d6bf98cc3a`.
223 snapshot SHA: `9058da9a103a0d4edc6a7a429cdc10365dcf5eaab1e5e3fa410e0508949eacc3`.

## Census завершённых дней 44-ФЗ

`scripts/server-eis-ingestion-report.sh --first-day 2026-10-04 --last-day 2026-10-06`,
завершено `2026-10-07T05:07:39Z`, tenant `local-eis-supplier`.
Read-only RR, source0, DB writes0. Scope: 99 региональных кодов × пять семейств
PRIZ × три завершённых дня = 1485 окон. Все имеют исход CANONICAL либо NO_DATA;
missing plan, unattempted и known failure в этой границе отсутствуют.
NO_DATA не доказывает отсутствие извещений.

| День | epNotificationEF2020 CANONICAL/NO_DATA | EOK | EZK | Cancel | CancelFailure |
| --- | --- | --- | --- | --- | --- |
| 04.10 | 21/78 | 1/98 | 24/75 | 1/98 | 0/99 |
| 05.10 | 89/10 | 52/47 | 84/15 | 67/32 | 3/96 |
| 06.10 | 87/12 | 51/48 | 84/15 | 58/41 | 1/98 |

Для notice cohorts число indexed versions совпало с canonical versions.
Полный tenant proof на VPS:
`/var/lib/eis-browser/research/rejected/s192-ingestion-aadfb3f4-43fd-4049-9d02-4802b8d7de0d.json`.
SHA: `f62110a8bfefd3541df0ee1b7a0a09b5cabe1e5ce210b99e7439ea179e039f69`.
Scope SHA: `73ff4870c443abb8fdfdfb7f168035f278ba806adb43ecd3da0a015dec9c8227`.

Это не census всего исторического корпуса, текущего дня или всех семейств ЕИС.
Известная 223 wave 06–07.10 ранее имела один failed window и PARTIAL scope;
в этом срезе её загрузка не менялась. Нельзя заявлять «каталог полный»,
«все NO_DATA пустые» или полный анализ ТЗ по этим evidence.

Повторный GET coverage `2026-10-07T05:37:21.391886Z`: та же wave,
900 attempted = 292 SYNCED + 607 NO_DATA + 1 failed, PARTIAL/UNKNOWN.
Read-only journal установил точный gap:
`getDocsIP/RI223/77/2026-10-06+03:00/purchaseNotice`,
последняя попытка `2026-10-07T05:21:24.341733Z`, FAILED/ARCHIVE_COUNT_LIMIT.
Это ограничение при обработке архивов общего извещения Москвы; окно не
считается пустым или успешно покрытым. Число отсутствующих карточек неизвестно.
Следующий отдельный bounded slice — обработка этого ответа без снятия лимитов
памяти/архивов и без ложного checkpoint частично принятого окна.

## Пакет выпуска

VPS staging: `/home/syurai/vibe-seller-state/discovery-pagination-20261007`.
Local manifest: `tmp/search-pagination-release/payload/manifest.json`.
Manifest SHA: `dbfc7dbcee88001388722c7720c5c4b93376077f8275ab898b20293bf3099f70`.

| Image | Immutable ID |
| --- | --- |
| `vibe-seller-api:discovery-pages-20261007` | `sha256:96bf6795f8eadee57b2ca359e195ca7f37a99b737a35527f12c81fe53fe39219` |
| `vibe-seller-web:discovery-pages-20261007` | `sha256:59f91c2e9669b9b1d3eb20b3cf3826a727c039f88d64e844073203c6f700b6fb` |

База обоих images — установленный manual-captcha release; overlay содержит
только этот срез. Из двух shared files исключены невыпущенные local manufacturer
routes/client helpers. Worker, DB schema и документы не меняются при activation.
Предложение: заменить API/web этими images с возможностью возврата к текущим
manual-captcha images. Первоначальный candidate на исходной базе не
активировался; installed release описан ниже.
Activation script и два Compose overrides подготовлены в staging; script
требует exact manifest approval, проверяет текущие/candidate image IDs,
берёт deployment lock и переключает только API/web. При health failure
предусмотрен возврат к прежним images. На этапе candidate source checkout VPS
не перезаписывался. После activation approved source сохранён в checkout
с hash guards и backup (ниже).

## Установка согласованного overlay — 07.10.2026

Пользователь подтвердил публикацию описанного пакета («давай»). К этому моменту
другой срез обновил baseline до `manual-captcha-20261007-v9`. Initial activation
остановился на проверке baseline image IDs, до изменения контейнеров.
Сравнение старого и v9 baseline: `api/app.py`, оба storage query modules,
`actions.ts`, `procurement-api.ts` и четыре исходных discovery UI modules
совпадают byte-for-byte. Все 17 файлов approved payload сохранили SHA из
исходного manifest; product source overlay не изменён.

Overlay собран поверх текущей v9 базы, чтобы сохранить уже установленные
supplier CAPTCHA исправления. Next production build и семь Node tests из
нового web image PASS; HTTP ASGI check нового API image PASS: 44 100+100 из
730, 223 100+41 из 141, одинаковый clock/SHA; без source calls и DB writes.

| Installed image | Immutable ID |
| --- | --- |
| `vibe-seller-api:discovery-pages-20261007-v9` | `sha256:e31518c5e163a244742b4d2ac1f5c308614c8753fd7a77667aebf7810075ce23` |
| `vibe-seller-web:discovery-pages-20261007-v9` | `sha256:3799e6c3da0ae005837696e38b2a25fb7b8e5f57733a8912a79829ad9b8cd17e` |

`activate-v9.sh` проверил approved manifest и candidate/current image IDs,
взял общий deployment lock и пересоздал только API/web. API health PASS,
updated first screen PASS. Tenant audit: VPS staging `activation.json`,
`company_id=local-eis-supplier`, approved manifest SHA выше, aware activated_at,
installed IDs и сохранённый v9 baseline. Runtime source bytes соответствуют
approved overlay; Docker build recipes для current base —
`Dockerfile.api.current`, `Dockerfile.web.current` вне исходного manifest.

Public HTTPS с TLS validation: 401 без credentials, 200 с existing Basic Auth,
новый h1 и схема шагов присутствуют. Credentials прочитаны только внутри VPS
из существующего private access file и в output не выводились. Browser на
установленном web через loopback SSH tunnel: query «бумага», 100→200 из 730,
обзор/счётчики обновились, continuation без alert; refresh queue выключена.
Снимок установленного UI: `tmp/discovery-overview/installed-pages.jpg` (gitignored).

Post-install HTTP read через установленный API: 44 snapshot
`2026-10-07T06:22:10.052818Z`, 100+100 из 730, 200 unique;
223 snapshot `2026-10-07T06:22:22.042507Z`, 100+41 из 141, 141 unique.
Все ответы 200/no-store, SHA и snapshot_at двух страниц совпадают.
Source calls0, DB writes0. Дополнительно Node HTTP probe из установленного web:
44 snapshot `2026-10-07T06:15:17.710781Z`, 100+100 из 730, 200 unique;
223 snapshot `2026-10-07T06:15:29.969979Z`, 100+41 из 141, 141 unique, exit0.
Вывод этого probe получен с задержкой; оба независимых HTTP checks PASS.

`sync-installed-source.py` под deployment lock сверил девять существующих
owned файлов с baseline SHA и отсутствие трёх новых; сохранил backup и перенёс
12 approved runtime source files в VPS checkout. `source-sync.json` PASS.
Теперь следующий build из checkout включает continuation и новый UI.
Для rollback использовать `compose-rollback-v9.yml` (прежние installed
manual-captcha-v9 images), а не первоначальный rollback к более старой базе.

## Локальная проверка повторного сравнения — 09.10.2026

Root; owned: existing pagination, 44/223 storage query modules, unit/PG tests,
ADR0106 и этот отчёт. Production source/image не изменены. Bounded process-local
memo описан в [ADR0106](../../adr/0106-eis-search-continuation.md).

79 unit и 128 уникальных real-PG тестов PASS, 0 skip: исходные четыре группы
126 тестов и повтор только затронутой группы 93 после двух новых late-event/schema
регрессий. Corpus production6 повторно не восстановлен. Запрос «бумага», frozen
clock 2026-10-08T15:40:01.646377+00:00, page_size20, первые три страницы 223:
состав, порядок, total216 и fingerprint совпали. Candidate comparisons216/0/0,
reuse0/216/216. Installed1.587/1.330/1.332s, candidate1.542/1.411/1.340s;
ускорение latency не подтверждено. Это SQL/storage boundary, не production HTTP.
Проверены первые60 результатов, не вся выдача216.

44 ALL_CACHED: два варианта первой попытки SQLQueryCanceled при30s; PG512MiB
достиг cap/max-events2591 без OOM. После пересмотра бюджета только44 повторён
с PG1GiB/1CPU: installed30.891s/candidate30.593s, тот же SQL timeout;
PGpeak385884160B/max-events0/OOM0, worker88358912B. Parity/reuse44 на сохранённом
корпусе UNKNOWN. В SQL присутствует audited_projection_decisions; точный
SQL operator/причина задержки ещё не установлен. Третий retry не выполняется.
223 workerpeak246165504B, PGpeak536870912B; reserve после запуска5972910080B.
Owned containers/network удалены, сохранённый PGdata оставлен, production
API/PG identities совпали до/после. Нет snapshot/restore, source calls или DB writes
приложения. Evidence: `tmp/improvement-program/m2/overnight-20261009-v1/03-pagination/`
в основном checkout, result-final-v1 и два retained-corpus benchmark archives.
Новое сравнение не является release receipt. Precision/recall UNKNOWN без
независимых labels; установленная production версия продолжает повторные сравнения.
