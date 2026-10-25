# Адресное восстановление офисной бумаги на 3,23 млн ₽

24.10.2026, Europe/Moscow. Owner root, один агент.
Контрольный номер: `0122100003226000063`, tenant `local-eis-supplier`.
Основание — [сверка126](126-eis-paper-parity.md), разрешение пользователя «давай»
на следующий срез. Контракты: [официальный источник](../../adr/0044-eis-source-contract.md),
[адресное восстановление](../ingestion/84-eis-public-candidate-recovery.md).

Owned files: этот отчёт, search README, приоритет ЕИС live-плана и private evidence
`tmp/eis-paper-recovery-20261024-v36/`. Зависимости: источник, import lease,
установленный образ `7e2b52074aa5842ac39cd862240dea0b6af803c8b4bfd0e93153f8e6a06caa81`.
Это более новый runtime, чем при сверке126; его развёртывание не относится к этому срезу.
Acceptance: полный связанный набор проходит installed admission; закупка находится
по «бумага» через HTTP с ценой, aware deadline, исходным XML SHA и ссылкой ЕИС;
tenant audit/readback подтверждены. Национальная полнота не входит в этот PASS.

## Источник и запись

Перед началом canonical versions0: tenant-scoped PostgreSQL read-only/RLS on,
statement timeout5s, snapshot436107:436107:,23Oct21:55:23UTC.
Первое ожидание import lease55s завершилось exit75/source calls0. Второе ожидание
ограничено300s; источник получен штатным capture-only reader за20.755s.
Один ZIP11509B, один XML `epNotificationEF2020`, редакция1. Набор не фильтровался.

| Факт | Подтверждение |
| --- | --- |
| Предмет | Поставка бумаги для офисной техники |
| Цена | Decimal `3230328.80` RUB |
| Окончание подачи | `2026-11-27T09:00:00+10:00` из официального XML |
| ZIP SHA256 | `625a40c4cb2b4006c13d7e93330d108d4a081144bf75b59c60c56c88e5215710` |
| XML SHA256 | `bc7b2fde72f383b22d2b10e2aa29a0273a44cb3eb2a14d95fe99599dfe55ddec` |
| Stock manifest | `e0ea3b973961efe00bd831f4ae1d8e662571e9ecf537abf95b8ddd95b1c0b437` |

Initial/prepared SOAP, полный ZIP и capture proof сохранены с SHA. Installed
`bind_ready_window` и `preflight_ready_window` подтвердили привязку, полный набор,
поддержанный формат и номер; конфликтов с existing versions0. Отдельная XSD
валидация не запускалась; это штатный parser admission, не новый schema receipt.

Для вызова использован ограниченный adapter `intake.py`: существующий S201 CLI
требует другой входной NO_DATA report, а S202 фиксирует три исторических номера.
Adapter только связывает сохранённый capture с installed APIs; parser/проверки
не подменяет. Preview предшествует apply с точным manifest SHA. Intake проходит
под shared import lease в отдельном worker; network requests0 при preview/apply.

`ingest_ready_window` записал1новую редакцию,0events, lexical version1 и audit
`0257761c-15a6-471e-949a-7b185fd99d15` от `operator-paper-recovery-v36`.
Readback подтвердил XML SHA, latest source usable и привязку audit к manifest.
Свободно43 924 275 200B при резерве40GiB; DB22 472 588 311B при лимите100GiB.
Окно `getDocsIP/PRIZ/by-number/0122100003226000063` не означает завершение
исторического суточного окна27/22June. Исторические receipts не менялись.

## Проверка пользовательского результата

24Oct00:58:54МСК: HTTP200, `/v1/tender-discovery/global-price`, query=«бумага»,
page_size100, регион не ограничен. Целевой номер найден в первой сотне, цена
`3230328.80`, XML SHA совпал, официальный URL содержит точный номер. API deadline
`2026-11-26T23:00:00Z` эквивалентен27Nov09:00+10:00 и не истёк.
Application status и corpus coverage остаются UNKNOWN. Ответ22.961s,1863matches;
изменение общего счётчика не приписывается одному импорту: фоновые задачи работали.
Проверен HTTP API; браузерный UI отдельно не проверялся. Срез восстановления
одного номера принят; задержка поиска23s этим срезом не исправлена.

## Границы и продолжение

Source coverage — один номер, национальная полнота/устойчивая свежесть UNKNOWN.
Новая конфигурация загрузки, расписание, parser и runtime этим срезом не выпускались.
Документы ТЗ не скачивались; технический/экономический допуск и PARTICIPATE UNKNOWN.

Следующий срез — обработка подтверждённых пропущенных интервалов свежего потока,
сначала Москва23Oct14–15h и сверка №0373100103926000241/0373200032226000812.
Регулярное обновление KESMBO/ZPESMBO остаётся отдельным незавершённым этапом.
Evidence и SHA всех файлов — `tmp/eis-paper-recovery-20261024-v36/evidence-manifest.json`.
