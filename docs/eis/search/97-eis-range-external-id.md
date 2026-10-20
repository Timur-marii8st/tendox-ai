# S214 — диапазоны с externalSid

Статус: DEPLOYED / VERIFIED selected characteristic slice, 2026-10-06.

## Контракт

В сохранённом XML выбранного извещения 0348200080326000021 v1 числовое значение
содержит optional `externalSid`. Сохранённая схема IntegrationTypes.xsd
(s203, объявление около строки 16504) описывает его как `base:externalIdType`
с `minOccurs="0"`. Обязательный формат UUID из этого не выводится.
Поле распознаётся как служебный непустой скаляр; оно не определяет равенство
диапазонов. Дубли, атрибуты, вложенность, смешанный текст и неизвестные формы
не дают признака полноты источника.

Новая неизменяемая проекция `eis-position-v3-range-evidence-r1` читается первой,
затем исходная v3, затем v2. Прежняя v3 сохраняет свои признаки, v2 всегда
неполна для диапазонов. Повреждение предпочтительной версии блокирует чтение,
без перехода к нижней версии. Создание исторической v3 новым парсером запрещено.
Размер retained archive проверяется SQL-метаданными до чтения его байтов.

## Проверка и ограничение

Предусмотрено восстановление только одного exact ref из сохранённого архива,
с контрольными суммами, source holds, одной проекцией и одним audit event.
Canonical notice и прежние проекции неизменны; replay не пишет данные.
Проверки API и интерфейса читают сохранённые данные без запросов в ЕИС.
Полная техническая сопоставимость, прибыль, участие и полный охват UNKNOWN.
## Evidence

95 локальных pure/API tests, Ruff и независимый review PASS.
346 isolated PostgreSQL/unit/API tests PASS, 38.57 s, zero skips; disposable DB
удалена. PG log SHA256 `1cb94489a2930c63401ead7629212c461fb4f0c5798f317202f722a740c705f9`.
Deploy 05:23:36 UTC: atomic10, host119/API23/worker23 hashes PASS, web неизменён.
API image `sha256:17100eaa9dca4d68a6b392d10139ec279051cead43f0182ab1055d48f889974f`;
worker `sha256:9330889cc9c3589905079abd8369bac48b7e5e9cccb9b33569bd1bec0cfbc208`.
Rollback backup `/home/syurai/vibe-seller-state/backups/s214-before-20261006T052330Z-code.tar.gz`,
SHA256 `8a60b611c49a7d335816f10fe8e0b333b34367fc89789e2f1db0db32d90c8c17`.

Recovery 05:23:53 UTC: одна r1 projection/один audit, 599 ms; canonical row и
исторические projection payload digests unchanged, replay false/counts unchanged.
Proof `/var/lib/eis-browser/research/rejected/s214-range-repair-proof.json`,
SHA256 `36c17a150920d983d00cb43298ab79efc3c9c1bfb52cf5695f309defa9bf3b20`.
Installed API/direct: шесть fixed-clock identities PASS, HTTP81–243/direct83–177 ms;
шесть authorization/ref/position negatives PASS. Pair3: one recorded SAME +2UNKNOWN,
pair2 one SAME +3UNKNOWN, pair1 12UNKNOWN. API proof
`/var/lib/eis-browser/research/rejected/s214-verified-characteristic-live-proof.json`,
SHA256 `151f47431a9ebe39124acefa61b4562b80827a2c50f77757d29ced5af37dd62e`.
Next Action+compiled SSR шесть selected-pair reads87–183 ms и пять negatives PASS.
Browser visual check NOT_PERFORMED. State proof `s214-web-regression-proof.json`,
SHA256 `1a3bc6f5173cbd01cee6f96a502519b0db48168a36f3fd7e4f3081e7e82c7048`.

Ops 05:26:09 UTC: DB5479963671/free252146888704 bytes, head20261005_01,
health200, testDB0, markersfalse; caps/cron/source budgets прежние.
Proof SHA256 `287e1402dfecf6e996e501b1c4f156bdc1d31ed825bb1936da93d7a691425e80`.

## Обнаруженные следующие блокеры

Source0 national completed-date census 03–05 October, 05:22:27 UTC:
1485/1485 planned and attempted candidate windows, 352 canonical, 1106 NO_DATA,
27 FAILED `CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED`; 4905 versions have
4905 lexical rows, 246 procedure events. These are candidate codes01..99 and
five supported44 families, not a verified percentage of all EIS/223/documents.
NO_DATA does not prove absence. Proof
`/var/lib/eis-browser/research/rejected/s192-ingestion-a0677cb3-07a7-4be0-a9b3-01565b9195c7.json`,
SHA256 `27b38ce07cceb3bacaca2860f30435a61f5dfe67d54fb63fce0106b53167207a`.

S213 structural range exception currently rejects a whole archive. Next priority
is to preserve metadata intake while ambiguous characteristics remain UNKNOWN.
Analog UI regression is BLOCKED, not PASS: all three frozen direct queries now
hit `ANALOG_NOTICE_PAYLOAD_LIMIT` after ordinary ingestion; selected-pair checks
pass. Analog runtime module is unchanged by S214. Next bounded slice must prevent
one oversized candidate from disabling the full result without removing byte limits.
Then connect cached exact TSpec/delivery evidence to reviewed requirements and
the existing supplier-discovery workflow. This replaces cosmetic parser-only progress.
