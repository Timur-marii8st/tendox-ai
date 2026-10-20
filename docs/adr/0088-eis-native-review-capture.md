# ADR 0088 — отдельный анализ исходного DOCX для проверки

Дата: 2026-10-06. Статус: принят; результат выпуска — docs100.

Старый eis-native-v3-doc и его223receipts сохраняют прежний контракт. Они
не доказывают число блоков до retention и полноту извлечения. Новое явное
source0 действие создаёт eis-native-review-v1 только для выбранного44DOCX.
Exact notice/UID/expectedSHA/RECEIVED, sourceholds и tenant gates обязательны.

Используется существующий immutable tenant/SHA/filename/revision cache,
допускаемый additive migration. Прежние записи не переписываются. Native
status/reasons/units/chars до retention сохраняются отдельно от retained.
Сохранённый текст читается страницами с явным truncation. Complete native text
не означает полный комплект ТЗ, правильную роль документа, approvedrequirements
или технический допуск. Доставка остаётся raw review lead. Никакой автоматической
подачи, поиска поставщиков или внешней отправки это действие не разрешает.

Начальный server package ограничен DOCX. API/UI, другие форматы и ZIP parent/
member manifest выполняются отдельными срезами с проверкой этого контракта.
