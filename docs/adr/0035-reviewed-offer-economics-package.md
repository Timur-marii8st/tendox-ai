# ADR-0035: complete economics package из independently reviewed offer

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

После S87 существует воспроизводимый technical `PASS` exact BOM/КП. Старый
`ProcurementCase` умеет считать три сценария, но browser-import целого case JSON
не доказывает, что goods, НДС и коммерческий источник взяты из этого PASS offer.

## Решение

Создавать отдельный `server-offer-economics-package-v1` только из terminal PASS
offer review для той же immutable версии кейса. Сервер сам переносит goods без
НДС и ставку НДС из exact КП. Operator передаёт ровно три упорядоченных сценария
`base`, `realistic`, `conservative`, выручку, явные допущения и каждую прочую
статью расходов. Все значения — `Decimal`; отсутствующая статья не считается
нулём, а явный ноль сохраняется как подтверждённое значение.

Package связывает case input digest, offer proposal digest, review decision
digest и source document digest. Он append-only, tenant-scoped и один на версию
кейса. `scenario_status=COMPLETE`, но `recommendation_status=UNKNOWN`: package не
мутирует case, не создаёт assessment и не выдаёт `PARTICIPATE`.

## Последствия

Экономику можно проверить и воспроизвести до создания следующей версии кейса.
Следующий срез должен материализовать новую case version из exact package,
потребовать актуальные hard-gate assessments и только затем вызвать существующий
recommendation engine.
