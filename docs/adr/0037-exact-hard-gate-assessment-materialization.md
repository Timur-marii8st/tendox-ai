# ADR-0037: exact materialization оставшихся hard gates

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

S89 создаёт immutable case version с exact КП, complete economics и одним
technical `PASS` из independent offer review. Для запуска recommendation нужны
ещё `LEGAL`, `PARTICIPANT`, `COMPANY_POLICY`, `LOGISTICS` и `DOCUMENT`. Изменять
assessment внутри сохранённой версии нельзя, а ручной `DOCUMENT PASS` обошёл бы
terminal document-set completeness review.

## Решение

Создавать следующую immutable case version отдельной OPERATOR-командой. Source
version принимается только тогда, когда repository может восстановить её из
S89 audit lineage и exact reviewed-offer economics package. Technical check
переносится без изменений и не присутствует в caller payload.

`DOCUMENT` строится сервером функцией `document_gate_check_from_binding` из
exact `CaseDocumentEvidenceBinding`, manifest digest и terminal decision digest.
Caller не передаёт его status. Для `LEGAL`, `PARTICIPANT`, `COMPANY_POLICY` и
`LOGISTICS` обязательны ровно четыре явных решения. `PASS` и `FAIL` требуют
tenant-visible persisted document ID, SHA-256 и locator; `UNKNOWN` может не
иметь evidence и не превращается в допуск.

Case `N+1`, полный six-gate `CaseAssessment`, audit event и idempotency receipt
записываются одной транзакцией. Assessment получает digest нового snapshot и
время сервера. Команда не запускает recommendation engine.

## Последствия

Technical и DOCUMENT gates невозможно заменить произвольным browser payload.
Любой известный ручной gate имеет проверяемые persisted bytes и locator, а
неполная информация остаётся `UNKNOWN`. После создания версии пользователь
отдельно запускает существующий evaluation endpoint; `PARTICIPATE` возможен
только если все шесть gates PASS, КП действительно и три сценария complete.
Новая schema migration не требуется: используются `case_versions`, documents,
audit и write receipts.
