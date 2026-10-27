# Архитектурные решения


[Карта документации](../README.md) · [Текущий статус](../15-implementation-plan.md)

Одно решение — один файл NNNN-kebab-title.md: Контекст / Решение / Последствия / Альтернативы.
Принятое решение сохраняется; при замене указывать новый ADR. Статус и дату смотреть
в самом решении. Индекс не требует читать все ADR перед задачей.

- [0001-cloud-plus-local-agent.md](0001-cloud-plus-local-agent.md) — ADR-0001. Cloud brain + local agent вместо чистого SaaS.
- [0002-llm-extracts-rules-decide.md](0002-llm-extracts-rules-decide.md) — ADR-0002. LLM извлекает, правила решают.
- [0003-python-domain-core.md](0003-python-domain-core.md) — ADR-0003. Python + pydantic для ядра домена.
- [0004-full-lifecycle-with-hard-gates.md](0004-full-lifecycle-with-hard-gates.md) — ADR-0004: полный жизненный цикл с hard gates.
- [0005-digital-platforms-from-foundation.md](0005-digital-platforms-from-foundation.md) — ADR 0005: цифровые платформы с первого этапа.
- [0006-reviewed-case-before-automation.md](0006-reviewed-case-before-automation.md) — ADR 0006: проверяемый кейс до внешней автоматизации.
- [0007-postgres-rls-and-bearer-tenant.md](0007-postgres-rls-and-bearer-tenant.md) — ADR 0007: tenant из bearer identity и защита PostgreSQL RLS.
- [0008-server-side-pilot-ui.md](0008-server-side-pilot-ui.md) — ADR 0008: серверный BFF для первого пилотного экрана.
- [0009-postgres-document-snapshots.md](0009-postgres-document-snapshots.md) — ADR 0009: PostgreSQL BYTEA для исходных документов в пилоте.
- [0010-local-russian-ocr.md](0010-local-russian-ocr.md) — ADR-0010: локальный русский OCR на PaddleOCR 3.7 / PP-OCRv5.
- [0011-docx-embedded-media-ocr.md](0011-docx-embedded-media-ocr.md) — ADR 0011: отдельный OCR связанных изображений DOCX.
- [0012-hybrid-document-discovery.md](0012-hybrid-document-discovery.md) — ADR 0012: гибридный поиск по нативному тексту и vision-тегам.
- [0013-immutable-document-search-index.md](0013-immutable-document-search-index.md) — ADR 0013: неизменяемые версии tenant-scoped поискового индекса.
- [0014-evidence-backed-model-brand-catalog.md](0014-evidence-backed-model-brand-catalog.md) — ADR-0014: Evidence-backed exact model→brand catalog.
- [0015-immutable-reviewed-model-brand-catalog.md](0015-immutable-reviewed-model-brand-catalog.md) — ADR-0015: Immutable reviewed model→brand catalog persistence.
- [0016-immutable-model-brand-source-artifacts.md](0016-immutable-model-brand-source-artifacts.md) — ADR-0016: Immutable model→brand official-source artifacts.
- [0017-role-aware-model-brand-review.md](0017-role-aware-model-brand-review.md) — ADR-0017: Role-aware append-only model→brand review.
- [0018-document-requirement-completeness.md](0018-document-requirement-completeness.md) — ADR-0018: Явная полнота извлечения требований документа.
- [0019-mandatory-independent-model-brand-review.md](0019-mandatory-independent-model-brand-review.md) — ADR-0019: обязательный независимый review model→brand catalog.
- [0020-completeness-gates-document-compliance.md](0020-completeness-gates-document-compliance.md) — ADR-0020: полнота блокирует положительный document compliance.
- [0021-persisted-document-completeness-review.md](0021-persisted-document-completeness-review.md) — ADR-0021: Persisted review полноты одного native-документа.
- [0022-openrouter-semantic-requirement-candidates.md](0022-openrouter-semantic-requirement-candidates.md) — ADR-0022: OpenRouter для семантических кандидатов требований ТЗ.
- [0023-persisted-ai-requirement-review.md](0023-persisted-ai-requirement-review.md) — ADR-0023: Persisted review AI-кандидатов требований.
- [0024-document-set-evidence-manifest.md](0024-document-set-evidence-manifest.md) — ADR-0024: Явный evidence manifest комплекта документов.
- [0025-terminal-document-set-completeness-review.md](0025-terminal-document-set-completeness-review.md) — ADR-0025: Терминальная проверка полноты точного комплекта документов.
- [0026-exact-ai-transfer-approval-and-response-retention.md](0026-exact-ai-transfer-approval-and-response-retention.md) — ADR-0026: Exact approval внешней AI-передачи и retention ответа.
- [0027-server-managed-ai-requirement-materialization.md](0027-server-managed-ai-requirement-materialization.md) — ADR-0027: server-managed AI requirement materialization.
- [0028-reviewed-requirement-set-case-binding.md](0028-reviewed-requirement-set-case-binding.md) — ADR-0028: reviewed requirement set и exact case binding.
- [0029-server-derived-requirement-table-materialization.md](0029-server-derived-requirement-table-materialization.md) — ADR-0029: server-derived materialization таблицы требований.
- [0030-official-manufacturer-catalog-failover.md](0030-official-manufacturer-catalog-failover.md) — ADR-0030: официальный каталог производителя и supplier failover.
- [0031-multi-source-sourcing-artifacts.md](0031-multi-source-sourcing-artifacts.md) — ADR-0031: exact artifacts нескольких sourcing sources.
- [0032-independent-requirement-set-review-and-binding-ui.md](0032-independent-requirement-set-review-and-binding-ui.md) — ADR-0032: независимый review и operator binding exact requirement set.
- [0033-exact-server-offer-proposal.md](0033-exact-server-offer-proposal.md) — ADR-0033: exact server BOM и коммерческое предложение как pending proposal.
- [0034-independent-server-offer-review.md](0034-independent-server-offer-review.md) — ADR-0034: независимая построчная проверка server offer.
- [0035-reviewed-offer-economics-package.md](0035-reviewed-offer-economics-package.md) — ADR-0035: complete economics package из independently reviewed offer.
- [0036-controlled-case-version-from-reviewed-offer.md](0036-controlled-case-version-from-reviewed-offer.md) — ADR-0036: controlled case version из reviewed offer economics.
- [0037-exact-hard-gate-assessment-materialization.md](0037-exact-hard-gate-assessment-materialization.md) — ADR-0037: exact materialization оставшихся hard gates.
- [0038-independent-participation-decision.md](0038-independent-participation-decision.md) — ADR-0038: независимое решение об участии по exact evaluation.
- [0039-exact-application-package-proposal.md](0039-exact-application-package-proposal.md) — ADR-0039: exact proposal комплектации заявки после APPROVED.
- [0040-independent-application-package-review.md](0040-independent-application-package-review.md) — ADR-0040: независимая проверка exact комплекта заявки.
- [0041-exact-application-submission-approval.md](0041-exact-application-submission-approval.md) — ADR-0041: краткосрочное подтверждение exact команды подачи.
- [0042-one-time-application-submission-admission.md](0042-one-time-application-submission-admission.md) — ADR-0042: одноразовый admission без подачи на площадку.
- [0043-verified-application-handoff.md](0043-verified-application-handoff.md) — ADR-0043: проверяемый архив для ручной передачи заявки.
- [0044-eis-source-contract.md](0044-eis-source-contract.md) — ADR-0044: официальный сервис отдачи ЕИС как источник индекса.
- [0045-eis-corpus-queue-and-procedure-events.md](0045-eis-corpus-queue-and-procedure-events.md) — ADR-0045: очередь большого корпуса и отдельные события процедуры.
- [0046-eis-lexical-prefilter.md](0046-eis-lexical-prefilter.md) — ADR 0046: version-bound поисковые ключи ЕИС.
- [0047-eis-version-bound-document-queue.md](0047-eis-version-bound-document-queue.md) — ADR 0047: очередь и кеш документов точной версии извещения.
- [0048-legacy-xls-extraction.md](0048-legacy-xls-extraction.md) — ADR 0048: буквальные ячейки legacy XLS и новая версия разбора.
- [0049-legacy-doc-text.md](0049-legacy-doc-text.md) — ADR 0049: ограниченная текстовая производная legacy DOC.
- [0050-eis-223-metadata-index.md](0050-eis-223-metadata-index.md) — ADR-0050 — отдельный immutable metadata индекс 223-ФЗ.
- [0051-eis-223-schema-quality.md](0051-eis-223-schema-quality.md) — ADR-0051 — качество полного223XML отдельно от metadata projection.
- [0052-general-223-metadata.md](0052-general-223-metadata.md) — ADR-0052 — явный metadata contract purchaseNotice.
- [0053-eis-223-cancellation-evidence.md](0053-eis-223-cancellation-evidence.md) — ADR-0053 — отдельное evidence отмены закупки 223-ФЗ.
- [0054-eis-223-lot-cancellation-evidence.md](0054-eis-223-lot-cancellation-evidence.md) — ADR-0054 — evidence отмены отдельного лота 223-ФЗ.
- [0055-eis-223-regional-coverage.md](0055-eis-223-regional-coverage.md) — ADR-0055 — автоматический региональный scope223 и честный backlog.
- [0056-eis-catalog-revalidation-and-refresh-lanes.md](0056-eis-catalog-revalidation-and-refresh-lanes.md) — ADR-0056 — проверка каталога223 и очереди обновления.
- [0057-eis-cooperative-source-lease.md](0057-eis-cooperative-source-lease.md) — ADR-0057 — согласованная передача source lease между44 и223.
- [0058-eis-byte-identical-notice-members.md](0058-eis-byte-identical-notice-members.md) — ADR-0058 — evidence quarantine конфликтующих versions44.
- [0059-eis-223-four-archive-window.md](0059-eis-223-four-archive-window.md) — ADR-0059 — полный notice223 window до четырёх архивов.
- [0060-eis-44-conflict-diagnosis.md](0060-eis-44-conflict-diagnosis.md) — ADR-0060 — bounded диагностика конфликтующих notice44.
- [0061-eis-44-notice-variant-ledger.md](0061-eis-44-notice-variant-ledger.md) — ADR-0061 — immutable ledger вариантов notice44.
- [0062-eis-44-consumer-variant-hold.md](0062-eis-44-consumer-variant-hold.md) — ADR-0062 — shared consumer hold для unresolved notice44 evidence.
- [0063-eis-44-retained-variant-projection.md](0063-eis-44-retained-variant-projection.md) — ADR-0063 — explicit retained variant projection.
- [0064-eis-44-automatic-partial-intake.md](0064-eis-44-automatic-partial-intake.md) — ADR-0064 — automatic partial intake rejected notice44 window.
- [0065-eis-gap-census-and-historical-source-retry.md](0065-eis-gap-census-and-historical-source-retry.md) — ADR-0065 — полный gap census и bounded historical transient retry.
- [0066-eis-obsolete-attachment-limit-recovery.md](0066-eis-obsolete-attachment-limit-recovery.md) — ADR-0066 — bounded recovery obsolete attachment-count failures.
- [0067-eis-parser-failure-diagnostics.md](0067-eis-parser-failure-diagnostics.md) — ADR-0067 — source-bound parser failure diagnostics.
- [0068-eis-cached-search-deadline-scope.md](0068-eis-cached-search-deadline-scope.md) — ADR-0068 — explicit deadline scope for cached EIS search.
- [0069-eis-search-single-cursor.md](0069-eis-search-single-cursor.md) — ADR-0069 — single streamed candidate cursor for cached EIS search.
- [0070-eis-national-daily-scheduling.md](0070-eis-national-daily-scheduling.md) — ADR-0070 — five-family daily planning with bounded backlog fairness.
- [0071-eis-shared-lease-observability.md](0071-eis-shared-lease-observability.md) — ADR-0071 — bounded shared import-lease observability.
- [0072-eis-durable-planning-retry.md](0072-eis-durable-planning-retry.md) — ADR0072 — durable retry of completed-date planning.
- [0073-eis-recent-ingestion-report.md](0073-eis-recent-ingestion-report.md) — ADR0073 — снимок прохождения свежих окон в индекс.
- [0074-eis-fresh-first-attempt-share.md](0074-eis-fresh-first-attempt-share.md) — ADR0074 — доля и порядок первых попыток свежих окон.
- [0075-eis-corpus-bounded-continuation.md](0075-eis-corpus-bounded-continuation.md) — ADR0075 — bounded continuation после cooperative yield.
- [0076-eis-recent-no-data-rechecks.md](0076-eis-recent-no-data-rechecks.md) — ADR0076 — резерв для повторной проверки недавних NO_DATA.
- [0077-eis-no-data-aging-evidence.md](0077-eis-no-data-aging-evidence.md) — ADR0077 — возраст NO_DATA и границы доказательства пустого окна.
- [0078-eis-older-no-data-reserve.md](0078-eis-older-no-data-reserve.md) — ADR0078 — один ранний слот для старых NO_DATA.
- [0079-eis-no-data-raw-evidence.md](0079-eis-no-data-raw-evidence.md) — ADR0079 — bounded raw NO_DATA evidence.
- [0080-eis-no-data-store-operations.md](0080-eis-no-data-store-operations.md) — ADR0080 — операторский контроль bounded evidence store.
- [0081-eis-no-data-public-cross-check.md](0081-eis-no-data-public-cross-check.md) — ADR0081 — NO_DATA и публичный канал: сравнивать scope явно.
- [0082-eis-public-candidate-recovery.md](0082-eis-public-candidate-recovery.md) — ADR0082 — ограниченное восстановление public candidates по номеру.
- [0083-eis-mixed-number-archives.md](0083-eis-mixed-number-archives.md) — ADR0083 — метаданные дополнительных документов адресного набора.
- [0084-eis-historical-protocol-facts.md](0084-eis-historical-protocol-facts.md) — ADR0084 — исторические факты отдельных протоколов.
- [0085-bounded-historical-analog-selection.md](0085-bounded-historical-analog-selection.md) — ADR0085 — ограниченный отбор исторических аналогов.
- [0086-eis-recorded-range-evidence.md](0086-eis-recorded-range-evidence.md) — ADR0086 — исходные границы и наблюдения записанных диапазонов.
- [0087-eis-analog-payload-omissions.md](0087-eis-analog-payload-omissions.md) — ADR 0087 — явные пропуски в ограниченной выдаче аналогов.
- [0088-eis-native-review-capture.md](0088-eis-native-review-capture.md) — ADR 0088 — отдельный анализ исходного DOCX для проверки.
- [0089-eis-document-review-ui.md](0089-eis-document-review-ui.md) — ADR 0089 — точный source0 просмотр DOCX и ограниченный prepare процесс.
- [0090-eis-position-supplier-search.md](0090-eis-position-supplier-search.md) — ADR0090: отдельные ценовые наблюдения по позиции ЕИС.
- [0091-eis-position-fragment-association.md](0091-eis-position-fragment-association.md) — ADR0091: операторская связь исходных фрагментов с позицией.
- [0092-eis-position-association-restore.md](0092-eis-position-association-restore.md) — ADR0092: восстановление связи по scope и ID.
- [0093-eis-public-position-supplier-serp.md](0093-eis-public-position-supplier-serp.md) — ADR 0093: поиск новых поставщиков через публичную выдачу.
- [0094-eis-public-supplier-page-observation.md](0094-eis-public-supplier-page-observation.md) — ADR 0094 — ограниченное чтение сайта из сохранённого SERP evidence.
- [0095-eis-confirmed-supplier-catalog-search.md](0095-eis-confirmed-supplier-catalog-search.md) — ADR 0095 — подтверждённый поиск внутри сайта поставщика.
- [0096-eis-retained-product-details.md](0096-eis-retained-product-details.md) — ADR0096 — производные условия из сохранённой товарной карточки.
- [0097-eis-selected-requirement-table-preview.md](0097-eis-selected-requirement-table-preview.md) — ADR0097 — точная таблица DOCX перед review требований.
- [0098-eis-independent-selected-table-review.md](0098-eis-independent-selected-table-review.md) — ADR-0098: независимая проверка выбранной таблицы ЕИС.
- [0099-persisted-manufacturer-search.md](0099-persisted-manufacturer-search.md) — ADR-0099: сохранённый поиск изготовителей по товарным записям ЕАЭС.
- [0100-independent-manufacturer-review.md](0100-independent-manufacturer-review.md) — ADR-0100: независимая проверка identity и роли производителя.
- [0101-run-scoped-manufacturer-grouping.md](0101-run-scoped-manufacturer-grouping.md) — ADR-0101: консервативная сводка изготовителей одного сохранённого поиска.
- [0102-manufacturer-rfq-draft.md](0102-manufacturer-rfq-draft.md) — ADR-0102: неизменяемый внутренний черновик запроса КП изготовителю.

- [0103-supplier-serp-fallback-engines.md](0103-supplier-serp-fallback-engines.md) — ADR0103 (withdrawn): отменённый пакет дополнительных поисковиков; совместимость исторического evidence.
- [0104-persistent-headed-supplier-browser.md](0104-persistent-headed-supplier-browser.md) — ADR0104: обычный Chrome/CDP, отдельные профили и сохранённые паузы; границы VPS.
- [0105-human-supplier-captcha.md](0105-human-supplier-captcha.md) — ADR0105: ограниченное ручное окно CAPTCHA, проверка выдачи и одноразовое возобновление.
- [0106-eis-search-continuation.md](0106-eis-search-continuation.md) — ADR0106: страницы сохранённого поиска с tenant/query/clock/evidence guards.
- [0107-candidate-triggered-quality-gate.md](0107-candidate-triggered-quality-gate.md) — ADR0107: локальный provider-independent quality gate при submission кандидата, immutable receipts и граница активации.
- [0108-bounded-eis-audit-row-fragments.md](0108-bounded-eis-audit-row-fragments.md) — ADR0108: явный audit-only format v2 с ограниченными фрагментами; actual corpus и метрики ещё не подтверждены.
- [0109-bounded-eis-capture-v3-state.md](0109-bounded-eis-capture-v3-state.md) — ADR0109: обычные большие строки V3 и отдельные бюджеты временного состояния; actual fit не подтверждён.
- [0110-bounded-no-data-overflow.md](0110-bounded-no-data-overflow.md) — ADR0110: второй ограниченный сегмент NO_DATA с сохранением старых audit references.

- [0111-protected-eis-day-reconciliation.md](0111-protected-eis-day-reconciliation.md) — Защищённая обработка недавних суточных пропусков ЕИС.

- [0112-bounded-large-223-notices.md](0112-bounded-large-223-notices.md) — ADR0112 — ограниченные большие извещения223-ФЗ.

- [0113](0113-bounded-44-source-references.md) — большие окна44 и typed aliases вложений; R4 установлен.

- [0114-beta-company-invitations.md](0114-beta-company-invitations.md) — ADR0114 — одноразовые приглашения и отдельные компании бета-тестеров.
- [0115-company-profile-owner-confirmation.md](0115-company-profile-owner-confirmation.md) — ADR0115 — подтверждение владельцем критичных настроек профиля; проверено локально, NOT_INSTALLED.

- [0116-eis-hybrid-discovery-recovery.md](0116-eis-hybrid-discovery-recovery.md) — Ограниченная очередь пропусков из публичной выдачи и штатный адресный intake.

- [0117-eis-active-sweep.md](0117-eis-active-sweep.md) — Обход активных44 без query, атомарные диапазоны и очередь.

- [0118-eis-regional-contract-history.md](0118-eis-regional-contract-history.md) — V45: официальные контрактные результаты, объём заказчика и региональные сценарии; выпуск не принят.
- [0119-eis-drug-position-projections.md](0119-eis-drug-position-projections.md) — отдельные исходные лекарственные позиции; реализация V50.

- [0120-eis-freshness-priority-wait.md](0120-eis-freshness-priority-wait.md) — V51: один fresh waiter и bounded priority handoff; IMPLEMENTING.

- [0121-eis-223-regular-kesmbo.md](0121-eis-223-regular-kesmbo.md) — V52: регулярный KESMBO, additive6family wave и защита истории; IMPLEMENTING.

- [0122-eis-223-regular-zpesmbo.md](0122-eis-223-regular-zpesmbo.md) — V54: ZP source binding и add-only5/6→7scope; contract review.

- [0123: joint positions223](0123-eis-223-joint-position-projection.md).
