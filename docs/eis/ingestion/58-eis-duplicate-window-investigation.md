# S175: исследование незавершённых окон

## Read-only runtime measurement — 2026-10-04

Владелец измерения: acquisition_research. Company `local-eis-supplier`.
Снимок PostgreSQL05:36:09.756579UTC; filesystem05:36:38UTC.
Без source/EIS calls, runtime-изменений и записей БД. API DATABASE_URL
использован внутри контейнера без вывода; соединение read-only,
statement_timeout5000ms, штатный tenant context. Сохранён небольшой proof.
Отдельный live44ZIP capture выполняет root; его результаты здесь пока
не представлены.

### Две волны223

Обе wave имеют900ключей:90PUBLIC_KLADR_SELECTOR codes×5семейств×2дня.
Каталог SHA `b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`,
последняя успешная проверка03.10.19:28:12.761590UTC,ACCEPTED.

| Wave | Даты | СозданаUTC | SYNCED | NO_DATA | FAILED | Unattempted |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `735f19c4-7fce-4f2a-b5a4-b596ae07c501` |02–03.10|03.10.17:49:23.100941|261|638|1|0|
| `a55b3391-cb3e-4f58-8dd9-6a69b4b7bc22` |03–04.10|04.10.00:21:14.927349|33|867|0|0|

Текущая wave:attempted900,regions_attempted90,regions_terminal90,
first_sweep_finished=true,scope_statusCOMPLETE. Это проверка **точного плана**,
не whole-EIS. Coverage/freshness UNKNOWN,old_gaps1,oldest_gap_day02.10.
Due15,cooling885; observation_watermark03.10.23:31:18.108689UTC.
Watermark старше создания текущей wave: перекрывающийся день03.10 переиспользует
journal evidence предыдущей wave; не трактовать900как900новых sourcecalls.
Самая поздняя текущая проверка среди её latest outcomes04.10.05:31:54.654735UTC.
Это не отдельно измеренное время первого завершения обхода.

### Точный старый разрыв223

`getDocsIP/RI223/77/2026-10-02+03:00/purchaseNotice`.
LatestFAILED04.10.05:01:28.067425UTC,reason`ARCHIVE_SET_MISMATCH`,responseSHA=null.
Все7сохранённых nonterminal notice-attempts относятся к этому ключу:

```text
2026-10-03 22:07:59.849075Z
2026-10-03 23:11:20.755228Z
2026-10-04 00:21:48.417881Z
2026-10-04 01:31:28.642593Z
2026-10-04 02:41:22.980462Z
2026-10-04 03:51:26.513578Z
2026-10-04 05:01:28.067425Z
```

Во всех одна причина и nullresponseSHA. Причина валидации известна,
конкретное расхождение initial/prepared/archive members без retained source
proof не определено. Не превращать mismatch в NO_DATA/успешное неполное окно.
Nonterminal records в rejection/lot-cancellation journals не найдены.
Текущие0failed не означают0исторических разрывов223.

### Отдельное окно44: дубль версии

Ключ `getDocsIP/PRIZ/77/2026-09-29+03:00`.
У него8сохранённых попыток, всеFAILED`DUPLICATE_NOTICE_VERSION`, без
source_response_sha256; ingested window отсутствует. Новых записей после
S174не появилось:latest03.10.20:30:29.432893UTC,первая29.09.23:45:54.120527UTC.
Восемь timestamps и безопасные reason codes сохранены в proof.
Parser проверяет повтор(number,version) внутри ZIP; равенство либо конфликт
байтов XML пока UNKNOWN. Отсутствие архивного responseSHA в journal —
ограничение доказательства, не основание делать вывод о повреждённом XML.

### Корпус и размеры

- 223:2526distinct purchase numbers,2614notice versions. Это не2526действующих
  открытых закупок и не доказательство отсутствия отмен.
- Вся БД:3,390,094,359bytes.
- Крупнейшие relation totals (включают индексы/TOAST):

| Relation | Bytes | Estimated rows |
| --- | ---: | ---: |
| eis_feed_archives |2290401280|5372|
| eis_notice_versions |581853184|132369|
| eis_223_blobs |214695936|293|
| audit_events |125198336|168549|
| eis_notice_search_keys |71639040|132366|
| eis_sync_targets |47489024|148048|

PG estimated rows — статистика, не дополнительные точные counts.
Browser state volume135MiB;host state12GiB (включает retained/backup artifacts).
Root filesystem335GiB,used66GiB,available256GiB,21%used.
На этом снимке запас диска велик; основной immutable source payload хранится
в PG, поэтому du browser-state отдельно не описывает весь корпус.

### Следующий ограниченный шаг

Catch-up текущего900-keyплана завершён; практический риск сместился к
двум воспроизводимым source-contract failures. Разбирать их отдельно:

1. Для44получить/сохранить bounded rejectedZIP evidence и классифицировать
   byte-identical дубли против divergent XML. Exact duplicate может получить
   отдельный provenance-preserving контракт; divergent нельзя автоматически
   выбирать по порядку/первому member.
2. Для223сохранить безопасный manifest evidence initial/prepared/full archive
   set по единственному gap, затем определить несоответствие. Не увеличивать
   лимиты и не признавать неполное окно полным только ради закрытия gap.

Измерение не устанавливает6hSLA, полноту всей ЕИС или готовность участия.

### Proof

VPS `/home/syurai/vibe-seller-state/s175-measure.json`, matching local ignored
`data/research/eis-documents-2026-10-02/s175-measure.json`.
SHA256 `bfa38ed9462f0387530fc6c105e72fad069f7bca184c3ba8a0b257618af7f093`.
Local helper `s175-measure.py`. Proof содержит агрегаты, до20safe gap/history
записей и размеры, без raw transport exceptions/DSN/token.

## Фактическая классификация окна 44-ФЗ

04.10.2026 сохранён полный набор для `getDocsIP/PRIZ/77/2026-09-29+03:00`:
5 ZIP, 499 XML members, 498 уникальных пар номера и версии. Распакованный
объём 85 606 319 bytes; ZIP и входящие SOAP вместе занимают 7 701 141 bytes.
Один диагностический запуск выполнил 2 POST и 5 GET, без изменения базы.
Архивы остались на VPS под компанией `local-eis-supplier`.

Найдена одна расходящаяся пара: закупка `0373100047426001450`, версия 1.
Из 224 leaf fields различаются ровно два: время публикации в ЕИС и начало
приёма заявок; разница примерно 87 секунд. Совпадающих по байтам повторов нет.
Это не позволяет выбрать первый или более поздний XML без официального
контракта идентификации. Все 499 members остаются evidence; импорт поднабора
из 498 записей запрещён. Причина `DUPLICATE_NOTICE_VERSION` сохраняется.

Каталог VPS:
`/var/lib/eis-browser/research/rejected/local-eis-supplier/s175-20261004T053757Z`.
SHA256 `capture.json`:
`81935ef6339a18e4738f68dc2410ee3fa9b74ac80c180b6d38c8a395960edff9`.
SHA256 `classification.json`:
`e9ff8a90696bda181a5a4ed1b2957eaea57feda66ea85491a94d8dc191b4801d`.
Полный inventory связывает member name, XML SHA, archive SHA, тип и business key.

S175 реализует ограниченное сохранение спорного набора и tenant audit.
Сохранение позволяет повторить разбор без новых запросов к ЕИС; само по себе
оно не исправляет конфликт и не увеличивает подтверждённое покрытие. Следующий
контракт должен установить, как ЕИС различает эти варианты одной версии.

## S175: проверка развёрнутого сохранения

Финальный offline replay реального набора выполнен на VPS 04.10 в06:07UTC
через deployed hook под общим lease. Сохранены все5ZIP (7 697 126 bytes),
manifest и один immutable tenant audit. Повтор сохранил первый timestamp,
не переписал файлы и не создал второй audit. Ноль source requests и ноль
изменений карточек, feed windows или attempts. Старый gap остаётся FAILED.

Manifest SHA256:
`62532f02f3021f6078de78bc7cd86cc7a323fac4af9426c6f77fffba872c8a2e`.
Proof `/var/lib/eis-browser/research/rejected/s175-retained-proof.json`, SHA:
`3a7de5da9c6a495e358a1effd47e7c13abf0703d493415a00fae3d27e7998c13`.

Gates:77Linux unit tests,20isolatedPG tests,Ruff/mypy и архитектурное review PASS.
Mode/file fsync и обе directory branches проверены до подтверждения RETAINED,
включая повтор после неудачной записи. Файлы+audit остаются двумя транзакциями;
при audit failure статус виден, повтор позволяет восстановить связь.
Schema HEAD прежний20261003_05, backups сохранены, production API/worker images
обновлены. Новые обычные sync failures используют этот hook автоматически.
Это не проверка следующей live выгрузки ЕИС: реальный источник вызван один раз
для capture, а новый deployed путь проверен на полном сохранённом наборе.
