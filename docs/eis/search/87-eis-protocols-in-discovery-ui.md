# S204 — исторические протоколы в карточке закупки

Owner root. Реализовано и установлено на VPS 2026-10-05.

## Интерфейс

В сохранённой карточке 44-ФЗ раздел «Исторические протоколы» содержит кнопку
«Показать сохранённые протоколы». Загрузка начинается только по нажатию,
через existing server-side BFF и S203 API. Запрос не обращается к ЕИС, не создаёт
заданий и не изменяет индекс. Bearer остаётся на сервере; tenant берётся из
API principal, а не из клиентского payload. Это существующий single-tenant
loopback pilot; новая схема пользовательской авторизации не вводится.

Вход — exact purchase number/version/XML SHA. BFF проверяет формат, запрещает
дополнительный company_id и сверяет ответ с выбранным ref. Компонент remount
при изменении любого поля ref исключает перенос результата на другую версию.
Запрос fetch no-store/timeout30s. Ошибка API, несовпадение версии и browser→Next
transport rejection выводятся локально; старый результат очищается при повторе.

Каждый протокол показан отдельно: тип, источник XML SHA/member/namespace,
номера протокола/основания/лота, число строк и число заявок с однозначными ID.
Раскрываемая таблица показывает исходные ID, допуск, ранг, сумму, признак платы
за право заключения и исходный код результата. У каждого поля свой locator.
React экранирует исходный текст; внешнее содержимое не выполняется.

Сумма приходит строкой из Decimal и не конвертируется в Number, не округляется
и не получает выдуманный символ рубля. Валюта и налоговая основа UNKNOWN.
Неизвестные поля и причины остаются видимыми. FAIL/expired не исчезают при
чтении исторических данных. PASS извлечённого поля не означает допуск продукта.

Явно указаны ограничения: связь документов только по номеру закупки;
применимость к выбранной версии, текущий этап, личности поставщиков,
свежесть, полнота, участие и прибыль UNKNOWN. Строки/заявки не становятся
числом конкурентов; rank1/CC/RC не доказывают подписанный контракт.
Протоколы распределения могут повторять ID; документы не суммируются.
Пустой ответ означает отсутствие поддержанных сохранённых протоколов,
а не нулевую конкуренцию. Кнопка работает и для исторических карточек
в режиме поиска с истёкшими сроками.

## Acceptance

`cd web && npm run test:protocols`: восемь синтетических регрессий PASS.
Проверены exact ref/лишний tenant, несовпадение ответа, повторные ID,
точная большая и отрицательная Decimal-строка, UNKNOWN currency/tax,
FAIL/expired, пустые списки, XSS escaping/provenance, transport rejection.
`npx tsc --noEmit` и scoped ESLint PASS. Read-only Astra review:
transport rejection исправлен с регрессионной проверкой.

VPS production build17:07:52UTC: те же восемь тестов, TypeScript,
scoped ESLint и Next build PASS. Builder networknone/2CPU/2GiB, exit0/noOOM;
runtime ENTRYPOINT/CMD восстановлены к исходному web контракту до deployment.
Build log `/home/syurai/vibe-seller-state/s204-web-build.log`,
SHA `2a31cbde92c5af1f47d6be649f7f5864f35db89339d0ba208a4201acee44a827`;
runtime config log SHA `06e3d8dd9b556e8ecc331fabf4560c9b0c2a066b47a01e5f1a0d42712fbefbc4`.
Pinned source baseline web host/image PASS; остальные web исходники взяты
из прежнего pinned image. Dependencies и lockfile прежние.

Deployment17:10:19UTC: atomic13files/host75hashes PASS, web9 source hashes PASS,
server action registered, route HTTP200. Новый web image
`sha256:861e3e8f348d1d74f0d20d1f07cc3cda83798465dd13af8a8efe67e458ddf359`.
Backup `/home/syurai/vibe-seller-state/backups/s204-before-20261005T171016Z-web.tar.gz`;
SHA `34e3e767bd0efbbfe659a33eab55c57c41275f42e7adf4d6041fe08e41cac0ff`.
API и worker остаются pinned S203, схема20261005_01 без миграции.

Installed web acceptance17:12:42UTC: настоящий HTTP POST Next Server Action,
который вызывает кнопка, для трёх exact refs →9 protocol documents.
Production-compiled report component отрендерен с этими реальными ответами;
проверены суммы-строки/locators/FAIL/UNKNOWN и38 repeated rows/countUNKNOWN.
Чтение через web loopback132/102/88ms: один прогон сохранённых refs,
не время браузерного рендера, не поиск всей ЕИС и не SLA.
Четыре отрицательных запроса (номер, caller tenant, version, SHA) дали
локальный error без результата. Route HTTP200; новых source calls/DBwrites0.
Private proof0600 `/home/syurai/vibe-seller-state/s204-web-action-proof.json`,
282570bytes; SHA `84e4826a35c5573a9c4c997bd9883183f9e288dbc9f479fe541e9502cc3156c9`.

Визуальная проверка клика в браузере не выполнена: automatic approval review
отклонил Start-Process SSH loopback tunnel; конкретная причина не сообщена.
Сетевые ограничения не менялись. HTTP action и production render проверены
на VPS; это не утверждение браузерной визуальной проверки.

Ops17:13:56UTC: health200, head20261005_01/testDB0, API/web running/noOOM,
API1GiB/web768MiB; DB4809423895/free257766719488bytes.
Priority marker=true — наблюдение обычной параллельной работы, не marker S204;
223marker=false. Cron SHA
`012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f` прежний.
Proof `/var/lib/eis-browser/research/rejected/s204-operations-proof.json`;
SHA `8870618c43b0303ecb23f8fa8fd2014a445d5186058ffe51ab8250d943b933c2`.
Backend/БД/worker/source budgets не менялись.
Documentation/hash/image seal17:16:10UTC: atomic4docs/host75/API16/worker16/web9
hashes PASS; pinned images/cron/resources PASS, API/web running/noOOM.
Backup `/home/syurai/vibe-seller-state/backups/s204-before-20261005T171610Z-seal.tar.gz`;
SHA `266913210f69899825500e66b5dde65da7f262c3236ef9275858adc56e8aeb3a`.

Следующий этап: определить и реализовать критерии сопоставимости исторических
аналогов (предмет/лот/регион/период/объём) и bounded проекцию/кеш по evidence.
Прогноз вероятности и доходности требует отдельных данных и acceptance.
