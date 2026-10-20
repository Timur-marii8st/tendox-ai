# ADR-0031: exact artifacts нескольких sourcing sources

- Статус: принято
- Дата: 2026-09-20

## Контекст

S83 выбирал один фактически использованный источник. Это не позволяет в одном
run сохранить official manufacturer evidence и supplier discovery, а fallback
скрывает факт ошибки первого источника после успеха второго. Один binary blob в
`sourcing_runs` также не может доказать digest каждого ответа отдельно.

## Решение

1. Sourcing run содержит ordered metadata `sources` (до 10). Каждый source имеет
   kind, URL, media type, status, timezone-aware observed-at и либо exact
   digest/size, либо error code.
2. Новый append-only `sourcing_run_sources` хранит exact bytes каждого successful
   source. PostgreSQL самостоятельно сверяет SHA-256 и размер; error rows не
   могут содержать bytes. Composite tenant FK, RLS/FORCE RLS и immutable trigger
   применяются ко всем rows. Deferred constraint trigger сверяет полный ordered
   child set с metadata manifest при commit.
3. Parent blob становится canonical manifest metadata. Run имеет `COMPLETED`,
   когда успешен хотя бы один child, и `SOURCE_ERROR`, когда неуспешны все.
   Ошибочные children сохраняются и показываются даже при partial success.
4. Lead ссылается своим digest только на successful child. Ни manifest, ни
   несколько official documents не создают exact BOM или technical `PASS`.
5. Dell PowerEdge R660 добавляется как official PDF source с allowlisted direct
   URL, MIME/size/page limits и product identity validation. HPE может запускать
   official+supplier attempts; Lenovo/Dell не используют нерелевантный HPE
   supplier source.

## Последствия

Audit может восстановить, какой ответ дал каждую карточку и какие источники были
недоступны. Старые sourcing runs остаются валидными с пустым `sources`.
Стоимость — новая child table и предел 20 МиБ на один официальный PDF. Срез не
решает общий catalog crawling, SKU configurator, коммерческое предложение,
реестровый статус или полноту технического соответствия.
