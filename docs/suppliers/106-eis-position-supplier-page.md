# S224 — чтение сайта кандидата и опубликованные цены

Статус: COMPLETE в описанных границах, установлен на VPS 2026-10-06.
Один выбранный сайт из сохранённой поисковой выдачи.

## Контракт

API `eis-supplier-page/prepare` принимает точную позицию ЕИС, UUID сохранённого
SERP run, engine, исходный rank и strict boolean refresh. Клиент не передаёт URL.
Сервер выводит ссылку из immutable отчёта своего tenant, проверяет SHA отчёта и
действующее основание позиции. `read` и повторная подготовка возвращают последнюю
попытку без сети; неудачный refresh не скрывается старым успешным результатом.

Один HTTPS HTML документ: DNS проверяется полностью, TCP соединяется с проверенным
IP, TLS проверяет исходное имя. Запрещены внутренние адреса, mixed DNS, downgrade,
credentials, нестандартный порт. Не более двух redirects, трёх попыток чтения,
2 MiB HTML, 30 секунд транспорта; child ограничен 40 секундами и 10 CPU секундами.
Без proxy environment, cookies, браузера, JavaScript и подресурсов. Блокировки и
CAPTCHA сохраняются как отказ. Счётчик source_requests отражает попытки dispatch,
в том числе неуспешный TLS; это не доказательство отправленного HTTP-запроса.

JSON-LD Product с прямыми Offer/AggregateOffer даёт заявления сайта о товаре,
бренде, производителе, продавце, артикуле и цене. Decimal передаётся строкой.
Каждый факт имеет SHA256 сохранённого HTML и locator. Нижняя/верхняя границы
AggregateOffer показываются отдельно. Контекст категории и статьи сохраняется.
Нет удалённого JSON-LD resolution и произвольного выполнения содержимого.
Поддержано чтение UTF-8 JSON-LD. Другие способы разметки, JS цены и отдельные страницы товара требуют следующих
адаптеров. Это ограниченное чтение, а не полный охват сайта.

Официальные определения: [Product](https://schema.org/Product),
[Offer](https://schema.org/Offer), [AggregateOffer](https://schema.org/AggregateOffer).

## Хранение и границы

STARTED и итог — immutable tenant rows с audit. Неизвестный сбой после начала
оставляет STARTED/UNKNOWN. Cache не загружает сырой body. Исходный HTML приватен
и не выдаётся интерфейсу. Один slot на tenant и API, refresh через 15 минут,
30 начатых чтений за час, 64 MiB HTML за 24 часа с резервом 2 MiB перед чтением.

COMPLETED отчёта означает сохранённый исход попытки; source observation может
быть BLOCKED, TIMEOUT или иной ошибкой. Наличие товара в разметке не подтверждает
продавца, единицу продажи, минимальную партию, НДС, остаток, доставку или срок.
Техническое соответствие, сопоставимость цены, полное КП и участие UNKNOWN.

## Проверки

Read-only source и storage/API/runner review: PASS. Проверены SSRF/TLS/redirect,
ограничения HTML/JSON, Article/category ambiguity, Decimal и DTO coherence.

### Release evidence

- Финальный изолированный PostgreSQL: **336 Python/API/PG PASS**, 56.12 с,
  zero skips. Включены current-version/hold, exact parent, RLS, immutable body,
  резерв daily budget, refresh cooldown и latest STARTED после ошибки.
  PG log SHA256: `04e25856743c6ce7a2f295c077569d3d2658fba148f4549fb1dcc602ba3d6065`.
  Code manifest SHA256: `4fd6134b69c14f7ab50f24ac4d6776b83b78bf4b8421c3addf692e818b194184`.
- **73 Node wire/render PASS**, включая 10 новых S224; TypeScript/ESLint/Next
  production build PASS. Build SHA256:
  `a8ca13d3f3890b79bd19ee68328e6fe07d1166e02f24850bbdc75ad24994c2fa`.
- Source 52 локальных теста PASS. Независимые reviews закрыты. Настоящий PG поймал
  self-referencing FK в frozen migration; исправлен на parent SERP. После исправления
  Astra сравнил весь frozen TABLE_DDL/indexes с compiled PostgreSQL model: совпадение.
  Web review поймал принятие products при LIMIT_EXCEEDED: исправлено и проверено.
- Live API 10:55:47 UTC для трёх exact ссылок Bing сохранённой позиции бумаги:
  «ВсеИнструменты» HTTP403/BLOCKED; «Комус» HTTP200, 261749 байт HTML/EMPTY,
  товары/цены не извлечены. Подготовка 1893–2774 мс с child startup;
  чтение сохранённого результата 73–92 мс/source0, повторная подготовка
  1560–1614 мс/source0. STARTED+final: 6 rows, 6 audit events. Jobs0.
  «Бумага-С» первоначально дала ложный TRANSPORT_FAILED после HTTP200 из-за
  закрытого сокета при Content-Length EOF; эта immutable попытка сохранена.
  Live proof SHA256: `e212458b641676005a1439eb3cd2710e221a5923d6c6696951dc57ebc5be8869`.
- Исправленный EOF reader установлен 11:00:12 UTC; три регрессии используют
  настоящий HTTPResponse для Content-Length/chunked/connection-close.
  Одна отдельная bounded source diagnostic для той же сохранённой «Бумага-С»
  ссылки: HTTP200/COMPLETED, 46595 байт, **314 мс**, EMPTY, цен0. Source1,
  database writes0. Body SHA256:
  `e4d69e89486e471337feb6849a84ec57eb1ad175be524a98ead1f44a61dd2ff2`.
  Proof SHA256: `fc3f667c98343e835c3d30705f2136bc97527b35c29ab7c11dbd684f2ae70656`.
  Diagnostic не заменяет сохранённую API попытку и не обходит API cooldown;
  интерфейс при replay честно показывает старый исход до обычного refresh.
- Финальная installed Next Action + compiled SSR проверка 11:01:20 UTC:
  read82–152 мс/source0; cache prepare1570–1600 мс/source0. Wire/рендер/negatives
  PASS, новых source calls/writes0. Browser visual check **NOT_PERFORMED**.
  Proof SHA256: `dd9f5ab87cbb25850518a6ad06133d1d5ac30a5ccd49aeac3249b5bae76618de`.
- Schema `20261006_05`, health200, disposable test DB0. DB5792332823 байт,
  free250775691264 байт. API117.6MiB/1GiB; web62.6MiB/768MiB;
  OOMKilled=false. Remaining source helpers0, rows/audits по6.
  Operations SHA256: `f047249f03f09a9627d3227e04b40cfb8fee300fee44109f23b4be11904c8eaf`;
  cleanup SHA256: `f49e80751a3e2624a53b2884340848b40cd7a5095c717f31ac1699381c0b5be0`.
  Обычная загрузка ЕИС не останавливалась; активный 223 marker завершился сам.
- Installed image pins: API
  `sha256:0a2ce2d69c85e0542bbda03e23601a16cb6e728c483cca8ca7321a61f85f6422`;
  worker `sha256:2c35a16ed5c5fc1372484ba626bd6f96fd4816d425c6338adf4b6d95b5529fa8`;
  web `sha256:8da3b8adf0d32a75e32b22de4be543c1fb70ab2f1568780b6998ca88097206c3`.
  Manifest221, API/worker44, web61. Cron SHA неизменен:
  `012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`.

В синтетическом контрактном fixture проверены точная цена 562957.00 RUB и
диапазон 540000.00–610000.00 RUB. **Реальные три ссылки не дали извлечённых цен**.
Это готовый этап чтения и сохранения исходов; выгодный поставщик ещё не найден.

### Как проверить в интерфейсе

В карточке ЕИС выберите позицию → «Искать в интернете» или «Открыть сохранённую
выдачу» → под конкретной ссылкой «Проверить сайт и цены». Для сохранённого исхода
есть «Открыть сохранённую проверку»; обновление ограничено 15 минутами.

## Следующий срез

**S225:** перейти от главной страницы/категории к конкретным карточкам товара.
Ссылки выводить из сохранённого HTML с locator/SHA; ограничить число выбранных
страниц и повторно применять SSRF/tenant/current/budget gates. Сначала проверить
подходящие ссылки source0 на реальных HTML «Комус» и «Бумага-С», затем реализовать
один проверяемый adapter. Не объявлять отдельную страницу полным охватом сайта.

Затем связать конкретное предложение товара с характеристиками позиции и выбранными
фрагментами документации ЕИС. Проверять обязательные требования в PASS/FAIL/UNKNOWN.
Полную стоимость партии считать только при известных сопоставимых условиях;
при нехватке условий подготовить draft RFQ. Отправка требует exact-payload approval.
