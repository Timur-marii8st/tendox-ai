# ADR-0027: server-managed AI requirement materialization

Дата: 2026-09-17  
Статус: Accepted for the local pilot; production prerequisites remain open

## Решение

Уже captured terminal `SUCCESS` можно материализовать только сервером и только
для одного chunk. Materialization не делает сетевой вызов и не повторяет
provider dispatch. При успешной строгой проверке создаются в одной транзакции
raw-free `persisted-ai-requirement-run-v2` и append-only receipt в миграции
`20260917_08`.

В snapshot сохраняются typed candidates, provenance и цепочка SHA-256 evidence;
provider `response_content`, plaintext и ciphertext в reviewer queue не входят.
Полнота результата всегда начинается как `UNKNOWN`. Multi-chunk и invalid
candidate evidence фиксируются как terminal `REJECTED`.

## Доступ и совместимость

Recovery endpoint — `POST
/v1/ai-transfer-executions/{execution_id}/requirement-materializations` —
доступен только owning operator. Повторный вызов идемпотентен. Reviewer queue
читает persisted v1 и v2 snapshots, а raw response остаётся отдельным
reviewer/auditor-only ресурсом с encrypted retention 30 дней.

## Последствия

Решение исключает повторный внешний вызов после capture и не смешивает raw с
доказательным reviewer snapshot. Multi-chunk намеренно остаётся за пределами
этого среза. Production включение заблокировано до внешних evidence по managed
KMS с rotation и backup/WAL/restore retention.
