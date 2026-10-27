# V57: весь зафиксированный корпус ZP в основном поиске

Владелец root; ACCEPTED_BOUNDED_FIXED135_API, independent result review PASS. Зависимость — принятый
[V56](144-eis-223-joint-backfill.md). Evidence tmp/eis-zp-corpus-search-20261027-v57/.

## Проверяемый результат

Все135 fixed latest ZP извещений,34архива,287nativeitems: exactnumber mainroute,
HTTP200/no-store, coverageUNKNOWN; точные версия, XML/ZIP/responseSHA/window,
noticeJSON и jointprojectionJSON. 133ordinary/2joint; факт изменённой версии UNKNOWN,
пропуск/расхождение FAIL; частичный результат не становится PASS.
Cases2,562,035B SHAe561ce8b88daf631802a2aef0df1c0f9d2cf6f65cd426289842264a4e40a7ed9.
Readplan5aed1f7f9735cafbc393bfeef608b90ba7e84dc27193492f853535beab1108f0.

## Выполнение и границы

Установленный APIad34/WEBca9d/schema27_02 и realDB; ASGI/TestClient проходит тот же
основной route. Actual browser5 принят отдельно V56,135UI не заявляется.
Force read-only DB/SQL5s/lock2s,135queries,180swall,4MiBinput/512KiBrecord,
2MiBresponse. Source0/productionwrites0/archivefetch0; образы/schema/cron прежние.
1positive+11negative checks: missing/ambiguous/version drift/rawfact/projection/quantity drift,
source/cache/falsecoverage/budget/HTTP. Неизвестный transport/parser error UNKNOWN.

Новый reader нужен из-за фиксированных5разныхZIP в прежнем verifier; он не может
проверить весь135набор с повторяющимися архивами. Frozen inventory/classification
сверяется с routeJSON без новых ZIP reads. Payload2.56MiB передаётся через stdin,
поскольку single exec argument ограничен; bounded process-group cleanup и separate
stdout/stderr сохраняют предупреждения. Runtime/proof/input SHA до/после проверяются.
Национальная полнота, свежесть, полнота ТЗ, прогноз и PARTICIPATE UNKNOWN.

## Принятый результат

read-result.json PASS:135PASS/0FAIL/0UNKNOWN,287nativeitems,8.230s;
maxresponse106683B. Все135 версий/source facts/projectionJSON совпали с frozen
native corpus. Runtime неизменён, source0/productionwrites0/archivefetch0.
TestClient warning сохранён отдельно в read-stderr.txt; stdout JSON чистый.
result-review.json PASS_BOUNDED_FIXED135_NATIVE_MAIN_API_PARITY,
SHA6efc8ed89f5d8d4d8b077556cea4f0d40a0118edb417c920365fce5f1c9daab7.
Это135API проверок;5actualbrowser проверок — в V56. Национальное покрытие UNKNOWN.
