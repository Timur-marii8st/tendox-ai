# ADR 0089 — точный source0 просмотр DOCX и ограниченный prepare процесс

Дата: 2026-10-06. Статус: принят; выпуск docs101.

## Контекст

S218 сохраняет отдельный immutable review анализ с lossless страницами, но не
имеет API/UI. Вызов parser внутри API thread теряет wall/CPU/memory isolation.

## Решение

Только явный OPERATOR prepare, отдельный POSIX child с одним slot/CPU30s/
AS512MiB/wall45s. Tenant и actor задаёт API principal; DB URL не выходит в wire
или logs. Cached page read разрешён authenticated reader с теми же exact source gates.
Два bounded JSON POST с no-store/strict keys/4096bytes. UI streaming256KiB,
Unicode codepoint span validation, paired cursor и lossless page navigation.
Полный immutable request key отделяет состояния документов. Raw content не HTML.
Native source coverage/fullTSpec/role/requirements остаются UNKNOWN.

## Последствия и альтернативы

Срез делает проверяемый текст доступным без повторного download. Лимиты видны,
large/unprepared/stale/held/foreign данные не становятся разрешением. Это не полный
DOCX parser и не engine технического допуска. Thread-only prepare отклонён из-за
отсутствия kill deadline; массовый анализ всех документов требует отдельной очереди.
