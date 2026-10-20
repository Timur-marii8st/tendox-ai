> Исторический README до реорганизации; не источник текущей готовности.

# Syurai Procurement — виртуальный тендерный отдел

Система ведёт закупочный кейс компании-поставщика от непрерывного поиска процедуры
до оплаты выигранного контракта: извлекает требования, применяет юридические и
коммерческие hard gates, ищет поставщиков, собирает КП, считает три сценария
экономики и готовит объяснимую рекомендацию.

Ключевой принцип: **ИИ извлекает и предлагает, детерминированные правила решают,
юридически значимое действие подтверждает человек**. Зелёный рейтинг не может
перекрыть запрет, `FAIL` или `UNKNOWN` по обязательному требованию.

## Текущий статус

S1, первый серверный срез S2 и внутренний экран S3 завершены в зафиксированных
границах. S4 продолжается: к 2026-09-18 завершены шестьдесят ограниченных срезов
конвейера документов. Реализованы tenant-scoped immutable-загрузки и безопасное
нативное извлечение PDF/DOCX/XLSX, отдельные ZIP-пакеты, локальный русский OCR
PP-OCRv5, построчные confidence/bbox, строгий маппинг фактов, золотой набор и
fail-closed workflow калибровки с SHA-256 evidence. Scan-only PDF внутри ZIP
получает собственную immutable OCR-производную версию.
Связанные PNG/JPEG внутри DOCX доступны отдельному OCR workflow с собственным
digest и locator, tenant-scoped API/persistence и без автоматического слияния с
нативным текстом.
AI-assisted визуальная разметка DOCX-media проходит отдельную типизированную
калибровку, но не может заменить human-confirmed production evidence. Локальная
страница `/ocr-review` проверяет exact DOCX/media digest и формирует отдельное
человеческое подтверждение без загрузки документов в API.
Если calibration не находит безопасного порога, routing отклоняет именно local
OCR, оставляет документ `UNKNOWN` и предлагает запросить нативный исходник либо
подготовить exact-payload approval для внешней vision-модели.
Гибридный discovery-поиск сохраняет immutable tenant-scoped версии названия,
имени файла, нативных блоков и отдельных vision-тегов. AI-тег остаётся `UNKNOWN`
до human confirmation и никогда не становится hard gate; API возвращает
provenance каждого совпадения без исходных байтов.
Server-rendered страница `/document-search` подключена к этому API: она различает
название, имя файла, нативный текст и vision-теги, показывает status/provenance и
не передаёт bearer token в браузер.
Reviewed-справочник `model-brand-catalog-v1` сохраняется immutable и tenant-scoped,
разрешает бренд только по exact effective-dated модели и официальному evidence;
похожая, конфликтующая или межтенантная запись остаётся `UNKNOWN`, а AI-модель не
повышается до `PASS`. Persisted entry обязан ссылаться на immutable PDF-артефакт;
при записи catalog сервер повторно вычисляет SHA-256 его exact bytes.
Управляемый review использует persisted роли bearer-ключей, immutable `DRAFT` и
единственное `APPROVED/REJECTED` решение; автор не может утвердить свой draft.
Полнота требований одного native-ТЗ проходит отдельный immutable review:
operator создаёт server-derived snapshot exact extraction/mapping, а роль
`COMPLETENESS_REVIEWER` принимает одно evidence-bound решение
`PASS | FAIL | UNKNOWN`. Страница `/completeness-review` работает только через
server-side bearer и после решения показывает снимок read-only.

Профиль, процедура, выбранное КП и три сценария связаны с оценкой точного снимка.
Недостающий фильтр, истёкшее КП, неподтверждённый расход или изменение данных
блокируют положительное решение. Экран внутреннего пилота показывает список и
карточки, provenance, gates, экономику и последнюю evaluation; ручной импорт и
пересчёт выполняются сервером. Контракты описаны в [документе S3](../operations/18-first-screen.md)
и [документе S4](../documents/19-document-pipeline.md), live-статус — в
[плане реализации](../15-implementation-plan.md).

- требования и provenance, товары, сертификаты, `PASS | FAIL | UNKNOWN`;
- профиль компании, география, финансовая политика и раздельные юридические /
  коммерческие запреты;
- процедура, статус подачи, точный deadline с часовым поясом и схема доставки;
- полная структура расходов и обязательные `base / realistic / conservative` сценарии;
- независимые риски, объяснимый рейтинг и deterministic recommendation gate;
- human-in-the-loop: подтверждение связано с SHA-256 точного исходящего payload;
- этапы исполнения контракта и предупреждения о сроках.
- каркас цифровых платформ: раздельные поиск поставщика и продажи «с полки»,
  проверки допуска канала с источниками и версией правил.
- документы: PDF/DOCX/XLSX и ZIP с безопасным разбором, provenance до
  страницы/абзаца/ячейки/участника архива, отдельными OCR-производными и
  гибридным discovery-поиском по нативному тексту/vision-тегам.

Это ещё не production-система: нет очередей, production IAM/TLS, пользовательских
сессий и коннекторов к ЕИС, ЭТП, почте, маркетплейсам, логистике и банкам.

Исходные пробелы описаны в [историческом аудите](legacy/13-partner-spec-audit.md).
S1 закрывает типизированный ручной ввод КП, полноту проверок/расходов и связь
оценки со снимком. До подключения первого источника требуется production-калибровка
OCR на разрешённой размеченной выборке реальных закупочных сканов. Актуальные
нормативные rulesets, денежный график и одноразовое исполнение approvals также
ещё требуют реализации.

## Запуск первого сценария

```powershell
uv sync --extra dev
uv run python -m procurement evaluate examples/paper_case.json --actor demo-operator --at 2026-09-08T12:00:00+03:00
```

Пример целиком синтетический. Команда выводит решение и сохраняет полный снимок
расчёта в `data/evaluations/`. `--at` фиксирует время для воспроизведения;
без него проверяется актуальность на текущий момент. Подробности и ограничения —
[инструкция локального расчёта](../operations/16-local-case-workflow.md).

История backend gate начиная с двадцать третьего среза S4: `490 passed, 29 skipped`
без настроенной БД и opt-in OCR (`28` PostgreSQL-тестов и `1` реальный OCR-тест
явно пропущены), 10 doctests, Ruff, strict mypy по 40 source-файлам, ESLint,
production build Next.js, `uv lock --check` и единственный Alembic head
`20260915_02`. UI-срез 24 отдельно прошёл ESLint, production build Next.js и
smoke-проверку страницы со всеми 9 клиентскими ресурсами. Срез 25 прошёл полный
gate: `498 passed, 29 skipped`, 10 doctests, Ruff, strict mypy по 41 source-файлу
и `uv lock --check`. Срез 26 прошёл полный gate: `500 passed, 30 skipped`
(`29` PostgreSQL без DB URL и `1` opt-in OCR), 10 doctests, Ruff, strict mypy по
41 source-файлу, ESLint, production build Next.js, `uv lock --check`; Alembic
имеет единственный head `20260916_01`, полная цепочка компилируется в offline SQL.
Срез 27 прошёл полный gate: `500 passed, 30 skipped`, 10 doctests, Ruff, strict
mypy по 41 source-файлу, ESLint, production build Next.js и `uv lock --check`;
Alembic head `20260916_02`, offline SQL компилируется.
Срез 28 прошёл полный gate: `501 passed, 30 skipped`, 10 doctests, Ruff, strict
mypy по 42 source-файлам, Next.js lint/build и `uv lock --check`; Alembic head
`20260916_03`, offline SQL компилируется.
Срез 29 и стабилизация прошли 526 unit/API/e2e тестов без integration, 30/30
обязательных PostgreSQL integration на отдельной PostgreSQL 16, 9 doctests,
Ruff, strict mypy по 43 source-файлам, Next.js lint/build и `uv lock --check`. Единственный
реальный PaddleOCR integration остаётся opt-in и не объявлен пройденным.
Срез 30 прошёл 535 unit/API/e2e тестов без integration и 32/32 обязательных
PostgreSQL integration на чистой PostgreSQL 16; Ruff, strict mypy по 44
source-файлам, 9 doctests, Next.js lint/build, lockfile и Alembic head
`20260916_04` также прошли.

## Локальный сервер S2

Скопируйте `.env.example` в `.env`, замените оба пароля, затем выполните:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Полный контракт и команды интеграционной проверки описаны в
[инструкции PostgreSQL и API](../operations/17-storage-api.md).

## Локальный пилот поиска закупок ЕИС

Для теста [экрана поиска закупок](../eis/search/25-eis-tender-discovery.md) без
PostgreSQL подготовьте браузер и соберите интерфейс:

```powershell
uv sync --extra dev --extra browser
uv run --no-sync playwright install chromium
Set-Location web
npm install
npm run build
Set-Location ..
uv run --no-sync python scripts/start-eis-pilot.py
```

Откройте <http://127.0.0.1:3000/tender-discovery>. Скрипт поднимает только
локальный API поиска и Next.js, создаёт токен без вывода в консоль и сохраняет
сессии в `data/eis-discovery.sqlite3`. Чтение ЕИС идёт по одному запросу с
интервалом 60 секунд; закрытие вкладки приостанавливает работу до следующего
открытия. Расчёт требует введённых поставщиком расходов и остаётся
предварительным, без решения об участии.

## Документация

| Документ | Назначение |
|---|---|
| [11-product-requirements.md](../product/11-product-requirements.md) | Нормализованное ТЗ партнёра и критерии приёмки |
| [12-requirements-traceability.md](../product/12-requirements-traceability.md) | Трассировка требований в компоненты и релизы |
| [13-partner-spec-audit.md](legacy/13-partner-spec-audit.md) | Исторический аудит готовности по состоянию на 2026-09-07 |
| [14-product-agents.md](../product/14-product-agents.md) | Реестр продуктовых агентов и границы их автономии |
| [15-implementation-plan.md](../15-implementation-plan.md) | Актуальный порядок работ и live-статус срезов |
| [20-stabilization-pilot.md](../operations/20-stabilization-pilot.md) | Протокол пилота на разрешённых документах и критерии `PASS/FAIL/UNKNOWN` |
| [16-local-case-workflow.md](../operations/16-local-case-workflow.md) | Запуск CLI, формат данных и журнал расчётов |
| [17-storage-api.md](../operations/17-storage-api.md) | PostgreSQL, RLS, bearer auth и FastAPI |
| [18-first-screen.md](../operations/18-first-screen.md) | Первый внутренний экран, server-side BFF и ограничения S3 |
| [19-document-pipeline.md](../documents/19-document-pipeline.md) | Документы S4: PDF/DOCX/XLSX/ZIP, OCR, provenance и calibration gate |
| [00-vision.md](../product/00-vision.md) | Видение, границы продукта и модель решений |
| [01-domain-model.md](../architecture/01-domain-model.md) | Объекты и инварианты домена |
| [02-architecture.md](../architecture/02-architecture.md) | Целевая архитектура SaaS + Local Agent |
| [03-compliance-engine.md](../architecture/03-compliance-engine.md) | Методика доказательного соответствия |
| [04-economics.md](../architecture/04-economics.md) | Полная экономика и три сценария |
| [05-roadmap.md](../product/05-roadmap.md) | Вертикальные срезы MVP → v1 → v2 |
| [06-legal-security.md](../architecture/06-legal-security.md) | Юридические правила, approvals и ИБ |
| [07-research-log.md](../research/07-research-log.md) | Проверенные и непроверенные внешние факты |
| [AGENTS.md](../../AGENTS.md) | Правила разработки, роли владельцев и порядок выполнения задач |

HTML-файлы `08–10` — презентационные снимки исходной концепции. До их регенерации
нормативными источниками являются Markdown-документы выше. `docs/history/legacy/ии.docx`
сохранён как исходный архив и не является актуальной спецификацией.

## Проверка

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src/procurement
PYTHONPATH=src uv run python -m pytest --doctest-modules src/procurement/domain src/procurement/documents/extraction.py
uv lock --check
cd web
npm run lint
npm run build
```

С заполненными `DATABASE_URL` и `DATABASE_ADMIN_URL` команда `pytest` также
выполняет 29 PostgreSQL integration-тестов; без них этот набор явно пропускается.
Реальный PP-OCRv5 regression запускается отдельно и требует opt-in окружения,
описанного в [контракте конвейера](../documents/19-document-pipeline.md).
### S48 local pilot AI transfer

Тестовый dispatch внешнего AI по умолчанию выключен. Он допускается только для
точно сохранённых request/approval и при явном `AI_TRANSFER_LOCAL_PILOT_ENABLED=1`.
Каждый явный запуск `dispatch-approved-ai-transfer` выполняет bounded coordinator
step: максимум один новый permanent claim и один HTTP-вызов. Повторный запуск
может продвинуть ровно следующий chunk либо выполнить no-network recovery;
внутреннего batch-loop команда не запускает.
Отдельная `materialize-ai-transfer` никогда не обращается к provider: она читает
immutable `chunk_count` и выбирает single- либо multi-chunk materializer,
возвращая `PENDING`, `MATERIALIZED` или `REJECTED` с безопасными IDs.
Pilot KEK задаётся через `AI_TRANSFER_RAW_ROOT_KEK_B64` и
`AI_TRANSFER_RAW_KEK_ID`; это не production KMS. Legacy `analyze-tz-ai` отключён.
Полный provider response хранится зашифрованным ровно 720 часов, после чего
удаляются ciphertext и wrapped DEK, а metadata/digests/audit сохраняются.

### S49–S60 materialization and bounded recovery

После единственного captured `SUCCESS` для single-chunk ответа сервер без нового
сетевого вызова создаёт raw-free `persisted-ai-requirement-run-v2` и append-only
materialization receipt (миграция `20260917_08`). В reviewer queue сохраняются
typed candidates, provenance и digests; raw `response_content` не раскрывается,
а полнота остаётся `UNKNOWN`. Полный multi-chunk batch создаёт raw-free snapshot
v3, а invalid evidence получает terminal `REJECTED`; повторная materialization идемпотентна. Recovery endpoint доступен
только owning operator, CLI recovery по умолчанию выключен. Reviewer queue
поддерживает v1/v2/v3 snapshots; encrypted raw хранится 30 дней.

Текущий combined gate: `780` no-DB тестов, `90` fresh PostgreSQL 16 тестов,
`10` doctest, mypy по 55 source-файлам, Ruff, Alembic head `20260917_12` и
`uv lock --check`. Production остаётся заблокирован до managed KMS/rotation и
backup/WAL/restore retention evidence; production dispatch/scheduler пока
намеренно отсутствуют.

### Локальный браузерный просмотр каталогов

Экспериментальный Playwright preview с отдельными профилями компаний, плавным
курсором, прокруткой и диагностикой блокировок:
[запуск и фактические ограничения](../suppliers/24-browser-catalog-pilot.md).
Запрос выбирает ServerMall HPE Gen12 либо категорию Яндекс Маркета: насосы,
ноутбуки, принтеры/МФУ. Фильтр требует все слова запроса в названии; для
Маркета разрешены до двух страниц по ссылке или проверенным данным продолжения
в HTML категории. Каждая
страница имеет provenance, сбой продолжения даёт PARTIAL. Живое HTTP-чтение
новых категорий подтверждено; браузерный переход принтеров на `/search`
отклонён политикой. Это ограниченный поиск, не вся выдача площадки.
На `/supplier-discovery?document_id=...` доступны режимы «Автоматически»,
«Только прямой доступ» и «Через браузер». По умолчанию браузер подключается
при ошибке прямого чтения каталога; режим входит в подтверждаемый план.
Для backend установите `uv sync --extra browser --inexact` и
`uv run --no-sync playwright install chromium`, затем перезапустите API.
Профили сервера задаются `BROWSER_PROFILE_ROOT` и доступны только серверу.

Публичные HTTP-источники используют сетевые настройки окружения
(`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, доверенные CA).
`SOURCE_HTTP_TRUST_ENV=false` явно отключает их. Проверка TLS остаётся включена,
redirects запрещены; адреса прокси с паролями не записывайте в репозиторий.
В S109 подтверждён живой проход Маркета по двум страницам: 24 карточки,
6 совпадений по «МФУ HP» (2026-09-22).

Поиск по ТЗ также подключён к публичным категориям «Гравитона»: серверы,
ноутбуки, принтеры/МФУ и ПК. Примеры товарных якорей:
`Наименование товара: Сервер Гравитон С2242ИУ`,
`Наименование товара: МФУ Гравитон ГМ2501`.
Этот источник использует HTTP во всех режимах, проверяет одну страницу
выбранной категории и возвращает названия/ссылки с SHA-256; соответствие остаётся UNKNOWN.
Также подключена одна публичная категория серверов DEPO:
`Наименование товара: Сервер DEPO Storm 1430B1R`. Результат DEPO независим
от «Гравитона» и реестра ЕАЭС; найденная модель не является КП.

Для насосов в режимах AUTO/BROWSER подключена одна публичная B2B-категория
Supl.biz через Chromium. Результат содержит название предложения и заявленного
площадкой продавца; общего поиска по Supl.biz, цены и подтверждения КП нет.
