# ADR 0119: лекарственные позиции как отдельная проекция источника

Дата: 2026-10-26. Статус: ACCEPTED / DEPLOYED в ограниченном scope; evidence [V50](../eis/ingestion/138-eis-drug-positions.md).

## Контекст

В шести сохранённых EF-извещениях V49 обнаружены 26
`drugPurchaseObjectInfo`, тогда как canonical `lot_items` пусты. Изменение
canonical parser нарушило бы сравнение snapshot при повторной проекции variants.
Источник: проверенные retained XML/SHA в
`tmp/eis-completeness-20261026-v49/drug-diagnosis/source/`.

## Решение

Использовать существующую append-only tenant-scoped таблицу position projections,
parser `eis-position-v4-drug-source-r1`. Старые parser versions читаются.
Canonical snapshot, decisions и история не переписываются; миграций нет.
Шесть старых записей обрабатываются явным существующим source0 projector.
Оба canonical writer создают derivation для новых записей в своей транзакции;
variant writer делает это после authenticated admission audit. Replay не backfill.
Доказанный same/newer HOLD оставляет derivation отсутствующей, explicit projector
отказывает. Ошибки binding/digest/storage не подавляются.

Извлекаются только точные QName-пути, явное имя, сумма `total`, исходная единица,
цена и валюта. Единицы всех альтернатив должны совпадать буквально, включая код.
`quantityUndefined` сохраняет количество UNKNOWN. Пересчёта дозировок, упаковок,
фармацевтической эквивалентности и выбора первого кода альтернативы нет.
Каждый факт содержит XML SHA и точный namespace-qualified локатор.
Превью ограничено 25 позициями, обход — 1000 объектами и 64 альтернативами;
XML — 32 MiB. Полнота ТЗ и review всегда UNKNOWN.

Обычный поиск и сортировка по цене добавляют сохранённую typed `position_set`
только выбранной странице после comparison cache. Чтение позиций не разбирает
ZIP и не пишет данные; существующая navigation сортировки по цене сохраняется.
Перед чтением JSON проверяется размер в PostgreSQL: 512 KiB на запись,
2 MiB на страницу, до100 результатов. Пропущенная derivation остаётся UNKNOWN.
Страница использует до трёх пакетных запросов: scoped HOLD, размеры и приоритет
версий, затем только JSON, вошедший в бюджет. SQL на каждый результат запрещён.
UI показывает source evidence отдельно от canonical inputs региональных аналогов.

## Последствия

Новые факты не создают КП, допуск, прибыль или PARTICIPATE. Поиск по имени
лекарства, отсутствующему в canonical title, требует отдельного согласованного
изменения lexical и второго этапа matching. Весь ЕИС и лекарственное ТЗ не приняты.
Старый API не читает v4: возврат на него снимает acceptance отображения этих
позиций; evidence не удаляется. Барьер совместимости V48 сохраняется.

## Альтернативы

Canonical rewrite отклонён из-за immutable replay. Парсинг ZIP на GET отклонён
из-за стоимости и скрытых изменений поведения. Новая таблица не нужна:
существующая projection уже имеет tenant/RLS, digest, версии и audit.
