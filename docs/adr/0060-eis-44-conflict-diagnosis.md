# ADR-0060 — bounded диагностика конфликтующих notice44

Статус: **ACCEPTED / DEPLOYED**, 2026-10-04, 07:49 UTC.
Дата: 2026-10-04, S177. Owner ADR: Astra; source module: Sol;
integration/storage audit: root.

## Основание

Retained window содержит 499 XML members и 498 уникальных пар
purchase number / numeric version. Два XML имеют один direct notice/id
`44105096`, version `1`, schema `16.2` и одинаковый document number.
Сравнение всех 224 leaf values выявило только различия
`commonInfo/publishDTInEIS` и `notificationInfo/procedureInfo/collectingInfo/startDT`
(около 87 секунд). Document ID поэтому не разрешает этот конфликт.

Identity proof: `/var/lib/eis-browser/research/rejected/s177-identity-proof.json`,
SHA-256 `7647d77c04981e7f7a45c4db388772d817e12e33104abf6012933a10dc0734dc`.
Исследование source contract: [docs60](../eis/ingestion/60-eis-44-version-contract-research.md).
Publication/start являются business dates; filename UUID, archive order и
более позднее время не доказаны как правило выбора канонического XML.

## Решение

Реализовать только bounded offline full-window diagnosis. Не менять admission,
canonical identity, version-conflict guards, checkpoints или current projection.
Существующий whole-window FAILED сохраняется. Диагноз имеет смысл UNKNOWN:
он описывает различия evidence и не выбирает достоверный вариант.

Типизированный результат связывается с tenant, exact retained manifest SHA,
source response/window и всеми archive/member/XML SHA. Source document ID
извлекается только как provenance: unique direct child в ожидаемом namespace,
с bounded значением. Missing/ambiguous identity не превращается в совпадение.
Для каждого conflict group сохраняются обе SHA и идентичности, проверенная
полнота сравнения и bounded структурные paths различий. Нельзя утверждать
«различаются только timestamps», если сравнение неполно или найден иной XML
состав; более сильный вывод не выводится из сокращённого summary.

Полный inventory и успешная диагностика означают, что изучен exact bounded
набор, а не что source window допущен. Нельзя пропускать проблемный member,
присваивать subset статус COMPLETE или выбирать first/latest вариант.

## Ресурсные и security gates

До XML parse проверяются headers всех ZIP: compressed/expanded/window/member
caps, ZIP member names и однозначность provenance. Per-file limits сохранены;
небезопасный XML, duplicate filenames и нарушенный source binding не допускаются.
Ни cap, ни число архивов не повышаются скрыто ради диагностики. Внешние bytes
недоверенны; namespace, DTD/entity и reflection guards применяются до вывода.
Secret/reflection не попадает в paths, summary, persisted report или ошибки.
Превышение bound даёт явный неполный/неуспешный диагноз, сохраняя original FAILED.

## Хранение и видимость

Отдельный immutable tenant audit закрепляет diagnosis/report SHA и exact
retained evidence. Replay того же payload не создаёт повторный audit;
несовпадающий payload не заменяет прежний. Tenant/RLS и безопасные reason codes
проверяются независимо от filesystem evidence. Ошибка диагностики, retention
или audit не подменяет исходную причину отказа intake.

Feed/corpus/freshness получают только bounded typed safe summary и evidence
reference. Диагноз не выдаёт supplier PASS, действующий deadline, SYNCED,
полную coverage или разрешение на документ/estimate/action. Существующие
hard gates и history остаются неизменными.

## Acceptance

Нужны tests full-header-before-parse; caps/unsafe XML/namespace/reflection;
same ID + divergent dates; отличия вне dates; incomplete comparison;
tenant isolation, immutable audit/replay; original-error preservation.
На retained sample доказать all-member inventory и точный conflict group без
source calls и без index/checkpoint mutation. Результаты rollout приведены ниже.

## Review реализации

Проверены source diagnosis и root integration/storage/status. Ранее найденные
encoding/DTD, decoded reflection и model regrouping gaps исправлены. UTF-8
проверяется вместе с NUL/declaration rejection; XML parser прерывается во время
построения дерева после 50,000 nodes или depth 128. Эти guards используются
и при повторном parse для structural timing comparison. Leaf purchase number,
xs:long ID / int version bounds и raw timestamp text проверяются отдельно.
Decoded reflection включает tags, attribute names/values и text.

Полный occurrence inventory и duplicate groups повторно проверяются при model
validation: ключи, multiset membership, типы, SHA classification, identity,
timing categories и non-timing structural SHA. Последний описывает сериализованную
XML-структуру после удаления двух exact-path timing texts; это не побайтовая
канонизация исходного XML. Исходные XML SHA остаются отдельным evidence.

Integration публикует diagnosis только после отдельного успешного tenant audit,
связанного с ранее audited retained manifest и exact ordered archive SHAs.
Ошибки сохраняют исходный отказ. Новых blockers при повторном bounded review
не найдено. Sol сообщил 37 focused PASS; root подтвердил финальные 158 Linux
PASS, 22 isolated PG PASS и Ruff/mypy для пяти modules. PG использовал только
`procurement_eis_test_20261004_s177`.

## Пройденный retained-sample gate

Root подтвердил exact retained полный reject hook + replay с resident blank
Chromium в cgroup 2 GiB: 5 ZIP / 499 XML, provenance всех 499 occurrences,
одна DIVERGENT group с SAME document ID. Report 338,074 JSON bytes, SHA-256
`5ca4af5206ba669f257891dba79d19dfa0c64ad5253a8c94f6c70b685c494805`.
Cgroup peak 379,813,888 bytes (около 362 MiB), Python max RSS 236,920,832 bytes;
full hook + replay 13.154 s. Source calls 0, index/checkpoint/attempt delta 0,
replay file writes 0. Это offline sample measurement, не online SLA и не
универсальная оценка максимальной XML сложности.

Isolated proof: `/var/lib/eis-browser/research/rejected/s177-isolated-proof.json`,
SHA-256 `d48b8212ca502b65e0c4a2aa6df542e12e5d0f2a829cffebc74499e655bb261a`.
Code review и release gates пройдены; admission guard по контракту остаётся
неизменным после rollout.

## Production evidence

Root подтвердил rollout в 07:49 UTC: scoped hashes host 18 / API 5 совпали,
API/worker rebuilt, backup выполнен перед rollout. Schema HEAD
`20261004_01` неизменён; новая migration не требовалась.

На exact retained production evidence повторены полный reject hook и replay:
5 ZIP / 499 XML, тот же report SHA `5ca4af5206ba669f257891dba79d19dfa0c64ad5253a8c94f6c70b685c494805`.
Добавлен один immutable diagnosis audit; retention audit delta 0,
replay file writes 0, index/checkpoint/attempt delta 0, source calls 0.
Фактический 44-FZ gap остаётся FAILED, historical attempts неизменны.

Full hook + replay занял 13.387 s; cgroup peak 382,709,760 bytes (около 365 MiB)
при прежнем лимите 2 GiB и resident blank Chromium. Это retained offline
measurement, без обещания online latency или полной freshness.
Proof: `/var/lib/eis-browser/research/rejected/s177-retained-proof.json`,
SHA-256 `9c2a7f76e1380fc1e642bcaca2ac5b2f0231702ff711460166b76f75d4462450`.
