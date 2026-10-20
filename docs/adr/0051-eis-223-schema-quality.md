# ADR-0051 — качество полного223XML отдельно от metadata projection

Статус: принято. Дата:2026-10-02. Владелец: основной агент.

## Контекст

S154 получил новую котировку: typedmetadata безопасно разбирается, но полный
официальный XML не соответствует maxLength в национальном режиме. Полная
валидация всех полей XML и точное извлечение ограниченных исходных значений —
разные проверки. Ни одна из них не доказывает допуск поставщика или прибыль.
S152generic архив не допущен: семейство/reader ещё не реализованы.

## Решение

Сохранять immutable raw и существующую строго типизированную projection
только уже допущенныхAESMBO/ZKESMBO. Не исправлять sourceXML, не ослаблятьXSD,
не удалять историю. Отдельная immutable FORCE RLS проекция хранит полную XSD
проверку exactномер/версия/XMLSHA, schema release/root/tree/package SHA,
validator version и bounded diagnostics. SQL compositeFK связывает exactXML.
Проверки выполняются offline operator по pinned complete local official trees,
без использования внешнего schemaLocation и без HTTP. Повтор не создаёт audit.

Выдача показывает source_schema_status: UNKNOWN без полного evidence обеих
проверенных releases; FAIL при любом сохранённом schemaFAIL; PASS только при
PASS обеих releases. Статус относится исключительно к исходному XML. Match,
цена лота и schemaPASS не меняют supplier gates, eligibility/economicsUNKNOWN.
Ошибка видна вместе с диагностикой и exactXML/schema hashes. SourceSYNCED
означает полный downloaded listed archive set, а не XSDPASS/полнотуЕИС.
Новые версии не наследуют quality status старых bytes; отсутствие observation
новой версии остаётся UNKNOWN. Evidence полного XML не превращает слова
в утверждённое ТЗ. Deep document/requirement workflow должен проверять quality
и сохранять критические неизвестные до детерминированного domain review.

## Последствия

Можно искать исходный спрос и видеть пробелы источника без ложного допуска.
Metadata reader по-прежнему fail closed дляidentity/namespace/provenance,
небезопасного XML/ZIP и version conflicts. GenericpurchaseNotice не допущен:
этот ADR не добавляет его reader и не изменяет карантин S152.
Operator audit ограничен200версий/32MiB compressed за запуск; расписание
глобальной XSD валидации требует отдельного boundedqueue slice. Новый API GET
читает saved evidence, не вызываетvalidator/download и не меняет audit.

## Альтернативы

Отбрасывать целиком безопасныйsourcewindow за ошибку в дополнительном поле:
теряет полезный наблюдаемый спрос и скрывает ошибку. Переписать XML/смягчитьXSD:
ломает provenance. Выдать reader success за full-XSDPASS: создаёт ложный факт.
