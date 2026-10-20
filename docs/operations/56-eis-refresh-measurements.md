# S173: измерение регионального refresh 223-ФЗ

Дата: 2026-10-03. Владелец: acquisition_research. Scope: read-only измерение
текущего VPS, company `local-eis-supplier`. EIS/source HTTP/SOAP вызовы,
изменения runtime, миграции и записи БД не выполнялись.

## Результат

На нынешнем маленьком scheduler dataset SQL не является измеренным узким
местом: выбор32окон33.364ms, чтение coverage21.827ms (Python+connection+SQL).
Три завершённых региональных прохода по32окна занимали265.99–281.30s каждый.
Главный оставшийся риск — очередь и частота запуска: unseen окна имеют
приоритет перед fresh_due, а cron запускается дважды в час. Полного обхода
ещё нет; coverage/freshness UNKNOWN. Измерения не являются SLA роста корпуса.

## Снимок БД: 19:16:20.194233 UTC

| Метрика | Наблюдение |
| --- | --- |
| Каталог | PUBLIC_KLADR_SELECTOR,90регионов |
| Wave | `735f19c4-7fce-4f2a-b5a4-b596ae07c501` |
| Даты | 2026-10-02 /2026-10-03 |
| План |900окон:90регионов×5семейств×2дня |
| Попытка была |140 |
| SYNCED /NO_DATA /failed |48 /92 /0 |
| Unattempted /due /cooling |760 /763 /137 |
| Regions attempted /terminal |67 /1 |
| Old gaps |0 |
| Oldest gap day |2026-10-02 |
| First sweep finished |false |
| Observation watermark |null |
| Scope status /coverage /freshness |PARTIAL /UNKNOWN /UNKNOWN |
| `_latest` distinct keys |144 |
| `_latest` входные attempts по плану |165:notice157,rejection5,lot cancellation3 |
| `_scope` grouped keys |900 |
| pg_database_size |2,874,883,095bytes (вся БД, не размер223) |

Latest144 включает четыре ключа вне текущего плана; это не противоречит140
attempted в wave. Source day lag=0 сообщает дату плана, не свежесть всех900окон.

## SQL EXPLAIN ANALYZE

Helper использовал API `DATABASE_URL` внутри контейнера, без вывода значения.
Соединение: `default_transaction_read_only=on`, `statement_timeout=5000`.
Tenant context устанавливался штатным `storage.transaction(company,
consistent_read=True)`. SELECT-тексты scheduler/coverage перехвачены и повторены
через `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`; session set_config исключён.
Сырые параметры/DSN в proof не выводились. Первичная диагностическая count
без tenant transaction была отвергнута: RLS дал0; все числа выше из исправленного
повторения с tenant context.

| SELECT | Planning ms | Execution ms |
| --- | ---: | ---: |
| Current wave (scheduler) |0.040|0.045|
| Unseen32 (`_scope` outer join `_latest`) |0.295|1.803|
| Retry due (0строк) |0.269|0.471|
| Current wave (coverage) |0.040|0.049|
| Catalog |0.032|0.028|
| Current-wave900rows join latest |0.174|1.128|
| Old-gap count |1.025|0.646|

Планы: `_latest` UNION ALL165rows→quicksort→Unique144; `_scope` joins900targets
with1wave→aggregate900. Unseen top-N heapsort возвращает32 из760. Current
coverage сортирует900строк,144KiB; сортировки attempts46–48KiB. В измеренных
планах shared reads0, shared hits до28; spill не наблюдался. Это тёплый cache,
одна текущая wave и165attempts, не тест истории из миллионов попыток.
Fresh_due SELECT не исполнился: unseen уже заполнили лимит32.

## Cron и завершённые проходы

Log `/home/syurai/vibe-seller-state/eis-223-refresh.log`, снимок19:17:05UTC:
59075bytes,mtime19:15:39UTC,SHA256
`47d7a364e92e4fa99d72838b6d8681ac6bf467b92c4d82a289a74832e4190bf4`.
67JSONстрок;45NOT_DUE,2SERVER_IMPORT_BUSY,20без top-level reason.
Дополнительно1историческая строка shell Permission denied. Log не содержит
временных меток для каждой строки, поэтому частота ошибок по интервалам
и полная длительность ожидания lock из него не вычисляются. None reason
не интерпретируется как ошибка. Текущий crontab: `11,41 * * * *`.

| Региональный проход в log order | Окон | Seconds | Posts | ZIP GETs | Overrun |
| --- | ---: | ---: | ---: | ---: | ---: |
|1|32|281.299641|41|9|0|
|2|32|265.989147|44|12|0|
|3|32|275.294503|45|13|0|

Всего96окон в этих3строках:34SYNCED,62NO_DATA,0failed outcomes. Этот96
не равен всем140attempted wave: это ограниченная выборка завершённых log runs.
Среднее274.19s/run,8.57s/window включает смесь пустых/непустых окон; не оценка
отдельной тяжёлой закупки. Wrapper ждёт import flock до45s; start budget600s,
max32windows,per-window timeout180s по прочитанному deployed-контракту.

## Ресурсы: 19:14:40UTC

- Host RAM7941MiB;used1627MiB;available6314MiB;swap0.
- Root FS335GiB;used62GiB;available260GiB (20% used).
- Docker snapshot: worker280.3MiB/2GiB,DB636.3MiB/2GiB,
  API123.3MiB/1GiB,web73.24MiB/768MiB,proxy2.066MiB/128MiB.
- Моментальный CPU: worker0.03%,DB0.08%,API0.10%,proxy1.82%.
  Один snapshot не показывает пики, CPU duty cycle или размер будущего индекса.

## Catch-up и starvation: вывод из контракта, не результат полного sweep

На снимке760unseen,0failed,763due:3terminal окна уже fresh_due.
Scheduler заполняет unseen, резервируя один слот retry при наличии retry;
fresh_due получает только остаток лимита. Поэтому3refresh отложены за unseen.
Все32выбранных ключа ещё относятся к AESMBO (регионы66–87 в данной выборке),
так как порядок family→region→соседние дни. Остальные семейства ожидают своей
очереди. Новые календарные дни не означают, что старый план полностью обработан.

При идеально успешных будущих32/window runs760unseen требуют минимум24запуска.
При нынешних2cron/hour это около12часов scheduling slots; это арифметическая
нижняя оценка без retry/lock contention/тяжёлых архивов, не обещанный ETA.
Повтор всей900окон каждые6часов потребовал бы150windows/hour; расписание
32×2 даёт максимум64windows/hour. Текущая политика6h fresh_due поэтому
не гарантируется даже без ошибок. Ускорение SQL на этом наборе разрыв не закрывает.
Нужно явно согласовать catch-up/freshness доли и частоту в общем source budget;
увеличение трафика здесь не выполнялось.

## Воспроизводимые небольшие артефакты

Ignored каталог `data/research/eis-documents-2026-10-02/`:

- `s173-measure.py` — read-only helper;
- `s173-measure.json` — coverage,выбранные32keys,компактные планы;
  SHA256 `5dc8c27e17d993a1f80d2b3465e397eb2237a1f615ee7af71f806830c370b095`;
- `s173-measure-log.json` — компактная агрегация log/crontab;
  SHA256 `7203bb73ada528b9218766cc23c3b6ece8e3a845c06819dca622a9125010c95e`.

VPS live source worker мог дописывать journal/log между снимками; числа привязаны
к указанному времени. Все SQL завершились до5s. Полные log outcomes/секреты
не копировались в proof. Документ не утверждает full sweep, all-EIS coverage,
текущую действительность закупок или готовность участия.
