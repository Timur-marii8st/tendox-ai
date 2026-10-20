# S192 — прохождение свежих окон ЕИС в поисковый индекс

Статус: DEPLOYED / VERIFIED BOUNDED INGESTION OBSERVATION. Owner root, 2026-10-05.
Контракт — [ADR0073](../adr/0073-eis-recent-ingestion-report.md).

## Использование

На VPS в каталоге проекта:

```bash
scripts/server-eis-ingestion-report.sh --first-day 2026-10-02 --last-day 2026-10-04
```

Один запуск проверяет максимум 1485 точных ключей: три завершённые даты MSK,
99 candidate codes и пять типов. Ключи берутся из `EisCorpusScope.batches()`;
DEFAULT EF сохраняет legacy форму без суффикса типа. Текущая незавершённая
дата, диапазон свыше трёх дней и обратные даты блокируются до подключения к БД.

Отчёт выполняется через API runtime в одном tenant repeatable-read/read-only
snapshot. Источник ЕИС не вызывается. На VPS создаётся immutable private JSON
с window metadata, domain scope digest, snapshot ID и checked_at. Консоль выводит
только 15 групп date/type и SHA256 файла. Source payloads/URL/credentials не входят
в отчёт. У каждого SQL statement timeout 30 s.

## Что измеряется

- Disjoint состояния окон: `CANONICAL`, `MISSING_PLAN`, `UNATTEMPTED`, `NO_DATA`
  и существующие категории gap policy для последней попытки.
- Canonical требует `LEGACY_CANONICAL` receipt. Транспорт и `SYNCED` без него
  не доказывают завершение. Последний сбой обновления не отменяет ранее сохранённый receipt.
- Число immutable notice versions и lexical-v1 записей с exact tenant/number/version join.
- Число отдельно сохранённых событий отмены и восстановления.
- Возраст планирования/последней попытки pending окон и lag первого canonical
  receipt относительно конца завершённой MSK даты; отрицательный lag выводится как 0.
- Между двумя снимками одного scope: первые попытки, смены latest attempt,
  переходы состояний, новые canonical receipts, регрессии и прирост индекса.

Возраст очереди не является обязательной SLA. Наличие lexical записи не проверяет
её содержимое или допуск карточки в конкретный запрос. NO_DATA остаётся gap:
он не доказывает отсутствие закупок или корректность/полноту ответа источника.
Число смен latest attempt не равно числу сетевых запросов.

## Baseline

Read-only snapshot 2026-10-05 06:49:46.521206 UTC; 2–4 октября:

| Показатель | Количество |
| --- | ---: |
| Ожидаемые / запланированные окна | 1485 / 1485 |
| Canonical | 374 |
| Последнее NO_DATA, без canonical | 1046 |
| Ещё без первой попытки | 65 |
| Сохранённые версии извещений / lexical rows | 6487 / 6487 |
| Сохранённые события | 177 |

65 unattempted находятся в EOK за 4 октября. Это определённый cohort,
а не вся национальная очередь или почасовые окна текущего дня.
У всех 6487 версий с origin в cohort есть lexical row; измеренная задержка
находится до этого этапа. Полнота источника/документов, national freshness и profit UNKNOWN.

Baseline proof на VPS:
`/var/lib/eis-browser/research/rejected/s192-ingestion-9b5a18e4-ae10-47ed-a47b-463b5c8984fa.json`.
SHA256 `87bbf41adb18a0e9745a6e506de9314688ec7a5835fe029e52c352d1e90210a9`.
Scope SHA256 `67f76af00ac93aa5eaa6c3656d7c1b2ab20476c324a9ea9a7c8d69ca8f8bd6d8`.
Предварительный 06:44 snapshot сделан до добавления canonical SHA в schema;
он не используется в окончательном typed comparison.

## Проверки и rollout

27 tests PASS локально и Linux network-disabled gate 06:50 UTC.
Проверены legacy EF keys, границы scope, disjoint состояния, canonical provenance,
NO_DATA/transport/SYNCED без ложного canonical, index deficit, будущие timestamps,
подмена tenant/digest/groups, comparison scope/time/regressions, exact SQL joins,
read-only/isolation refusal и private proof serialization. Ruff/mypy PASS.

Синтетические tests не выполняют source requests; live диагностика также source0/DBwrites0.
API/web/worker не требуют пересборки; scheduling/source budgets не меняются.
Rollout 06:53:46 UTC: два leaf scripts, один test и шесть документов, atomic9;
host23/API2 hashes PASS. Cron SHA
`012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f` сохранён.
Backup `/home/syurai/vibe-seller-state/backups/s192-before-20261005T065346Z-code.tar.gz`,
SHA256 `c01fdd4bac4cf5ad02ba40f46032afa055c74571505e15c1673dbfef5d96ab6c`.

Дополнительный read-only snapshot selector 06:57:45 UTC использует существующий
`eligible_windows(limit=60)` внутри того же tenant RR/read-only connection.
Выбрано 24 свежих EOK окна 4 октября и 36 исторических окон 4 сентября
(по девять EF/EZK/Cancel/CancelFailure). Это очередь на момент снимка, не доказательство
что следующий cron выполнит все 60: source/resource gates и preemption сохраняются.
Private proof `s192-selection.json` SHA256
`8a646e27640793bab33a8fedf6ffd1d77af6eb98c699c0b9c86c9019e053a63e`.
Диагностика source0/DBwrites0; selector не запускает source transport.

## Результат обычного cron

Тот же exact scope, 06:49:46–07:05:40 UTC, 954.432103 секунды:

| Показатель | До | После |
| --- | ---: | ---: |
| Canonical окна | 374 | 375 |
| NO_DATA без canonical | 1046 | 1069 |
| Без первой попытки | 65 | 41 |
| Версии / lexical rows | 6487 / 6487 | 6488 / 6488 |
| События | 177 | 177 |

24 новых первых попытки и 24 смены latest attempt; transitions:
`UNATTEMPTED->NO_DATA` 23, `UNATTEMPTED->CANONICAL` 1. Canonical regressions 0.
Новая версия и её lexical row появились вместе; в измеренном cohort index deficit 0.
Нельзя приписывать весь прирост единственному cron run: интервал включает окончание
прохода, начатого до baseline, и очередной плановый проход. Нет ручного source dispatch.

Final private proof `s192-ingestion-1385f68a-dd7b-42de-9416-39b79ae71db5.json`:
SHA256 `494ee19317710e29553bf2d69683659bfcbd31951d90d439e0706a57f4f247f2`.
Typed progress proof `s192-progress-c8d2d0f1-8704-4895-9006-471845548efd.json`:
SHA256 `476eb17a13cdf70df88e51f59f451eb17c1f051673322a198e49619004223ef6`.
Intermediate 07:01:45 snapshot/progress сохранены, но не заменяют final comparison.

Общий lease observer S190 повторно использован с тем же окончательным горизонтом:
23 runs (corpus2/priority3/documents16/223two), complete21/censored2, boundary1,
inconsistent0. Неполные интервалы остаются UNKNOWN. Held union lower bound
115.166305 s; whole intersecting work known2 суммарно399.792464013 s включает
работу до baseline, поэтому эти числа нельзя делить для оценки национальной мощности.
Known wait max2.220890754 s. ERROR1 — operational exit, не доказательство source fault.
Private `s192-lease-final-observation.json` SHA256
`5c8d9f1d73273f1f257a43f83e75350b01544ab11208212df2434c51b8dd1d38`.
Дополнительный lease horizon 06:45–07:01 сохранён отдельно, не смешивается с final.
Первый вызов observer для промежуточного 718s horizon был корректно отклонён
существующим минимальным15min контрактом; production reporter/comparison не менялись.

## Вывод для следующего среза

Измеренный источник задержки — первая попытка свежих окон и результаты источника,
а не отсутствие lexical rows у сохранённых версий. Следующий этап должен уменьшить
возраст свежего backlog при сохранении прогресса истории и действующих source gates.
Отдельно нужен контролируемый bounded повтор точно выбранных NO_DATA окон
по существующей retry policy с сохранением original attempts/source hashes.
Один 15min sample не определяет capacity/SLA; 1069 NO_DATA не становятся canonical
и не доказывают отсутствие закупок. Full EIS, current-day national hourly scope,
все документы и прибыльность остаются UNKNOWN.

## Итоговая проверка VPS

07:07:59 UTC: host23/API2 hashes PASS, API/web image IDs и worker12charprefix
сохранены, HEAD `20261004_03`, API health200, OOMfalse. API1GiB/web768MiB;
БД3 970 284 567bytes, free258 939 768 832bytes, testDBnone. Priority marker true
отражает обычный активный cron; чужие markers не удалялись. Source/DB budgets
и cron SHA остались прежними. Эти значения относятся к отдельному ops snapshot,
а не к окончательному cohort report07:05:40.

Ops proof `s192-operations-proof.json` SHA256
`e1bb4ded2779fc576e8f9c8c71bc0bd10ba014519ca14e0b95ddded53c09ebad`.
Docs backup `/home/syurai/vibe-seller-state/backups/s192-before-20261005T070758Z-docs.tar.gz`
SHA256 `f0b628b5e69a0f26ace76c79bf05b9cee297025f8d9263c5358d1e0a3f05a19a`.
Receipt additions включены в заключительный docs-only hash seal; runtime bytes
не менялись после27 LinuxPASS.
