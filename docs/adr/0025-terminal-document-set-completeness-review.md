# ADR-0025: Терминальная проверка полноты точного комплекта документов

- Статус: принято
- Дата: 2026-09-17

## Контекст

`document-set-evidence-manifest-v1` из ADR-0024 фиксирует точный состав и порядок
нескольких документов, но намеренно остаётся `UNKNOWN`. Отдельные решения `PASS`
по каждому документу не доказывают, что заявленный комплект полон: обязательный
файл может отсутствовать, а условия из разных файлов могут противоречить друг
другу.

Нужен отдельный независимый review, связанный одновременно с immutable manifest,
каждым terminal single-document decision и конкретным evidence внутри выбранных
snapshots. Он не должен автоматически сливать несколько `FactMappingResult` или
выбирать «последний успешный» review.

## Решение

Вводится `document-set-completeness-decision-v1`. Reviewer с ролью
`COMPLETENESS_REVIEWER` получает серверно восстановленный exact evidence package:

- исходный manifest и его digest;
- ordered constituent review snapshots;
- terminal decision и вычисленный digest каждого constituent decision;
- автоматические server findings по проверяемым междокументным конфликтам.

Reviewer обязан дать attestation для каждого member, оценить полноту заявленного
inventory и совместную проверку документов. Findings типизированы и ссылаются на
существующий source block либо на конкретное поле mapping. Клиент может создавать
только findings с origin `REVIEWER`; server findings вычисляются заново и не могут
быть удалены или подменены payload.

Статус выводится fail-closed:

- `FAIL` — только при constituent `FAIL` или положительно подтверждённом
  существенном пропуске/отсутствующем документе;
- `PASS` — только если все constituent decisions имеют `PASS`, каждый member
  отмечен `REVIEWED_IN_SCOPE`, inventory подтверждён, cross-document assessment
  не содержит открытых вопросов и findings отсутствуют;
- во всех остальных случаях — `UNKNOWN`.

Разные непустые сроки поставки автоматически создают server finding
`UNRESOLVED_CONFLICT` и не позволяют получить `PASS`. Reviewer не может быть
создателем manifest или любого constituent snapshot. Он может совпадать с автором
single-document terminal decision: независимость этого предыдущего шага уже
проверяется его собственным контрактом.

Перед каждым решением и чтением repository повторно проверяет manifest, source
bytes/extraction, exact constituent decisions, их digests и server findings.
Aggregate logical JSON evidence ограничен 40 МиБ до полной materialization.

Миграция `20260917_03` добавляет две append-only tenant-scoped таблицы с
RLS/FORCE RLS: terminal decision и ordered member attestations. Exact manifest FK,
constituent decision FK и deferred constraint trigger проверяют число members,
scope, порядок и JSON/row binding. Decision, attestations, audit event и
actor-bound idempotency receipt записываются одной транзакцией.

HTTP-граница предоставляет reviewer-only evidence GET, terminal POST и decision
GET. Strict JSON запроса ограничен 256 КиБ, duplicate keys и non-finite values
отклоняются, ответы помечены `Cache-Control: no-store`.

## Последствия

Положительное следствие: система получает воспроизводимое терминальное решение о
полноте конкретно заявленного комплекта, не теряя provenance и не позволяя
рейтингу либо отдельным `PASS` скрыть обязательный `FAIL` или неопределённость.

Ограничения: решение действительно только для exact manifest и его scope. Оно не
создаёт объединённый executable mapping, не выбирает case/ruleset, не разрешает
`PARTICIPATE` и не запускает sourcing. Любое изменение состава требует нового
manifest и нового review.

## Отклонённые варианты

- Считать комплект полным, если все constituent reviews имеют `PASS`: не
  обнаруживает отсутствующий документ и междокументный конфликт.
- Разрешить reviewer самостоятельно передавать server findings или decision
  digests: переносит trust boundary на недоверенный payload.
- Слить mappings и выбрать первое/последнее значение одиночного поля: молча
  теряет конфликтующее evidence.
- Разрешить `FAIL` для любого сомнения: смешивает доказанный отрицательный факт с
  отсутствием данных; сомнение обязано оставаться `UNKNOWN`.
- Автоматически использовать terminal decision в case: скрывает выбор версии и
  нарушает exact-evidence boundary.
