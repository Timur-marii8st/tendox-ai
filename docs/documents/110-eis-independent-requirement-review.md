# S228 — независимая проверка выбранной таблицы ЕИС

Статус: COMPLETE для выпуска механизма; установлен на VPS 2026-10-06.
Production независимое решение PENDING. Предложение связано с точными digest S227 и S226.

## Контракт

Все строки выбранной сохранённой таблицы остаются в предложении, включая
контекст. Сервер читает исходные данные, назначает автора и время. Предложение
и решение immutable и tenant-scoped; создание записывается в audit.

Отдельная роль COMPLETENESS_REVIEWER подтверждает точный digest предложения,
нормативную роль документа, связь с позицией и конкретные строки. Автор
предложения не может сам его одобрить. Неподтверждённые сведения UNKNOWN.

Первое исполняемое правило — формат бумаги A/B0–10 с явным review кириллической
А/В. Другие характеристики сохраняются и остаются UNKNOWN: единицы количества
листов, плотность с допуском, порядок классов и полнота всего ТЗ не угадываются.

PASS/FAIL выводит существующий детерминированный engine с provenance обеих
сторон. Mandatory FAIL блокирует выбранный товар. Процент не вычисляется.
Даже все проверенные форматы PASS не дают полного технического допуска.
КП, экономика и участие UNKNOWN. Сетевых запросов к источникам и jobs нет.

## Проверки и выпуск

- 505 Python/API/PostgreSQL tests PASS, 82.51 s, zero skips;
- 116 Node wire/render tests PASS; TypeScript, ESLint и production build PASS;
- independent source/backend/web reviews: исправлены identity whitespace,
  RR write snapshot/lease, NULL-safe CHECK, busy translation, metadata/S226 FK
  и подмена wire requirement/provenance/engine explanation;
- source helpers0, schema20261006_08, health200, test databases0;
- API 126.6 MiB / 1 GiB, web 68.04 MiB / 768 MiB, OOM false;
- браузерная визуальная проверка NOT_PERFORMED; установленный Next Actions
  и compiled SSR проверены на реальном источнике.

## Как проверить в интерфейсе

После открытия таблицы рядом с товаром появляется «Подготовить проверку
требований». По умолчанию все строки manual UNKNOWN. Для поддержанного формата
можно предложить нормализацию и обязательность, затем сохранить предложение.
ID позволяет повторно открыть неизменный снимок. Проверяющий видит document,
position, все raw cells/instructions, товар и exact Proposal SHA256.

Настроенное подключение пилота имеет роль OPERATOR: оно создаёт предложение,
читает его и получает 403 при попытке одобрения. Независимое решение требует
другого actor с COMPLETENESS_REVIEWER через отдельное авторизованное подключение.
Мультипользовательский login этому срезу не добавлен. Никакой reviewer/token
ради live proof не создан. На production решение остаётся PENDING.

## Реальный production proof

Извещение 0107300009526000178 v2, исходный POD DOCX, таблица2, прежний S226 товар.
Пять строк: четыре характеристики и один контекст. Предлагается только формат;
остальные характеристики и контекст сохранены manual UNKNOWN.

Proposal ID `91ce8fd5-d8d6-46d4-9328-dee24ede9877`;
SHA `7bb95853cbf7ad1bd78f586e7fbf786c48a09cca74fc1e52cb722d7d11162900`.
Preview SHA `eab4d371d8b7037bff6fd26ca58f5de9a1b9e0d664ae4a2e9cf35a0f6493ccbb`.
Создание257 ms, replay232 ms, read222 ms; размер36402/36403 bytes.
Одно создание пишет proposal+audit (2writes). Replay/read writes0.
Next Actions replay288 ms/read246 ms, compiled SSR7032 bytes.
Всё source0/jobs0, без повторного чтения HTML/DOCX bytes.

Защиты: unauthorized401, oversize413, duplicate-key422, actor injection422,
omit row422, stale preview409, missing proposal404, OPERATOR review403.
Pending comparison404 — отсутствие решения, а не пустой успешный допуск.
После API и Next Actions: proposals1, decisions0, review audit1;
DOCX bytes5181668, analyses142, catalog bytes242753 — прежние значения.

## Evidence / pinned release

| Evidence | SHA256 |
|---|---|
| Tested src/tests/migrations manifest | 725570f91c855149f8f5ae65563e357be91f68ccc4827ccea1d785600c49b28f |
| Real PG log | 7f6f6d1adc8b6bd53bf26b0848d21eb5eeb588e719255d634c0543440182c20d |
| Production web build | 3f8c3c875bd4f36af16e88f7f4b50476581554db3f3cf4c97a600321647d0c0f |
| API live proof | b8e524b6f19e27226d4cfbd6ed5e7e30e2f89b0fbf64b13cfa25654b45aa48a0 |
| Installed Next Actions + SSR | 6d8de67ff2b2693ab4684cc5b96bf9b8ee21c24456a77fd01675d80bc2dc8a48 |
| Operations final | 765df2cec024046c70c13200bae9c9e9f10a63430cbf5f4879a849c03869f0f7 |
| Cleanup census | ece249727df426e96a4cac21194b52f5c6481a3592952290e8c1d38cb3b80c5e |

API image `sha256:56ba6c869c72b30b3d35d87a547c2fbbcaf01f54fc94d54d0668483187aa49aa`.
Worker image `sha256:9cfb06d20cc35470d6d1bbebf9b0258c0252df8e9d52001d997cdfba87a6de3a`.
Web image `sha256:b29b8dec4f4a8a740cee2786b18c1d3b4eb8c0243501b2ea3bb6abf6290e1cee`.

Реальные исходники и полные снимки остаются на VPS. На ноутбук source bytes не
переносились. Общее сравнение всех карточек, полнота ЕИС, полное ТЗ, действительное
полное КП, экономика и рекомендация участвовать этим срезом не подтверждаются.
