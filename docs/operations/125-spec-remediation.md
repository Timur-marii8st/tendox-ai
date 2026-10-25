# Исправления после сверки с ТЗ — 23 октября 2026

Владелец root. Пользователь поручил последовательно устранить найденные дефекты
с помощью Luna, Terra и Sol 6.1; автоматический расчёт доставки исключён из
текущего среза. Проверяемый результат — согласованные исходники установленной
беты, точная проверка маржи, подтверждение критичных настроек владельцем,
сокращение повторной обработки архивов и актуальная карта дальнейшей работы.
Это локальный кандидат, не установленный релиз и не приёмка полного MVP.

## Исходники и границы

Основной checkout отставал от выпущенного R4. Восстановлены проверенные пути
из `tmp/eis-44-archive-recovery-20261022-v28/candidate-v28b.tar.gz`, SHA256
`a4b99fd32e5818fb8ef8f31b6bfb6ddd14505865a9297ab7a78c19d5c263e0fe`.
Перечень, побайтовые проверки и резервные копии изменённых файлов находятся в
`tmp/spec-remediation-20261023/`: `source-audit.json`, `import-proof.json`,
`import-support.json`, `import-existing-scripts.json`, `before-import/`.
Ранее изменённые пользователем файлы сохранены; ограничения размера документации
совмещены с совместимостью legacy-layout в `scripts/check_docs.py`.

B11 invitations остаётся отдельным кандидатом NOT_INSTALLED. Его исходники и
миграция `20261023_01` не включались в этот срез. Миграция владельца
`20261023_02` наследует установленную `20261021_01`; для совместного выпуска
нужна явная интеграция цепочек, новый frozen source и полный release gate.
Существующие release receipts не допускают изменённый код.

## Изменения поведения

| Дефект | Исправление и граница |
|---|---|
| Округление маржи до сравнения с порогом | Shortlist сравнивает `profit` с `revenue_net * min_margin` через Decimal. При выручке 100000 и затратах 85004 фактические 14.996% не проходят порог 15%, даже если отображается 15.00%. UNKNOWN остаётся UNKNOWN. |
| Нет поддержанного пути изменения critical profile settings | Доверенный admin bootstrap может выдать отдельную роль COMPANY_PROFILE_OWNER. UI показывает точные изменения; сервер связывает подтверждение с tenant/actor/version/normalized command и сохраняет immutable audit. Старые snapshot/receipt hashes совместимы. См. [ADR0115](../adr/0115-company-profile-owner-confirmation.md). |
| Повторный разбор архива и отдельный SQL на каждый источник | TypeAdapter переиспользуется; ZIP reader и индекс членов живут внутри запроса. Архивы читаются SQL-пакетами до16MiB; архив больше этого бюджета — отдельно под прежним cap50MiB. Tenant/source/hash/hold/UNKNOWN и закрытие ресурсов защищены регрессиями. |
| Устаревшая карта покрытия ТЗ | [Матрица](../product/12-requirements-traceability.md) различает LIVE SCOPED, LOCALLY TESTED и MISSING SCOPE; импортированные контракты включены в навигацию. |

Владелец не назначается приглашением или обычным оператором. Реальные owner
credentials не создавались, production profile не изменялся. Структурированные
`prohibitions` остаются locked/UNKNOWN до отдельного контракта правил.
Авторизация профиля не выдаёт permission на RFQ dispatch, подачу или A3.

## Проверки

Evidence находится в `tmp/spec-remediation-20261023/`.

- Общий non-integration Python после batch fix: 3867 PASS, 27 SKIP
  (`final-unit-batched.log`).
- Изолированный PostgreSQL: 31 PASS — профиль, миграция, global price и
  continuation (`focused-pg-batched.log`, `migration.log`, `pg-boundary.txt`). Тестовая
  БД в disposable container, без production credentials, томов и открытых портов.
- Для каждого закона20 отдельных архивов дают ровно2 archive SQL (metadata/content),
  все20 XML SHA и навигация сохранены, audit writes0. Новый PG regression находится
  в `tests/integration/test_eis_global_price_pg.py`. Снимок PG source:
  `pg-source-batched.tar.gz`, SHA256
  `6ba39e579a5d86ea18233e0c03b58c7f1be602da8d1f3a0b88ede1aff51fee47`.
- Ruff PASS, mypy strict PASS для 24 domain files, doctests PASS.
- Frontend общий прогон после исправления decimal confirmation: 201 PASS;
  TypeScript и ESLint PASS (`web-tests-final.log`, `web-lint-final.log`). После
  совместимой с ES2017 записи BigInt повторены 6 targeted tests и основной tsc;
  production Next build PASS (`web-build-final.log`).
- Независимый review Sol: server authorization/provenance/legacy compatibility
  без дополнительных блокеров; несовпадение decimal digest для `.15`
  и `1e-1` исправлено. 13 фиксированных и 200 воспроизводимых cross-language
  сравнений с backend PASS (`owner-decimal-proof.json`), денежный коэффициент
  не преобразуется в JavaScript Number.
- Синтетический архив: 100 notices/300 reads, создание TypeAdapter 100→0,
  ZIP open/index 300→1, SQL archive fetch 1→1; около 0.451→0.097s.
  Это не измерение production latency (`navigation-cache-proof.json`).

Первый read-only запрос после ZIP-cache, до batch fix, завершён за51.955s, matches11,
regionUNKNOWN359; SQL timeout5s, 1CPU/1GiB, source requests/business writes0.
Исторические55.505s несопоставимы из-за изменяемого корпуса. Задержка остаётся
близкой к timeout60s. Дополнительный диагностический профиль56.500s выявил1825
`read_navigation` и1456SQL executions. После этого реализована пакетная загрузка;
59 focused tests PASS, независимый review не обнаружил блокеров. Порядок
наблюдений совпадает с прежним R4; CPython BytesIO сохраняет исходные bytes без
дополнительной полной копии. Старые измерения — `perf-profile.json`/`.txt`,
доказательство batching — `navigation-batch-proof.json`. Runtime после batching:
53.826s, SQL calls1458→169, SQL time22.640→20.776s; задержка ещё не принята.
Evidence: `perf-profile-batched.json`/`.txt`, independent review —
`review-navigation-batch.json`. После двух подходов причина пересмотрена:
множество roundtrips устранено, остаётся стоимость чтения самих архивов.
TEXT/BINARY A/B одного747429-byte пакета подтвердил одинаковые metadata/types/SHA;
warm TEXT7.557ms/BINARY3.053ms. Диагностический binary full run прочитал
1702991023bytes из1415archive rows за49.889s. Все119content statements имели
проверенный BINARY format; guards/read-only/cleanup PASS. Это непарное измерение,
поэтому причинный end-to-end выигрыш не принят. Binary hook остался только в
диагностике, продуктовый код не менялся. Evidence: `perf-binary-experiment.json`,
`perf-binary-full-experiment.json`. Первый сбой harness был вызван отсутствием
tenant context; после локальной проверки выполнен один разрешённый успешный retry.
Evidence: `performance-readonly-result.json`. Полный release gate и rollout
в этот результат не входят.

## Дальнейшая работа по ТЗ

1. Локальные функциональные исправления проверены; latency остаётся OPEN.
   Перед установкой нужны интеграция отдельного B11, миграционная цепочка,
   exact payload и полный release gate.
2. Продолжать текущий приоритет ЕИС: контрольная выдача по реальным номерам,
   причины пропусков, precision/recall и устойчивость свежести. Полнота UNKNOWN.
3. Проверить один реальный сквозной кейс: подтверждённый профиль, полный комплект
   ТЗ, обязательные gates, действующее полное КП и три сценария расходов.
   Наблюдение B10 о 27 UNKNOWN и нуле КП — отсутствие данных, не повод их выдумывать.
4. Затем брать ограниченные срезы PRD: структурированные запреты, S229,
   анализ/сравнение КП и supplier workflow. RFQ/application dispatch и post-award
   требуют самостоятельной реализации и проверки.

### Следующий ограниченный срез производительности

Причина пересмотра: два локальных улучшения сократили CPU setup и SQL calls,
но поиск всё ещё читает около1.7GB ZIP. Продолжать менять transport без нового
критерия недостаточно. Владелец следующего среза — root; реализация Sol6.1,
независимый review Terra, документация Luna. До изменения кода определить
owned files: extraction/ingestion, отдельное хранилище derived navigation,
поиск, миграция и соответствующие PG tests; не пересекать pending B11 migration.

Контракт: при ingestion сохранять проверенную навигацию с tenant/law/exact
source version/XML+archive SHA/parser version и provenance. Immutable projection
не подменяет источник; конфликт, отсутствие или неподтверждённые данные остаются
UNKNOWN. Hold/cancellation и snapshot/cursor semantics продолжают проверяться.
Backfill и выпуск имеют отдельный manifest, bounds и exact approval.

Acceptance: на одинаковом frozen корпусе сравнить результат и evidence с текущим
oracle; проверить неправильный tenant/SHA, пропуски, смену parser version,
holds и continuation; измерить transferred bytes и задержку при прежних
SQL5s/1GiB limits. Нельзя объявлять этот срез завершённым по одной микрометрике
или увеличивать timeout вместо устранения повторного чтения архивов.

Автоматический расчёт доставки отложен по решению пользователя. Стоимость
доставки можно вводить вручную с основанием; отсутствие суммы не заменяется
нулём и не снимает требования полной экономики. PARTICIPATE без полного
действующего КП, всех hard gates и трёх сценариев не допускается.
