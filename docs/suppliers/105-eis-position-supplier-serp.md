# S223 — публичная выдача для поиска снабжения позиции ЕИС

Статус: COMPLETE и установлен на VPS, 2026-10-06. Цель — находить новые сайты производителей и
поставщиков по выбранной позиции закупки без платного API поисковых систем.

## Контракт

`POST /v1/tender-discovery/eis-supplier-serp/prepare` принимает только точную
позицию сохранённой версии ЕИС и `refresh`. Запрос строится на сервере:
публичное наименование позиции + «производитель поставщик купить оптом».
Фрагменты документов, внутренние цены и контакты не добавляются в запрос.
Подготовка доступна OPERATOR; чтение — авторизованным ролям своего tenant.

Обычный Chromium последовательно открывает одну страницу Bing, Яндекса и Google.
Браузер не использует личный профиль, маскировку, обход CAPTCHA или смену IP.
CAPTCHA/403/429 сохраняются как отдельные отказы. BLOCKED вызывает паузу на час,
RATE_LIMITED — на 15 минут. Google/Яндекс пока не имеют подтверждённого адаптера
органической выдачи: доступная новая структура получает SOURCE_CHANGED.

До 20 секунд на источник, 75 секунд на пакет, 90 секунд на изолированный процесс.
Один браузерный поиск на tenant и один процесс на API. До 10 ссылок на источник,
до 50 разобранных строк, DOM до 2 MiB, ZIP до 8 MiB. До 20 начатых поисков в час
и 64 MiB сохранённых ZIP с DOM за скользящие 24 часа на tenant; перед стартом резервируется 8 MiB.
В отчёте source_requests считает переходы к поисковикам, а не все HTTP-запросы
ресурсов страницы. Переходов на сайты найденных кандидатов в этом этапе нет.

## Evidence и поведение

STARTED и итог — отдельные неизменяемые записи с audit. Неизвестная ошибка после
начала внешней операции сохраняет STARTED/UNKNOWN. Последняя неудачная попытка
не скрывается предыдущим успехом. DOM хранится в приватном ZIP, ссылки связаны
с SHA256 и локатором исходной выдачи. GET-содержимое недоверенно.

`read` и повторный `prepare` без refresh читают сохранённый результат с source0.
Refresh доступен через 15 минут и ограничен cooldown отдельных поисковиков.
Новая версия или неоднозначность источника ЕИС блокируют старое основание поиска.

Ссылка и сниппет — кандидаты для проверки. Supplier identity, price, stock,
delivery, technical, quote, participation и полный охват остаются UNKNOWN.
Позиция в поисковике не является рейтингом выгодности предложения.

## Проверка доступности 2026-10-06

Обычный Chromium на VPS: Bing HTTP200, 1.934 с, 116299 байт DOM, 10 органических
строк по пробному запросу про бумагу. Яндекс — CAPTCHA, Google — unusual traffic;
оба остановлены. Дополнительные единичные пробы: Brave429/CAPTCHA,
DuckDuckGo202/challenge, Yahoo500, Mojeek403, Rambler проверка робота.
Это измерение одного запроса; качество поставщиков и стабильность не доказаны.
Приватные DOM и SHA256 сохранены в `vibe-seller-state/s223-proof` на VPS.

Google описывает программы поиска и общий IP VPS/VPN как возможные причины
проверки unusual traffic: [официальная справка](https://support.google.com/websearch/answer/86640?hl=en).

## Следующий этап

Ограниченное чтение сайтов найденных кандидатов с защитой исходящих запросов:
подтвердить производителя/поставщика, товар, характеристики, единицу, упаковку,
партию, цену, НДС, наличие и срок. Затем сравнивать полную сопоставимую стоимость
и формировать проект запроса КП. Отправка КП требует exact-payload approval.

## Release evidence

- Изолированный PostgreSQL: 263 Python/API/PG теста PASS, 49.98 с, zero skips.
  Log SHA256: `cedf66767bc52af7a431e8794673cb4df216c90cc7a34e894f9be14f57725fc1`.
- Node wire/render: 63 PASS (8 новых + 55 предыдущих); TypeScript, ESLint и
  production build PASS. Build SHA256:
  `63b17e9d57e749ad44a1f6503f9b6ed701a724203c263916957606e98956b08c`.
- Read-only Astra/source и S203/storage/API/runner reviews закрыты. Исправлены
  CAPTCHA с organic rows, потеря navigation при cancellation, cleanup всех
  subprocess путей, вытеснение cooldown записями source0 и ложный ноль после ошибки.
- Live 10:24:37 UTC: exact `0107300009526000178`, version 2, source_index 1,
  XML `4818c9530f94e544bdec54163e3c740bf7b3bb43770dc5f4b04c780e095b2a02`.
  Запрос «Бумага для офисной техники производитель поставщик купить оптом».
  API prepare 3762 мс: PARTIAL, Bing COMPLETED / 10 ссылок / 735 мс;
  Яндекс BLOCKED / 300 мс; Google SOURCE_CHANGED / QUERY_BINDING_INVALID / 244 мс.
  Отказы не являются EMPTY. Bing среди результатов показывает маркетплейсы,
  магазины и нерелевантные страницы; supplier identity и цена не установлены.
- Сохранены STARTED + итог, 2 audit события. Read 92 мс/source0; повторный prepare
  1568 мс/source0 (включает запуск изолированного процесса). Никаких supplier-page
  requests или новых ЕИС jobs. Live proof SHA256:
  `2a6c4758cf2aa77fb48e83b2e06f0387f1e84a3482bbd92c556328f7ccfce54e`.
- Installed Next Actions + compiled SSR: read 125 мс, prepare cache 1590 мс;
  реальные ссылки, SHA и статусы отображены, negatives PASS. Визуальная проверка
  браузером NOT_PERFORMED. Proof SHA256:
  `6ab334fa2d75ab6187af91cf155586a158227c2749df743d677700f6ed542062`.
- Schema `20261006_04`, health200, test DB0. DB 5724314647 байт; free disk
  251060453376 байт. API 1 GiB и web 768 MiB, OOMKilled=false; после запроса
  оставшихся Chromium/Playwright процессов 0, idle API118 MiB/web66.7 MiB.
  Обычный маркер 223-refresh был активен; плановые workers не останавливались.
  Operations proof SHA256:
  `8f63c032b89979e1e03546d7f2585263ccbe3b486f87f430f1a83c4e86f631d3`.
- Installed image pins: API
  `sha256:2c6abdeefaa124cfa0663f200461499c83e7a398380da8db68140bd82cd73706`;
  worker `sha256:ef46bc7c7b942ab43ded92e4bea021e86989a4441f43b1fa69e2826040839946`;
  web `sha256:7961aea14c06b66ffea35f86f820e034f48c707aab58478f47a46e6be7e313ef`.
  Полный manifest: 203 файла, API/worker по 40, web54. Cron SHA не менялся:
  `012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`.

Это готовый этап обнаружения сайтов. Сравнение выгодной закупочной цены,
проверка комплектации и полное КП ещё не реализованы для найденных сайтов.


## Отмена дополнительных источников, 2026-10-06

Brave Search, DuckDuckGo HTML и Mojeek удалены из активного поиска по запросу
пользователя: успешная реальная выдача не подтверждена. Runtime/parsers/fixtures
дополнительных адаптеров убраны; новые попытки снова policy v1 с Bing/Яндекс/Google.
Отозванное решение и причина — [ADR0103](../adr/0103-supplier-serp-fallback-engines.md).
Сохранённые v2 отчёты читаются без source I/O и не означают доступность метода.
Их имена engines/URL/locators сохранены только как historical wire metadata;
request allowlist исключает отозванные источники. Уже записанные audit/evidence
не изменяются. На сервер расширение не устанавливалось.

### Почему ноутбук и сервер дают разные результаты

Read-only SSH inspection установленного API 2026-10-06 подтвердил только
BING/YANDEX/GOOGLE, Chromium `headless=True`, fresh `browser.new_context()`
и filtered resource routes. Personal browser profile не используется.
Локальный CLI каталога использует `launch_persistent_context` и поддерживает
headed Chrome/Edge. Это разные режимы. Прежний адаптер пользователя найден и проверен ниже.
Политика сети также может отличаться: домашний и VPS IP не взаимозаменяемы.
Google официально описывает автоматизированный поиск и общий сетевой IP среди
причин unusual traffic:
[официальная справка](https://support.google.com/websearch/answer/86640?hl=en).
IP как конкретная причина текущего отказа не доказан сравнительным экспериментом.

По сохранённому S223 proof Bing на VPS давал 10 ссылок. Яндекс блокировался;
Google получал QUERY_BINDING_INVALID. Кроме доступности, Google/Яндекс
не имеют реализованных organic parsers: даже доступная новая структура
остаётся SOURCE_CHANGED. Возможность вручную искать на ноутбуке не доказывает
работоспособность серверного extraction adapter.

Проверка отмены: 90 Python source/API/runner/real PostgreSQL PASS без skips;
20 Node SERP/page wire/render PASS, full TypeScript и ESLint PASS;
Ruff всего repo и проверка документации PASS. Новых запросов к отозванным
источникам нет; archived v2 → active v1, общий cooldown и immutable history
проверены на isolated PostgreSQL. Full production build после отмены не повторялся;
это ограниченное изменение wire/UI текста, предыдущая сборка до отмены прошла.


### Проверка прежней методологии напрямую из Python

По уточнению пользователя найден исходный `yandex_procurement_adapter.py` в
`C:/Users/elkgo/Documents/ChatGPT/zakupka-robolaba/research` вместе с его venv,
ChromeDriver и выделенным `sessions/yandex_chrome` профилем. Это ordinary visible
Chrome, запущенный subprocess с локальным debug port, затем Selenium attachment;
ни браузерное расширение Codex, ни Windows UI automation не нужны.
Именно этот неизменённый адаптер выполнен с `--headed --fresh --card-check --restart-check`.
Запрос: «Бумага A4 80 г/м2 500 листов», интервал15с, cache не используется.

- Market search: live HTTP200, 19 предложений, 9.11с.
- Открытие карточки SvetoCopy A4: live HTTP200, заголовок и цена видны, 5.30с.
  Показанная 430₽ отмечена как Пэй; это не доказательство обычной цены или КП.
- После restart того же профиля: live HTTP200, 19 предложений, 9.31с.
- Original report `verification=passed`, три страницы `source=live`.

Report/HTML/PNG лежат в `research/results/session-20261006-232922-024343`.
Дополнительно ordinary visible Chrome + Selenium attach с новым отдельным
persistent profile открыл Google с точным supplier query; видимая выдача и девять
связанных заголовков сохранены в `research/results/search-diagnostic-20261006`.
Это manual availability proof, не законченный adapter organic extraction.

Тот же Market search URL с VPS: unfiltered headless Chromium/fresh context,
HTTP403, title403, product snippets0, DOM3370байт,
SHA256 `e214ae85ddc7ca8be8f3a7beced5e3305740c3a794a7be025e0d8898df7a9eb8`.
Различие воспроизведено; влияние network/IP, browser build/platform и mode/profile
не разделено контрольным экспериментом. Часы VPS и ноутбука отличаются;
порядок действий подтверждён tool outputs. Копирования cookies/profile на VPS,
CAPTCHA solving, прокси-подмены и production изменения не выполнялись.

Evidence `session-20261006-232922-024343/report.json` SHA256 `1fc6599a47ca978278d694d3023b8117fad4b9741d1a0a629a03fb5110199bec`.

Evidence `search-diagnostic-20261006/google-visible.json` SHA256 `3199bc50b22225cba68da8417ef2154943454e6a3e2e3c3deedc72d9ce55c614`.

Evidence `search-diagnostic-20261006/server-market.json` SHA256 `fc544525aa892e929e7e8f8a9e6a16a396a68cf670cd5cfbdfd3b8bb497c524e`.

### Серверный persistent Chrome: срез 6–7 октября 2026

Контракт — [ADR0104](../adr/0104-persistent-headed-supplier-browser.md).
Владелец root: source/storage/runner, compose, три
`scripts/server-supplier-browser-*.py`, установка и этот отчёт;
Sol: `supplier_serp_browser.py` и его тесты; Astra: read-only review.

Новый транспорт запускает обычный headed Chrome под Xvfb напрямую, читает его
через localhost CDP, сохраняет отдельный tenant/origin профиль. Системные фоновые
расширения отключены, downloads запрещены через CDP, service workers обходятся
на странице и при обнаружении останавливают capture. Browser environment
не содержит DB/proxy secrets; профили и state приватны 0700/0600.

Chrome начинает без startup window; после attachment создаётся одна blank page.
Так прежние вкладки не открываются до установки request guards. Chromium
поддерживает keepalive с этим флагом и remote debugging до явного Browser.close
([исходный код](https://chromium.googlesource.com/chromium/src/%2B/bdf8b9b6d67b77a6b6e1dc98550cf2e417c14ec2/chrome/browser/devtools/chrome_devtools_manager_delegate.cc)).
Это headed browser: созданная через CDP страница имеет обычное окно на Xvfb.

Завершение: Browser.close внутри живого Playwright connection, ожидание Chrome
до двух секунд, затем bounded terminate/kill. SingletonLock должен исчезнуть;
оставшийся lock не удаляется автоматически и не вызывает создание нового профиля.
При аварии нужна проверка владельца/процессов и ручное восстановление точного
профиля; автоматическое копирование cookies или сброс cooldown отсутствуют.

Пауза минимум 15 секунд обеспечивается консервативной reservation 35 секунд
до запуска: максимум 20 секунд попытки плюс 15 паузы. Global-origin и tenant-origin
state сохраняются до I/O, BLOCKED — один час, RATE_LIMITED — 15 минут.
Координация рассчитана на один VPS/shared volume. Старый source0 и policy v1
не переинтерпретируются; immutable tenant audit получает revision и SHA source/helper.

**Реальная доступность:** regular Chrome153 на VPS показал CAPTCHA Google,
Яндекса и Маркета. Google и Market — unfiltered controlled probe, Яндекс —
с request filters. Повторных обращений после CAPTCHA не было; Google/Яндекс
cooldown перенесён из сохранённых observed timestamps в durable state.
Bing с filters дал 10 ссылок; часть результатов нерелевантна и не доказывает
изготовителя. HTTP200 CAPTCHA не считается поисковой выдачей.

**Ошибки, обнаруженные runtime acceptance:** фоновые component extension workers
при первом запуске, SIGTERM до завершения штатного close и restored tabs при
повторном запуске. Они исправлены; offline tests без live proof не заменяли
приёмку. Старые диагностические профили с stale SingletonLock сохранены отдельно
и не используются реальными tenant; автоматического удаления lock нет.

**Установлено:** четыре bounded модуля из pinned production baseline;
manufacturer migrations и local storage v2 не включались. На API включён
Docker `init: true`: он собирает orphaned browser descendants; после live capture
в контейнере остаются только docker-init/uvicorn, Chrome/Xvfb/zombie отсутствуют.
Фоновый ЕИС штатно уступал deployment окно по существующему priority marker;
Worker image, схема БД и frontend этим срезом не менялись.

Итоговый API image ID:
`sha256:8f96ca8123d6dfa94d18339ba18f859413847e6f86d808fdec542ff733cbdba3`.
Manifest: `/home/syurai/vibe-seller-state/supplier-browser-rollout/release-20261006-v8/manifest.json`;
его SHA256 `77e59cc5ca4f37e8ad70de28d96a7d6ff51ba378ab9ed9e712fabc83ffa8c82e`.
Runtime compose SHA256 после init:
`9626ce47c1151743572f3a5b5d7723d708f5e0f5c008d7840b658eb3f5b55026`.
Host/container hashes четырёх модулей и executable/import smoke PASS.

Acceptance: 101 source/helper/API/runner/version Python tests и 4 real PostgreSQL
tests PASS без skips; Ruff и docs PASS. Это ограниченный срез, не полный suite.
Staged same-profile restart между разными контейнерами и installed repeat —
Bing COMPLETED10; installed после init — COMPLETED10, одна navigation, 4.615с.
Google/Яндекс cooldown после restart — source0.
API `/health` 200; старый saved report прочитан без I/O до новых запусков.

**Полный установленный persisted путь:** обычный subprocess runner с tenant
`local-eis-supplier`, actor `server-methodology-acceptance`, exact saved position.
Создан run `237c69fc-4d88-4477-8646-797d9d96048b`, policy v1, PARTIAL:
Bing COMPLETED10/3.946с/source1, Яндекс и Google COOLDOWN/source0.
ZIP36034байт, SHA256
`71ec7f1d915bd71739e945d9d1f8ce439f9480571ef5b1d428a53602f77c5dbd`.
Повторное чтение вернуло идентичный report, source_requests0.
Immutable audit реально содержит revision `headed-chrome-cdp-v1`, source SHA
`5ae38b5cfa131131bd8238c87d6af1b96d3f59243f694640dfd87ac095ceabd0`
и helper SHA `92b993bb0bc3e77f4645c226f147fc90137608ab0a59a3130eebc2e818676c83`.
Цена/наличие/роль/техника/КП/PARTICIPATE не подтверждались.

Private evidence лежит в серверном `supplier-browser-rollout/evidence`;
локальные копии JSON — `data/eis-pilot/supplier-browser-rollout`.
`installed-persisted-prepare.json` SHA256
`fed81ab192dfd37818ba7fe5af85df2e65f6ff3b6119d6cc680f18ca3c5d7cb7`;
`installed-bing-init-final.json` SHA256
`766ea35b9d176ee3fa00c0635ba4c183f3348a70ca933f52dbfe6bc3230ec3b3`.
Доступность Google/Яндекса/Маркета и product acceptance всего поиска остаются
незавершёнными; этот выпуск подтверждает транспорт и ограниченный Bing путь.
