# S221: связь позиции ЕИС с сохранёнными фрагментами DOCX

Статус 2026-10-06: завершён и установлен на VPS. Зависимости: S219/S220.

## Контракт

Оператор выбирает exact позицию и видимые фрагменты DOCX, включая разные
страницы. В запросе только notice/version/XML SHA, source_index, attachment
UID/document SHA, `eis-native-review-v1` и ordered ranges block/start/end.
До 10 непересекающихся диапазонов, суммарно до 16000 Unicode characters.
Текст и locator от клиента не принимаются: они извлекаются из проверенного
сохранённого анализа на сервере. Файл и сеть не перечитываются.

Одна immutable запись содержит digest позиции, canonical digest полного
анализа, отдельный SHA исходного документа, точные выбранные строки, исходные
локаторы с character range, receipt/time/revision и автора. Forced tenant RLS,
append-only/audit/replay; latest/hold/receipt/exact source проверяются на save
и read. Replay и read восстанавливают report по текущему immutable source,
включая текст и provenance. Приватные ошибки/DSN не выдаются пользователю.

Статус связи **OPERATOR_LINKED**. Полнота body-only DOCX и всего ТЗ,
утверждённость требований, соответствие товара, КП и участие **UNKNOWN**.
Это исходный контекст для будущей нормализации требований и RFQ; выделенные
фрагменты не объявляются полной спецификацией.

## Интерфейс

В карточке открыть «Связать с карточкой и расчётом», затем подготовленный DOCX.
Выбрать позицию и checkbox у нужных видимых блоков; выбор сохраняется между
страницами. Явная кнопка подтверждает и сохраняет связь. Рядом доступны exact
фрагменты/источники и поиск снабжения S220 по той же позиции. Изменение выбора,
ошибка, переключение exact документа или unmount не оставляют старый report
под новым выбором. До сохранения не выполняется автоматическая загрузка каталога.

## Проверки

Owned files и milestones зафиксированы в docs15. Итоговый gate: 189 Python/
isolated PostgreSQL/API tests PASS за 43.27s, без skips; Node51, TypeScript,
ESLint, production build и независимый high-risk review PASS. Проверены tenant
RLS, append-only, current/hold, source SHA/receipt, некорректные диапазоны,
подмена текста/locator, лимиты, конкуренция и повтор. Save захватывает тот же
tenant advisory lease, что и импорт, **до** writable repeatable-read snapshot;
занятый lease возвращает 409 без записи. Read использует source0 read-only
snapshot. Сохранённый report реконструируется из источника: изменение текста
с пересчитанным SHA не принимается.

Установка: backend 08:19:13UTC, web 08:19:16UTC, schema `20261006_03`.
Host182/API36/worker36/web46 hashes совпали. На реальной позиции 1
«Бумага для офисной техники», notice `0107300009526000178` v2, выбран контекст
из блоков 1 и 32 сохранённого DOCX (две страницы). Это **обоснование цены**:
строка объекта закупки и сумма `112 950,00`; документ не объявлен полным ТЗ,
сумма не перенесена в закупочную стоимость или КП. Сохранены 2 фрагмента / 61
Unicode character, 1 immutable association и 1 audit event. Первый API save
198ms, replay160ms, read133ms; installed NextAction read186ms/save148ms.
Все операции source0/jobs0. API10 и NextAction6 negative cases PASS.
Визуальный осмотр браузера **NOT_PERFORMED**; проверены реальные installed
Server Actions и compiled SSR.

Регрессии после установки: исходный DOCX33blocks/1732chars прочитан losslessly
за 2 страницы81/76ms, public supplier cache8leads read128ms, replay1581ms/source0;
6 characteristic reads143–209ms и 3 analog queries1251–1531ms PASS. Негативные
проверки источников/tenant/индексов сохранены. Refresh каталога не выполнялся.

Ops08:19:34UTC: DB5574859799bytes/free251540631552bytes, test DB0, health200,
markersfalse. Cron SHA и source budgets прежние. Для открытия связи после
перезагрузки пока нужно выбрать те же диапазоны; список сохранённых связей
и восстановление выбора — следующий отдельный срез.

## Evidence выпуска

Приватные JSON остаются на VPS в `/var/lib/eis-browser/research/rejected/`
и `/home/syurai/vibe-seller-state/`; документы/архивы ЕИС на ноутбук не скачивались.

| Evidence | SHA256 |
|---|---|
| `s221-pg-gates.log` | `e6e69f6ecb1e207d416956008fa54978631e30c59717ec61665dac146c049b62` |
| production build log | `28f8e49fff2e43b167ef495fe9e9ea83a2cf6b3a338929bb14dd9947df5556a4` |
| `s221-final-association-live-proof.json` | `c782e8ea291e6520596119a155cde7bea8937c0611444d4b4cecb7036cf773e9` |
| `s221-final-association-web-proof.json` | `f9374d86f38b8c17e27eab11f3ef8ae6a5d5b898121c155a6c0d8ecbd7a4e7fa` |
| `s221-docx-final-review-web-proof.json` | `ee68ce37c24f7d879380d18b96394a2e2eba32cd99cef28a0a6ad8422c0998d6` |
| `s221-final-supplier-web-proof.json` | `98d20333d6431beec44bb2aca4432f0002d470261337000b9e46a0611c16987f` |
| `s221-web-final-proof.json` | `668402a1b49325cd828da29a068c76dc44091c5080fc766be201d2e3f2cd6d64` |
| `s221-final-operations-proof.json` | `6af495a1592b441e764b716fc0b9f080fe9e14bddd4e1f954328da53db5b9c23` |

Installed image pins:

- API `sha256:a09e4a4f8be452b0d4f7ba08e15bf8a8959cb1058eea5048e5856c6cb1fd3928`.
- Worker `sha256:717d65b99fb0b90af09e8ad21d486747d864facd9fda0b068513145387063aa6`.
- Web `sha256:575e8b7aa8bcc1c973140132a36af12d01a71e5e8dbb93b480530578df561389`.

Code backup `s221-before-20261006T081905Z-code.tar.gz`, SHA
`c474271981872fb89e278859852b379a2ff42b3338e52df8d6b3cf09c738659c`;
web backup `s221-before-20261006T081914Z-web.tar.gz`, SHA
`fc55324fdaf64ddc2f38246159f14807576cd7b06fabf654e5bac3b031a72ebf`.
Rollback возвращает S220 images/owned files, оставляя совместимую additive
схему03 и immutable evidence; удаление данных ради downgrade запрещено.

## Совместимость установки

S221 добавляет source0 API и отдельную таблицу; парсеры, intake-контракты, cron
и лимиты загрузок не меняются. Установка сериализуется через
`vibe-seller-state/backend-deploy.lock`, затем web deployment lock. Миграция
выполняется до переключения API с lock timeout 5s / statement timeout 60s.
Старые работающие worker images совместимы с additive schema и продолжают
импорт. Deployment не захватывает dispatch/import leases и не создаёт priority
marker; он не пересоздаёт работающие загрузчики. При занятой DDL-блокировке
миграция откатывается; повтор установки не требует остановки загрузки ЕИС.
Source0 live proof считает только собственные association/audit rows, поскольку
обычная фоновая загрузка может одновременно менять общий объём индекса.
