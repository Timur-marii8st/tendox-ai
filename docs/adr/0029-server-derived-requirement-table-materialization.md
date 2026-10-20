# ADR-0029: server-derived materialization таблицы требований

- Статус: принято
- Дата: 2026-09-20

## Контекст

S81 хранит полный reviewed requirement set и его точные решения, но низкоуровневый
proposal API принимает строки от клиента. Для приложения закупки с 87 строками
это оставляет риск пропуска строки, подмены исходного текста или неявного
принятия числового кандидата. Persisted документ уже содержит immutable bytes,
SHA-256 и native DOCX extraction с provenance; именно он должен быть источником
materialization.

## Решение

Materialization состоит из server-derived preview и commit:

1. Preview принимает только document ID, exact SHA-256 и ожидаемое число строк.
   Сервер допускает `TENDER_REQUIREMENTS` с extraction `PASS` и выбирает ровно
   одну native DOCX-таблицу, чьи строки непрерывно покрывают `1..N` и имеют
   ячейки name/value. Неоднозначный или неполный выбор завершается ошибкой.
2. Сервер возвращает все исходные строки, provenance, необязательные числовые
   подсказки и canonical digest preview. Подсказка остаётся неисполняемой.
3. Commit повторно строит preview из persisted document и сверяет digest.
   Оператор может повысить только показанную числовую подсказку, явно задав
   canonical property, unit, mandatory и review note. Operator/value числа
   берутся из server-derived кандидата.
4. Каждая невыбранная строка сохраняется как `MANUAL_REVIEW_REQUIRED`. Proposal
   проходит прежний независимый review S81; лишь exact terminal `PASS` может
   быть привязан к версии кейса.

## Последствия

Browser больше не является источником raw requirement rows для основного
операторского пути. Полное row-level покрытие проверяется до записи, stale
preview не принимается, а отсутствие выбора не превращается в допуск. Workflow
не решает семантическую нормализацию 59 строк без числовой подсказки и не создаёт
reviewer `PASS`, case binding, КП или решение об участии.

Низкоуровневый S81 endpoint сохраняется для доверенных интеграций и тестовых
fixtures, но операторский UI использует только server-derived endpoints.
