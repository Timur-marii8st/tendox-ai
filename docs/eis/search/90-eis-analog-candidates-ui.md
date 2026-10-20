# S207 — исторические кандидаты в аналоги в интерфейсе

Статус: установлен и проверен 2026-10-05. Владелец root, независимый read-only
review Astra. Контракт [S205](88-eis-historical-analog-selection.md), установленный
API [S206](89-eis-analog-query-performance.md); без изменений backend и схемы.

## Использование и смысл результата

В `/tender-discovery`, в карточке результатов поиска по сохранённым XML 44-ФЗ,
появился блок «Подобрать исторические кандидаты в аналоги». Выберите исходную
позицию (первые 25), поисковые слова и период 1–730 дней. Кнопка выполняет
read-only запрос к сохранённым данным; сама карточка ничего не запускает.
Период отсчитывается от публикации выбранной версии, а не от сегодняшней даты.

Отчёт показывает до 20 карточек того же типа процедуры, отобранных по словам,
с истёкшим сроком подачи. Это не доказательство завершённого контракта.
Порядок — дата публикации, без рейтинга доходности. Строки с FAIL исключены;
остальные требуют проверки и сохраняют сопоставимость UNKNOWN. Полный КТРУ
или ОКПД2 с нормализованным названием и диапазон количества являются
критериями отбора. Техническая эквивалентность и регион поставки UNKNOWN.
Данные о поставщиках, связи с лотом, прогнозе конкуренции, прибыли и участии
также UNKNOWN; процент соответствия или вероятность победы не выводятся.

Критерии раскрываются с причинами, исходными значениями, XML SHA-256 и
локаторами обеих карточек. Количества остаются строками Decimal, даты — с
часовым поясом. Ссылка в ЕИС открывает карточку по номеру и может показать
другую версию; источником сравнения остаётся сохранённый XML с указанным SHA.
Обрезанная выборка, непроверенные позиции, неизвестные полнота/охват/свежесть
видны явно. Пустая выборка не означает отсутствие аналогов или конкурентов.

## Транспорт и границы

Next Server Action передаёт точные номер/версию/SHA, source_index, query и
lookback_days. Tenant и bearer определяет server-only adapter; клиент не может
передать tenant. Ответ проверяется на точную привязку всех параметров, лимиты,
счётчики, FAIL/UNKNOWN и provenance. Изменение ввода, другая карточка или новый
запрос инвалидируют предыдущий ответ и ошибку. Ошибки API и сетевого транспорта
выводятся локально, с возможностью повторить запрос.

Новые source calls/jobs/audit/projection writes отсутствуют. API/worker/cron,
схема 20261005_01, dependencies/lockfile и лимиты источника прежние.
Owned files и acceptance зафиксированы в docs15. Изменения только web + docs.

## Проверки и установленный результат

9 новых Node tests + 8 существующих protocol tests PASS. Проверены точная
привязка запроса, ложный FAIL в виде массива, неверные счётчики/provenance,
missing positions/пустая/обрезанная выборка, смена ввода/запроса/отмена ответа,
сетевые ошибки, точность Decimal, escaping XML-текста, тип процедуры в ссылке и
unknown inherited keys. TypeScript, scoped ESLint и production build PASS на
VPS в network-none контейнере 2CPU/2GiB. Astra независимый review закрыт;
замечания исправлены и защищены регрессиями.

Build log `/home/syurai/vibe-seller-state/s207-web-build.log`, SHA256
`6d0306e24faec7b45e16b4560bd15849477173d9ac6727d134ccba7b0aba5693`.
Deploy19:56:19UTC: atomic13files/host90hashes/web14hashes PASS;
routeHTTP200 и новая/старая Server Actions зарегистрированы.
В качестве базы использован pinned S204 web с прежними зависимостями.

Image pins:

- Web `sha256:fe9b6a171709f6c72f9142cf63c00bf6e16aa20c77c61f65a1ddc01b6d6be806`.
- API прежний S206 `sha256:b4dc7954e64648ba58e551a22a2cd63fd9623bf3008bcb9daa6466bbbe329691`.
- Worker прежний S206 `sha256:a9fccb839a20f8ae54c7ecdae7967539355e9dcc4f8b8bb2e92c299980bb74ba`.

Rollback backup
`/home/syurai/vibe-seller-state/backups/s207-before-20261005T195616Z-web.tar.gz`,
SHA256 `de7f4990b89d9ef4338f74887b016717e691fe8ac0460f2d21039f31f449c0b0`.
Для отката web используется прежний pinned S204 image; миграций нет.

Installed acceptance19:57:35UTC: настоящий HTTP POST Next Server Action, который
вызывает кнопка, на трёх exact paper refs, каждый first/repeat. Loopback timings
2269/2067,2048/2027,2040/1946ms. Каждый отчёт20notices/82positions/truncated=true;
excluded/review82/0,81/1,81/1. Изменённые source_index2/lookback30:1796ms,
точная привязка и20notices/82positions. Production-compiled report component
отрендерен с реальными ответами; проверены источники/Decimal/UNKNOWN/FAIL.
Восемь отрицательных запросов: tenant в payload/ref, version/SHA, позиция26,
отсутствующая позиция5, дробный период, пустой запрос — error без результата.
Регрессия прежнего чтения протоколов19:57:36UTC:3refs/9documents и4negative
checks PASS, HTTP128/98/82ms. Это замеры ограниченных сохранённых выборок,
не поиск всей ЕИС, не время браузерного рендера и не SLA.

Private proof0600, только VPS:

- `/home/syurai/vibe-seller-state/s207-web-action-proof.json`, 6711559bytes,
  SHA256 `1f128c828f8f619f4c20cdece5c24a7baba4d9bcc9103237f551fe8ec43a1a5a`.
- `/home/syurai/vibe-seller-state/s207-protocol-regression-proof.json`, 282569bytes,
  SHA256 `5b9ba7dd3937f8e33a1dac43722bc192942c8f4284dc73d706817e603de04eb6`.
- `/var/lib/eis-browser/research/rejected/s207-final-operations-proof.json`,
  SHA256 `f930a82e0191652a680a107de325b1d8bd81435ec6dd5894206831cd4f33d151`.

Ops19:57:37UTC: health200, head20261005_01/testDB0, DB5039660055bytes,
free257407389696bytes; priority/223markersfalse. API/web running/OOMfalse,
API1GiB/web768MiB/worker2CPU2GiB. Source0/DBwrites0/read-only.
Cron SHA256 `012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`
прежний. Архивы и отчёты на ноутбук не скачивались.

Визуальная проверка клика в браузере не выполнена. Указанная в S204 automatic
approval rejection для Start-Process SSH loopback tunnel не обходилась;
новые порты или туннель не открывались. HTTP Action и SSR — отдельные проверки.

Documentation seal19:59:04UTC: atomic4docs/host90/API18/worker18/web14hashes PASS;
image/cron pins/resources PASS, API/web running/OOMfalse. Seal backup SHA256
`1b750626e0b96b4d39654303e18eaef416478dcfda78e708e6c064594db0d784`.

Следующий срез S208: измеренная оптимизация SQL prefilter; контракт исторических
кандидатов и неизвестные поля сохраняются.
