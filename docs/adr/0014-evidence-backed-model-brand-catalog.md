# ADR-0014: Evidence-backed exact model→brand catalog

Дата: 2026-09-16  
Статус: принято

## Контекст

Hybrid discovery может найти обозначение модели в нативном тексте или отдельном
vision-теге. Из самого кода нельзя выводить бренд: похожие линейки и OCR-ошибки
создают ложные связи, а AI-тег может быть неподтверждённым. В частности,
`GW-G140W/N1D3` найден только vision-моделью; проверенный официальный документ
содержит другую точную модель `GW-G140/N1A1` и не доказывает требуемую связь.

## Решение

Вводится immutable `model-brand-catalog-v1` с tenant, catalog ID, timezone-aware
creation time, reviewer и approval reference. Каждая запись содержит exact model,
canonical brand, полуоткрытый effective interval и evidence официального
производителя: HTTPS URL, название, SHA-256 точного документа, locator и время
получения.

Lookup нормализует только Unicode, регистр и пробелы. Значимая пунктуация модели
сохраняется; prefix, substring typo correction и fuzzy matching запрещены.
Отсутствующая, неактивная, межтенантная или конфликтующая связь возвращает
`UNKNOWN` без выбранного бренда.

Discovery по бренду создаёт `MODEL_BRAND_CATALOG` hit только когда exact model
присутствует в документе. Hit несёт обе части цепочки: provenance модели в
документе и записи официального каталога. Его status наследуется от evidence
модели: native/human-confirmed source может дать discovery `PASS`, AI suggestion
остаётся `UNKNOWN`. Это не compliance, hard gate, эквивалентность товара или
решение об участии.

Первый срез загружает reviewed manifest локально через CLI. Persistence/API и
управляемый review workflow каталога выносятся в следующий срез.

## Последствия

- ошибочно похожая модель не раскрывает бренд;
- конфликт официальных evidence видим как `UNKNOWN`, а не выбирается по порядку;
- повторный поиск воспроизводим на явный effective time;
- tenant isolation проверяется до использования записей;
- для production требуется хранение immutable версий каталога, audit и API;
- `GW-G140W/N1D3 → General Climate` не добавляется без точного источника.

## Альтернативы

- Выводить бренд из префикса модели — отклонено из-за ложных совпадений.
- Доверять vision-тегу с названием бренда — отклонено: AI suggestion остаётся
  lossy evidence.
- Использовать общий невременной словарь — отклонено: нет tenant/reviewer,
  effective date и воспроизводимого provenance.
