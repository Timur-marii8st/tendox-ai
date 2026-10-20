# Бенчмарк поиска ЕИС — S134 / P1a

## Контракт

Baseline фиксирует 24 товарных запроса, три последовательных запуска локального
API на каждый и восемь страниц публичной ЕИС для шести запросов. Группы — бумага
и серверы: синонимы, аббревиатуры, форматы, характеристики и естественная фраза.
Версионируемый набор: `scripts/benchmarks/eis-query-suite.v1.json`. Intent нужен
для будущей разметки, он не доказывает релевантность результата.

Запросы последовательные, документы не скачиваются, закупочные кейсы и заявки
не создаются. Общий cooldown ЕИС сохранён; BLOCKED/429 останавливают внешний
обход. Локальный benchmark прекращается на первом timeout/401/403/429, чтобы
не накапливать незавершённые запросы. Providers/подписки не подключаются.

## Метрики

| Метрика | Интерпретация и границы |
|---|---|
| API duration | Wall time HTTP + чтение + валидация JSON; без анализа документов и экономики |
| p50/p95 | Nearest rank успешных запросов; sample size/ошибки отдельно. Три повтора — предварительный baseline, не SLA |
| Wait ms | Ожидание общего cooldown перед запросом; входит в полный обход, не в duration |
| Raw distinct/pages | Номера всех идентифицируемых строк до title-match; не доказывает исчерпание выдачи |
| Reference ID overlap | Пересечение публичной выборки и API top-100. Law/stage/date/source scope различаются, поэтому это не recall |
| Source watermark age | Возраст максимальной известной публикации; другие регионы/типы могут отставать сильнее |
| Ingest watermark age | Возраст ingestion; не подтверждает актуальность источника |
| FAIL в top-10 | Известные заблокированные кандидаты; остальные остаются UNKNOWN |
| Precision@10 | Только уникальные первые 10 с полным REVIEWED покрытием exact evidence; не допуск и не прибыль |
| Known reference recall@10 | Retrieval известного REVIEWED version-bound subset; не всей ЕИС |

Без разметки precision/recall — null/UNKNOWN. PROVISIONAL и UNKNOWN не считаются
положительными judgments; неполная разметка допускает лишь нижнюю/верхнюю
границу precision. Отсутствующий provenance, конфликт версий или устаревший
SHA не дают положительную оценку. Наивная/будущая дата не превращается в
свежий watermark. Таймауты остаются в ошибках; p95 успехов показывается вместе
с числом failures. Full corpus recall всегда UNKNOWN.

`labels-template.json`: query intent, номер, XML SHA, точный snapshot/локатор,
PROVISIONAL/UNKNOWN. Это заготовка, не эталон. Reviewer проверяет bytes/версию,
указывает verdict/reason/reviewer. При пересчёте проверяются SHA evidence и
tenant; путь вне scoped directory отклоняется. Локатор указывает конкретную
строку snapshot. Новая версия требует новой разметки.

## Ошибка, найденная baseline

Первый запуск дал три ReadTimeout по 30 секунд на «бумага для принтеров».
Сохранены 12 observations: девять успешных ответов, три ошибки; запуск остановлен.
Prefilter/comparator считали «для» самостоятельным достаточным совпадением.
Regression воспроизвёл подбор кресла для кабинета по запросу о бумаге.

Read-only SQL distinct номеров среди **всех известных версий**: ключи
`бумаг, для, принт` — 37 008; `бумаг, принт` — 1707. Это селективность ключей,
не коэффициент ускорения или полный recall. Runtime SHA до исправления
сохранены в `runtime-before-fix.json`.

В S134 comparator и PG prefilter используют `search_query_keys_v1`:
`для, при, или, как, это, что` исключены **только из запроса**. Без товарных
токенов — QUERY_INVALID. Persisted `search_keys_v1` и title/item tokenization
не меняются: прежние ключи — безопасное надмножество новых query keys;
миграция/reindex не нужны. Admission/deadline/экономика не меняются.

Остальные ограничения v1 сохраняются: токены короче трёх символов пропускаются,
А4/А3/80 не гарантируют фильтрацию. Такие признаки требуют отдельного контракта.
Effective query keys сохраняются в observations, чтобы видеть этот пробел.

Дополнительный read-only `reference-membership.json` проверяет public номера
по текущим известным версиям tenant corpus, вне ограничения API top-100.
Содержит aware время, номер/версию/XML SHA/название/source member и даты.
Отсутствие в этой БД означает только отсутствие в локальном известном корпусе,
не отсутствие в ЕИС. Scope/reference overlap остаются UNKNOWN; это не recall.

## Запуск

```bash
cd /home/syurai/vibe-seller
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T \
  --no-deps -v /home/syurai/vibe-seller/scripts:/app/scripts:ro \
  -v /home/syurai/vibe-seller/.env:/run/benchmark.env:ro \
  worker python /app/scripts/server-eis-query-benchmark.py \
  --suite /app/scripts/benchmarks/eis-query-suite.v1.json --public
```

Token отправляется только private `api`/loopback. Заголовки, token и exception
strings с телами/секретами не сохраняются. Pilot tenant `local-eis-supplier`
совпадает с API конфигурацией; другой tenant требует отдельной авторизации,
нельзя менять лишь метку при прежнем token.

Evidence в постоянном томе:
`/var/lib/eis-browser/research/search-benchmark/local-eis-supplier/<UTC timestamp>/`.
Каждый запуск создаёт новый каталог. Raw JSON/HTML, suite, metadata, observations,
report JSON/Markdown и template tenant-scoped. Metadata содержит SHA suite,
runner/поискового кода и Python version. Ответы имеют SHA/URL/aware timestamp/bytes.
Исходники предыдущего запуска не перезаписываются. На ноутбук достаточно
скопировать отчёт; полный raw baseline хранится на VPS.

Повторный расчёт без обращений к источникам:

```bash
python scripts/server-eis-query-benchmark.py --report-only EVIDENCE_DIRECTORY \
  --labels EVIDENCE_DIRECTORY/reviewed-labels.json
```

P1a включает инструмент и измеренный baseline. Полный P1 требует независимого
эталона релевантности и сравнимых provider/scope измерений. Следующее направление
P2 — same-day lane и повторная сверка поддержанных официальных семейств;
годовой backfill не заменяет свежесть.

## Результаты

Before: `20261001T162735110884Z` — 12 observations, 9 успешных и три timeout
по 30,03 с; source/quality UNKNOWN. Этот незавершённый запуск сохраняется
отдельно, его p95 успехов не скрывает ошибки.

After: `20261001T163841605901Z`, 01.10.2026. 72/72 API запросов успешно,
ноль timeout/429. Медиана успешного смешанного набора — 1897,89 мс,
p95 — 5781,27 мс. Индекс — 75 222 текущие известные карточки в этом baseline;
background ingestion не остановлен, это временной снимок, не фиксированный
immutable корпус для всех будущих запусков. Три samples на отдельный query.

| Запрос | До | После, диапазон / p50 мс |
|---|---|---|
| бумага для принтеров | Три timeout >30 с | 2216–2314 / 2263 |
| бумага | 1721–1923 мс | 1723–1933 / 1806 |
| серверное оборудование | В before не измерено | 2976–3047 / 3011 |
| серверы | В before не измерено | 583–638 / 638 |
| система хранения данных | В before не измерено | 6306–6344 / 6330 |

Цель будущего поиска до 5 с p95 пока **не достигнута** на этом наборе.
Первые результаты — metadata/preliminary, не анализ ТЗ и не полный economics.
У «СХД» лишь четыре результата, три с FAIL: быстрота не означает полезность.

Восемь public requests прошли; нет повторов страниц 1/2 у бумаги и серверного
оборудования, все 800 raw вхождений имеют проверяемые номера. Объединение между
синонимами — 578 разных номеров. Отдельный membership snapshot нашёл 89 из них
в текущих известных версиях локальной БД. **Это не recall**: public имеет
44/223 + af, локальный scope ограничен семействами 44; первая выборка raw,
локальный API ранжирует по другой логике и отдаёт только top-100.

Public duration 1,815–23,640 с на страницу, без общего cooldown. Даже когда
API отвечает за секунды, восемь HTML запросов занимают несколько минут из-за
общей 60-секундной паузы. Это подтверждает роль HTML как ограниченного fallback,
а регулярного официального компактного индекса — как foreground search.

| Query | Public raw distinct | Есть в локальном corpus | Есть в API top-100 |
|---|---:|---:|---:|
| бумага | 200 | 29 | 2 |
| офисная бумага | 100 | 13 | 3 |
| бумага А4 | 100 | 12 | 1 |
| серверное оборудование | 200 | 19 | 15 |
| серверы | 100 | 35 | 34 |
| сервер | 100 | 35 | 34 |

Эти строки пересекаются между запросами, складывать их нельзя. Возраст
source watermark — примерно 19,7 часа, ingestion watermark — несколько минут:
свежая загрузка старых окон не доказывает свежий источник. Обоснован следующий
приоритет P2: foreground same-day + reconciliation существующего scope.

API тела 47 513 208 bytes; всего сохранённых ответов после исправления
59 103 338 bytes (~56,4 МиБ). Полные raw хранятся на VPS. Есть 234 template
labels, все PROVISIONAL/UNKNOWN; REVIEWED labels — ноль. Precision/known subset
recall и глобальные quality/freshness/coverage остаются UNKNOWN.

Observed SHA всех 80 ответов проверен повторным report-only. Executed runner
и три engine source snapshots дополнительно сохранены и сверены с runtime
metadata; metrics source snapshot сохранён отдельно. 84 профильных теста,
Ruff/strict mypy пройдены. API query fix развёрнут, worker image обновлён.
Labels/corpus presence не являются approval для участия. Providers не измерены,
сравнение с ГосПлан по скорости/полноте пока не заявляется.

Локальная небольшая копия reports/observations/metadata:
`data/research/eis-search-benchmark-2026-10-01/{before,after}/` (ignored).
After копия около 3,43 МиБ; raw JSON/HTML туда не перенесены. Полные snapshots
остаются в постоянном томе VPS. Финальный regression gate: 84 passed / 14,45 с.

## P1b1 / S139: короткие характеристики запроса (02.10.2026)

Persisted v1 GIN ключи сохранены. Название товара даёт длинный anchor для
prefilter; А4/A4, А3 и короткие числа участвуют в сравнении title либо одной
позиции вместе с её характеристиками. Разные позиции не объединяются.
Каждый найденный термин имеет source value, kind и XML locator. Числовое
вхождение в minimum/maximum не подтверждает диапазон или единицы: compliance
остаётся UNKNOWN. Запрос только «А4 80» отклоняется с пояснением.

На том же известном индексе (80 430 current cards, 1569 paper candidates)
before/after одиночные live измерения: «бумага А4 80» 2029 → 2952 ms,
«бумага А3» 2007 → 2790 ms, «бумага» 2107 → 2164 ms. Это сравнение на
фиксированном известном корпусе, не p95 и не benchmark полного ЕИС.
Раньше short modifiers терялись и первые 100 А3 все имели STRONG; после
исправления таких 42 из 100. UI показывает весь known candidate set:
97 all-word /1472 partial для А3. Частичные результаты остаются видимыми.

Пример А4/80: №0104100002226000036, XML SHA
`b40f72ef6ac9074c7bd22da6761edcebc0d90190e50c5e7fde5ac0634802335d`:
item name «Бумага для офисной техники», KTRU TEXT «А4», MINIMUM «80».
Происхождение доступно по точным XML locators в ответе; minimum не является
подтверждённой точной плотностью. Полные responses остаются на VPS:
`research/query-modifiers/local-eis-supplier/final-20261001T214744272774Z/`.
Малые summaries: `data/research/eis-modifiers-2026-10-02/` (ignored).

71 профильный synthetic test, 22 isolated PG integration gates, Ruff и strict
mypy прошли; API/worker/web развёрнуты, production web build успешен.
Browser проверил counters, XML evidence, ошибку short-only и сохранение
query/checkbox после server action. Native form reset дополнительно отменён:
отключённый refresh не включается после ответа. Independent relevance labels,
синонимы и provider comparison всё ещё не выполнены; общий P1 не завершён.


## S148 / P1b2: финальная проверка слов (02.10.2026)

Пятибуквенный GIN v1 остаётся coarse candidate prefilter. STRONG/PARTIAL и term
provenance теперь вычисляются Russian Snowball3.0.1 (pinned pure-Python); числа,
латиница и визуальные А4/A4 не смешиваются с русскими корнями. Cache16384bounded,
на cache miss отдельный mutable stemmer. Сохранены явные нерегулярные формы
маска/масок и lexical alias латексный/латекс. Это lexical matching, не semantic
requirements/admission. Производные слова и синонимы могут не совпадать;
например экспозиционный != экспозиция. GIN recall ограничен прежнимv1 ключом;
переиндексации и расширения morphological recall этим срезом не сделано.

Причина: query «экспозиции» раньше давал STRONG по экспортер/экспонаты.
На fixed31 exact XML snapshots осталось9, EOK v5№0348200080326000020 сохранён.
Fixed comparison0.168527s; API82975current/31coarse candidates/9matches622ms.
Это одно live измерение; общий quality/p95/globalcoverage UNKNOWN.
60 профильных synthetic tests, Ruff/mypy/uv lock check; API/worker deployed.
Только новая snowballstemmer3.0.1dependency относительно VPS, остальные версии
lockfile не изменились. Источник API и thread-safety:
[Snowball Python package](https://pypi.org/project/snowballstemmer/3.0.1/),
[Russian algorithm](https://snowballstem.org/algorithms/russian/stemmer.html).

VPS proofs в /var/lib/eis-browser/research/search-morphology/local-eis-supplier/:
s148-before.json SHA3bfd3199a9e7de9af698ccf2e9c1898dc5227dcd2cf81af6d4e22dac9f7008af,
s148-after.json SHA542eee51a5264e3dfdf4f40aa0009c6449e4a8092bf49d9761a3f40b7dcb9e01.
Независимых reviewed labels всё ещё0; удаление false-prefix matches само по себе
не подтверждает глобальные precision/recall. Все доказательства/bytes на VPS.
