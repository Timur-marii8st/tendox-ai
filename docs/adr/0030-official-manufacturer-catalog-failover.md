# ADR-0030: официальный каталог производителя и supplier failover

- Статус: принято
- Дата: 2026-09-20

## Контекст

S79–S80 выполняли case-bound поиск только на одной странице ServerMall. Это
полезный supplier lead, но он не является источником производителя и не даёт
устойчивого пути к технической документации семейства. Одновременно текущая
таблица `sourcing_runs` хранит один exact snapshot, поэтому скрытое объединение
нескольких ответов в одну карточку разрушило бы provenance.

## Решение

Один sourcing run выбирает один фактически использованный exact source:

1. Отличительная пара model+generation маршрутизируется только в заранее
   разрешённую official family page. Первый allowlist содержит HPE DL360 Gen12
   QuickSpecs и Lenovo SR630 V3 Product Guide.
2. Адаптер делает один GET без redirect, ограничивает HTML 2 МиБ, требует
   `text/html`, проверяет visible product identity и считает SHA-256 exact bytes.
3. Успешная official page создаёт `MANUFACTURER_CATALOG` lead с явным
   manufacturer. Цена и exact BOM для такого lead запрещены доменной моделью.
4. При недоступности/изменении HPE official page допускается один существующий
   ServerMall HPE Gen12 fallback. Для Lenovo этот HPE supplier source не
   применяется. В run записывается только фактически использованный source;
   отсутствие релевантного успешного источника даёт `SOURCE_ERROR` без bytes и
   карточек.
5. Общий или неоднозначный query не направляется к случайному производителю.
   Добавление нового семейства требует отдельного allowlist entry, identity
   fixture и проверки официального URL.

## Последствия

Оператор получает рабочий официальный путь для двух рассмотренных семейств и
видит границу между manufacturer и supplier evidence. Existing append-only
storage и idempotency сохраняются без миграции. Срез не является общим web
search, не запускает конфигуратор, не подтверждает совместимость SKU,
происхождение, наличие или КП. Несколько одновременных source snapshots требуют
отдельной нормализованной storage-модели и не входят в это решение.
