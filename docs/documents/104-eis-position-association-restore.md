# S222: восстановление сохранённой связи позиции

Статус 2026-10-06: завершён и установлен на VPS. Зависимость: sealed S221.

## Контракт

Точная позиция, документ и `eis-native-review-v1` задают scope. Источники,
актуальность версии, hold и tenant проверяются при чтении. Список содержит до
20 metadata-записей: ID, время, автора, количество фрагментов/символов. Порядок
стабилен по времени и UUID по убыванию. Текущий evidence basis (позиция, анализ,
receipt/time) фильтруется до pagination: старое получение того же SHA не блокирует
новые связи. Такие исторические ID/cursor не восстанавливаются как текущие.
Cursor связан с существующей записью
в том же scope. Отдельный detail по scope + ID восстанавливает полный report
из immutable источника; клиенту не нужно повторять диапазоны или передавать текст.
Новые записи, загрузки, анализы и задания не создаются. Миграция не нужна.

## Интерфейс

В подготовленном DOCX выбрать позицию и «Открыть список сохранённых связей».
Кнопка «Открыть эту связь» восстанавливает выбранные фрагменты и их источники.
Связь не выбирается автоматически. Следующая страница ограничена тем же scope;
изменение позиции/документа или ошибка сбрасывает старый report. Сохранение нового
выбора требует отдельной явной кнопки S221.

Операторская связь по-прежнему не утверждает требования, полноту ТЗ,
соответствие товара, КП или участие: **UNKNOWN**. Нормализация выбранного текста
в проект требований выполняется следующим отдельным этапом.

## Проверки

Owned files и acceptance зафиксированы в docs15. Итоговые 197 Python/API/
isolatedPG tests PASS45.90s, без skips; Node55/TypeScript/ESLint/production build
и независимый high-risk review PASS. Проверены tied timestamps/pagination,
foreign cursor/ID, source SHA/revision/receipt/tenant/current/hold, подмена
текста и report SHA. Регрессия same-SHA re-receipt подтверждает: историческая
связь не блокирует новые страницы, старые detail ID/cursor не становятся текущими.

Backend09:39:03UTC/web09:39:12UTC, schema прежняя `20261006_03`, host185/
API36/worker36/web47 hashes совпали. В реальной notice `0107300009526000178` v2,
position1, document UID `01A0E7C8E19477C8A507A0C39F6BCCFF` открыты две разные
связи: S221 blocks1+32/61characters и новый явно выбранный block1/51characters.
Для проверки второго выбора создана ровно 1 дополнительная association и 1
audit event; list/detail сами не пишут. Список в 2 страницах limit1:142/146ms,
полный список150ms; detail137/149ms. Installed NextAction list188/147ms,
detail217/145ms, compiled SSR сохраняет текст и UNKNOWN. Detail-запросы не
содержат фрагменты или клиентский текст. API10/NextAction6 negative cases PASS.
Проверка открывает оба exact ID и новый список из пустого request state;
визуальная проверка браузера **NOT_PERFORMED**.

Все чтения source0/jobs0/writes0. Исходный файл остаётся обоснованием цены:
связанные строки не становятся approved requirements, полным ТЗ или КП.
Ops09:39:17UTC: DB5682658327bytes/free251283402752bytes, test DB0/health200/
markersfalse. Cron SHA, source budgets и работающие intake workers не менялись.

## Evidence и rollback

Приватные proofs остаются на VPS в `/var/lib/eis-browser/research/rejected/`
и `/home/syurai/vibe-seller-state/`.

| Evidence | SHA256 |
|---|---|
| `s222-pg-gates.log` | `96ca1c541442c8ba8932be837c6d34e41888edc5cc16f393873a30f6b1f2b84e` |
| `s222-web-build.log` | `95af30c080feab73ef0eebf725b771e5a75c4461ad624471f95c7a6cf0679993` |
| `s222-final-restore-live-proof.json` | `72b9e62ef60620b51385f5e7219220cb94820171d71a7f3a816e34ae20c09d47` |
| `s222-final-restore-web-proof.json` | `c0e0d32cb9d078a60b2669a47397333f2f4717bc794ae37fd4fca5d0413eb2ab` |
| `s222-final-operations-proof.json` | `568f585ef2fa7ba2ce49c269bbb85c0e3a7bb9b43318ef39bdb33bcea3890805` |

Installed image pins:

- API `sha256:d6cf44e2c221c833fa1b9a3192bd564b416d7e55094db11a4fe3152c0abbef45`.
- Worker `sha256:79f1fcde0a58ec74fac6ecba453468723c881bdeb373a6f4c42aa963c60bdd90`.
- Web `sha256:16e34d933a8f12cfd43c0b5b27a01400cc174fb2e6b1316f5702555230fd909e`.

Code backup `s222-before-20261006T093857Z-code.tar.gz`, SHA
`756f1999c2ce466408a230204979dc5f53ba26fa53fc8e2cb9e65c301e7f419e`;
web backup `s222-before-20261006T093909Z-web.tar.gz`, SHA
`0a39c6e091b0ee5326e59c632e9a73b053e2d4516612e63b21546f6a72abf8e1`.
Rollback возвращает S221 images/owned files; schema03 и immutable links/audit
сохраняются. Release gate связывает PASS197/zero skips и log digest с точными
tested src/tests hashes, поэтому изменение кода после проверки блокирует установку.
