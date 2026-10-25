# Точный регистрационный номер — исходный ограниченный локальный срез

> Исторический отчёт исходной ветки. Перенос на актуальный quality baseline и новые
> проверки описаны в [integration report](exact-registration-number-integration.md).
> Приведённые ниже baseline, timings и read-only наблюдения не повторялись при переносе.

Работа: 2026-10-14–15 МСК. Владелец: root. Ветка: `codex/exact-registration-search`.
Worktree: `C:/Users/elkgo/.codex/worktrees/exact-registration-search/vibe-seller`.
Baseline `5edcadb` сохраняет существовавшее незакоммиченное рабочее дерево;
review исправления выполняется относительно этого baseline. Общий live-план не меняется.

## Контракт и причина

Существующие GET `eis-index` / `eis-223-index` принимают строковый `query`,
но saved search сопоставлял только название/позиции/характеристики. Поле номера
не входило ни в SQL text-key prefilter, ни в последующую проверку matcher.
Формы были подписаны как поиск товара. Отдельная by-number проверка официального
XML из [25](25-eis-tender-discovery.md) не являлась этим пользовательским путём.
[PRD](../../product/11-product-requirements.md) требует поиск и ограничения;
[ADR-0068](../../adr/0068-eis-cached-search-deadline-scope.md) сохраняет явный scope.
Прежний saved-search контракт явно не обещал поиск по номеру.

До исправления: 9 новых unit cases FAIL; real PostgreSQL/API — 4 FAIL.
`32616445250` и `32616445747` находились по «кранов шаровых», но по номеру
возвращали HTTP 200 / 0 совпадений. Это воспроизведено на синтетических XML
с указанными номерами, а не на выгрузке production. Дополнительно обнаружен
ложный результат, если искомый полный номер находился в названии другой записи.
Затем read-only API пилота подтвердил реальный отказ: оба номера HTTP 200 / 0,
индекс tenant `local-eis-supplier` — 25630 current notices. Первый номер найден
по «кранов шаровых» (72 matches), второй — по тексту «2026-75 Оказание услуг по
комплексным испытаниям» (5578 matches; точный пример присутствовал в первой странице).
Read-only transaction подтвердила обе версии 1 и отсутствие номера в text keys.
Обе записи `purchaseNoticeKESMBO`, application UNKNOWN; второй предмет — услуги
комплексных испытаний/диагностики, а не краны. Намеренного исключения этих записей
в наблюдённом пути нет.

Теперь полный ASCII-номер (11 цифр для 223, 19–23 для 44) означает точное
строковое равенство `purchase_number`; ведущие нули сохраняются, края `strip()`.
Остальные запросы продолжают прежний текстовый путь. Новых endpoint, миграций,
переиндексации, загрузчиков или scheduler нет. Формы явно называют полный номер.
Evidence: `PURCHASE_NUMBER`, исходное значение, XML-локатор identity, существующие
номер версии/SHA/source metadata. Совпадение не означает соответствие ТЗ или допуск.

## Acceptance / evidence

| Проверка | Результат |
|---|---|
| Оба заданных номера через реальный PostgreSQL/API и обычную форму 223 | PASS, по 1 карточке |
| Пробелы/табуляция/перевод строки на краях API; пробелы UI | PASS |
| `00016445250` и `0000000000000000001` | PASS, нули сохраняются |
| `32699999999` | HTTP 200 / пустой массив, UI явно показывает 0 |
| Text «кранов шаровых» | 3 из 500 синтетических current 223 notices |
| Tenant подмена query-param и чужая более новая версия того же номера | PASS, свой tenant/version |
| Без bearer / другой tenant без записи | 401 / HTTP 200 с пустой выдачей |
| Latest version, read-only поиск, пагинация | PASS; audit/counts не меняются |
| 44 missing derived keys и source hold | PASS: номер без keys найден; hold исключён |
| 44 deadline scope / `exclude_failed` / `require_documents` | PASS; исключение сохраняется |
| 223 hidden source flag | FAIL сохранён; точный номер не разрешает действия |

Просроченная 44 карточка по умолчанию исключается. Существующий переключатель
«Включить закупки с истёкшим сроком» использует `ALL_CACHED` и показывает её с
`FAIL`; он не снимает source hold или tenant isolation. 223 unavailable metadata
сохраняет действующий контракт: evidence-карточка может быть видна, участие FAIL.

Owned files: `sources/eis_index_search.py`, `storage/eis_index_query.py`,
`storage/eis_223_index.py`, две `indexed-*-search.tsx` формы, два новых test modules,
этот отчёт/индекс и один synthetic runtime test в `test_eis_search_capture.py`.
Последний раньше зависел от frozen source SHA: после изменения matcher он
останавливался до проверяемого runtime. Только его временный synthetic plan
теперь pin-ит текущие файлы; frozen benchmark plans и production pin verification
не изменены. Общая оптимизация и quality benchmark не входят в срез.

## Проверки и ограничения среды

Focused Python/API: 84 PASS до добавления extra source/expiry/hold cases;
финальные новые unit cases: 10 PASS; новые real PG/API cases: 7 PASS, без skips.
Existing 44/pagination PG: 22 PASS; existing 223 PG: 18 PASS (12 + 6 corrected reruns).
Ruff, mypy domain (21 files), 9 doctests, 7 discovery Node tests, TypeScript,
ESLint, optimized Next build PASS. Финальный полный Python gate:
3233 PASS / 639 explicit skips / 0 FAIL.
Default Python gate не подключает PostgreSQL; его skips не считаются PG proof.

Два первоначальных расширенных migration-gate запуска не прошли: сначала
не выполнены dedicated role/database/disposable guards, затем CLI `pytest`
не включил root для import `migrations`. Подход пересмотрен: отдельная БД
`procurement_eis_test_20261005_s209`, роли по existing contract и `python -m pytest`;
повторены только 6 отказавших checks, все PASS. Новый helper не добавлялся.
Первый missing-key fixture пытался DELETE append-only keys и был отвергнут БД;
исправлен штатной существующей test-technique: пропуск derivation при synthetic intake.

UI: обычные Next Server Actions → API → PostgreSQL; browser evidence из `next dev`.
Локальный `next start` заблокирован автоматической проверкой разрешений без
указанной причины; optimized build проверен, runtime этой сборки не подтверждён.
Production не менялся. PostgreSQL локально 18, Python 3.13.9, Next 16.3.4, Windows.

## Replay реальных примеров

Локальный baseline старше deployed source: его parser/schema не поддерживают
`purchaseNoticeKESMBO` и by-number windows, а deployed text matcher уже оптимизирован.
Первый импорт exact XML через старый локальный intake был честно отвергнут
`WINDOW_INVALID`. Подход изменён: восстановлена отдельная копия 210 deployed Python
files и exact двухзаписочная projection (windows/blobs/archive sources/notices),
оригинальные SHA blob/XML проверены, только в disposable local DB
`procurement_eis_test_exact_replay`. Её check constraints восстановлены из deployed
catalog; product migrations/schema и загрузчики в Git не менялись.

На эту локальную копию применены только три поисковых изменения. Для 44 matcher
адаптирован один контекст hunk к уже установленному prefilter; установленная
оптимизация не заменена старой. Отдельный `exact-search-deployed-base.patch`
сохранён рядом с worktree для review относительно deployed baseline.
GET API нашёл каждый оригинальный номер, version 1, точный XML SHA, application
UNKNOWN. Неправильный номер дал 200/0; оба текстовых пути также сохранились.
UI обоих реальных примеров PASS через тот же обычный экран / Server Action,
каждый номер даёт одну карточку с оригинальным предметом и UNKNOWN подачи.
41 number/text unit cases также PASS с deployed source overlay. Старый UI baseline
не именует family KESMBO в обзоре способов; добавлен явный `Способ закупки UNKNOWN`
для отсутствующей UI-метки вместо пустой категории/React key warning. Наличие
карточки и реквизиты проверены; общий family-каталог не расширяется.

UI POST `/tender-discovery` для этих двух обычных действий вернул 200:
121/109 ms в `next dev` (сам Server Action 52/39 ms). По одному наблюдению,
без cold compilation; это серверная длительность POST, не browser paint latency.
Source copies/raw XML и projection не включаются в коммит или synthetic tests.

## HTTP response time

`httpx.Client`, persistent loopback TCP → uvicorn → PostgreSQL/RLS,
`GET /v1/tender-discovery/eis-223-index?query=...&page_size=100`, настоящий local bearer.
500 синтетических current notices / 5 windows одного tenant: 3 cranes, 497 paper.
Для каждого запроса 3 warm-up + 20 измерений последовательно, `perf_counter_ns`,
полное HTTP получение ответа; p95 — nearest-rank. Cold starts исключены;
во время замеров шли локальные проверки. Это не оценка production-корпуса.

| Запрос | Matches / evaluated | Median ms | p95 ms | Min–max ms |
|---|---:|---:|---:|---:|
| `32616445250` | 1 / 1 | 29.40 | 36.26 | 27.75–98.22 |
| `32616445747` | 1 / 1 | 29.68 | 32.91 | 27.20–34.04 |
| ` 32616445250 ` | 1 / 1 | 30.22 | 33.26 | 25.32–35.11 |
| `00016445250` | 1 / 1 | 30.33 | 35.00 | 24.63–45.34 |
| `32699999999` | 0 / 0 | 20.86 | 33.62 | 18.73–35.19 |
| «кранов шаровых» | 3 / 3 | 37.37 | 42.91 | 27.83–44.22 |

Отдельный replay двух оригинальных карточек: те же HTTP условия, 3 warm-up +
20 sequential measurements, deployed source overlay, отдельная isolated DB.
`32616445250`: median 31.88 ms / p95 37.18 ms; `32616445747`: 27.82 / 30.95 ms.
С пробелами: 29.19 / 31.10 ms; отсутствующий номер: 19.81 / 22.63 ms.
Это timings двухзаписочного replay, их нельзя сравнивать как ускорение production
с его 25630 notices. Production number reads (98/64 ms) — одиночные наблюдения
старого пути с пустым результатом, а не benchmark до/после.

Следующее действие: review ограниченного diff от `5edcadb`; deployment требует
отдельного разрешения и сюда не входит.
