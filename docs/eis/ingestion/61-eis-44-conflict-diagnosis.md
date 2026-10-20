# S177: диагностика конфликтов 44-ФЗ

Статус: **DEPLOYED 04.10.2026, 07:49 UTC**. Контракт — [ADR0060](../../adr/0060-eis-44-conflict-diagnosis.md),
официальные источники — [исследование версий](60-eis-44-version-contract-research.md).

## Поведение

После отказа импорта полный набор сохраняется в карантине S175. Только после
успешного retention audit запускается offline диагностика. Она описывает каждый
XML member, его ZIP/XML SHA, исходный документ и проверенные временные поля.
Повторы одной пары purchaseNumber/versionNumber классифицируются по точным
байтам; source identity дополнительно сравнивает тип и прямой идентификатор ЕИС.
Отсутствующий или некорректный идентификатор даёт UNKNOWN.

Полный inventory не является приёмом окна. Импорт сохраняет исходный FAILED,
поиск не получает выбранного по времени XML, новые checkpoints не создаются.
Для межоконного DB conflict диагноз локального набора может не содержать
повторов: это не опровергает конфликт с уже сохранённой версией.

Отдельный неизменяемый tenant audit связывает отчёт с exact retained manifest,
source response/window и упорядоченными SHA всех ZIP. Повтор того же набора
проверяет hash и binding, сохраняя один audit. Ошибка диагностики или её audit
не заменяет исходную причину отказа. Corpus получает только aggregate counts,
UNKNOWN и SHA отчёта; freshness — SHA и audit status. Поля XML, имена файлов,
даты и IDs не отражаются в summary или тексте ошибки.

## Проверки и границы

Общие ресурсные пределы S175 сохранены; дополнительно ограничены суммарное
число members (2000), имя файла (255 символов) и размер сериализованного отчёта
(2 MiB canonical JSON). Все ZIP headers проверяются
до XML parse. Identity требует ожидаемого namespace, уникального прямого
элемента и допустимого типа. DTD/entity, неоднозначные поля, отражение токена
и небезопасные member paths отклоняются. XML — UTF-8, с проверкой NUL/declaration/BOM.
Во время построения дерева действуют пределы 50 000 nodes и depth128 на XML;
они применяются и при сравнении. Все resource failures оставляют original FAILED.

`non_timing_sha256` относится к ET-сериализованной структуре с текстом двух
точных временных полей, заменённым пустой строкой. Это не raw-byte canonical
equivalence и не доказательство взаимозаменяемости документов. Полная raw
XML SHA сохраняется отдельно. `difference_category_count` считает категории
publication/start/other, а не все изменённые leaf fields.

Retained source sample: 5 ZIP, 499 XML, 498 пар номера/версии. Одинаковый id
44105096 не разрешает два XML закупки0373100047426001450: различаются времена
публикации и начала подачи заявок. Более поздний вариант не объявляется верным.
Этот slice не подтверждает полный охват ЕИС или готовность экономики.

## Release gates 04.10.2026

158 Linux unit tests, 22 isolated PostgreSQL tests, Ruff/mypy пяти runtime files
и независимый architecture review PASS. Проверены обход кодировки, DTD/entity,
decoded reflection, namespace/leaf/multiplicity, memory bounds, forged rehashed
groups, tenant RLS, audit immutability, replay и отсутствие checkpoint при отказе.
Тестовая БД: `procurement_eis_test_20261004_s177`; production tests не запускались.
Тестовая БД удалена после завершения release gates и rollout.

Exact retained full path + replay с resident blank Chromium при cgroup2GiB:
5 ZIP, 499 occurrences, 1 divergent pair с одинаковой identity, report338074bytes.
Peak379813888bytes (~362MiB), Python maxRSS236920832bytes; всего13.154s.
Это offline reject hook и повтор по сохранённым данным, не online search SLA.
Source requests0, index/checkpoint/attempt delta0, replay file writes0.
Diagnosis SHA `5ca4af5206ba669f257891dba79d19dfa0c64ad5253a8c94f6c70b685c494805`.
Isolated proof `/var/lib/eis-browser/research/rejected/s177-isolated-proof.json`,
SHA `d48b8212ca502b65e0c4a2aa6df542e12e5d0f2a829cffebc74499e655bb261a`.

## Deployment и production proof

Перед rollout сохранён code backup. Host18/API5 scoped hashes совпали,
API и worker images пересобраны; schema HEAD20261004_01 не менялся.
Production hook обработал тот же полный source set: один новый immutable
diagnosis audit, retention audit delta0; replay не пишет файлов или audit.
Index/checkpoint/attempt delta0, source requests0. Исходный44 gap остаётся FAILED.
Диагноз и его SHA точно совпадают с isolated run. Время full hook+replay13.387s,
peak382709760bytes (~365MiB) при2GiB с resident blank Chromium.
Proof `/var/lib/eis-browser/research/rejected/s177-retained-proof.json`, SHA
`9c2a7f76e1380fc1e642bcaca2ac5b2f0231702ff711460166b76f75d4462450`.

Final API: health200/anonymous401, coverage no-store, оба demand markers сняты.
Индекс223 содержит2880 текущих номеров закупок (фоновое обновление продолжалось).
Cached search бумага241.87ms/59matches, серверное оборудование585.35ms/184matches.
Это поиск по накопленному индексу; coverage/freshness всейЕИС остаются UNKNOWN.
Proof `/var/lib/eis-browser/research/regions/s177-final-api-20261004T075010Z.json`, SHA
`1172540c529d979a29e5665a27335700c2ab8a9d6a604c549343528c52acb59d`.
