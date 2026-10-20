# S220: источники снабжения из одной позиции ЕИС

Статус 2026-10-06: **завершён и установлен на VPS в указанных границах**. Отдельный этап после S219;
публичное ценовое наблюдение ещё не является закупочным КП или себестоимостью.

## Контракт

- Exact tenant + номер/версия/XML SHA + source_index позиции. Общий bounded
  single-position reader сохраняет поведение исторического сравнения; supplier
  flow отдельно требует latest known version и отсутствие source hold.
- Запрос категории выводится детерминированно из наименования: `dl360`, `dl380`,
  `hpe`. Для общего наименования «Сервер» выбирается бренд категории HPE
  как направление предварительного поиска; бренд не извлекается из ТЗ. Явно неподдержанный бренд/поколение, отсутствующее или
  слишком длинное название дают QUERY_NOT_COVERED без HTTP. Это предварительная
  маршрутизация одной категории, без подтверждения характеристик или всего ТЗ.
  Ремонт серверной комнаты, услуги, аренда и лицензии не маршрутизируются как
  покупка серверного оборудования. Этот случай найден на реальной карточке
  и добавлен в negative gates до выпуска.
- Один фиксированный GET категории ServerMall HPE ProLiant Gen12, до 2MiB,
  до 50 исходных карточек/10 результатов. URL из внешнего текста не становится
  сетевой командой; переходы на товары/redirects/обход защит не выполняются.
- HTML сохраняется неизменяемо на VPS с SHA/time/bytes. Цена — только Decimal,
  с raw label и exact locator внутри этого снимка. BASE_PRICE_FROM, PRICE_FROM и
  LEASE_MONTHLY различаются. НДС, полная комплектация, наличие, доставка,
  соответствие требованиям, КП, прибыль и участие остаются UNKNOWN.
- STARTED сохраняется **перед** HTTP, final outcome отдельной immutable записью.
  После timeout/kill последний исход остаётся незавершённым; старые предложения
  не выдаются за результат новой попытки. SOURCE_ERROR тоже сохраняется явно.
- Ключ включает policy + digest полного SavedPosition. Current/hold/basis
  проверяются до GET и перед append; при изменении источника финальная запись
  блокируется. Source I/O не держит DB transaction или широкий tenant import lock.
  Per-search session lease предотвращает конкурентный GET; short tenant lock
  используется только при сохранении. Refresh явный, интервал 15 минут.
- Source0 read/replay проверяет latest/hold/exact basis/digest/typed result и
  byte sizes до hydration. Источник HTML при обычном чтении не гидратируется.
  RLS forced; update/delete запрещены. HTML SHA проверяется PostgreSQL на insert.

## Пользовательский путь

Карточка ЕИС → «Связать с карточкой и расчётом» → позиции → «Найти поставщиков».
Отдельные кнопки открывают сохранённую попытку и явно обновляют источник.
Автоматического обхода рынка, отправки RFQ и допуска нет. Привязка DOCX к позиции
и reviewed requirement set — следующий этап; S219 body-only текст не становится ТЗ.

## Проверки и выпуск

Финальные 150 PostgreSQL/source/API/runner/pair/range/hold tests PASS, 24.82s,
07:45:41UTC, без пропусков. Gate log SHA
`ab3e876f06b3128d402588835af2bf11d04665e7e6dc5bdab7e1e74244908a2b`.
Node supplier wire/render 6 + DOCX 8 + characteristics 13 + analogs 11 + protocols 8,
TypeScript/ESLint/production build PASS. Build 07:42:29UTC, log SHA
`683e72354ccf351d43ee6f517207403d8cfab287bff4da69497cfd102b67bb37`.
Independent read-only review PASS: обнаруженный base/monthly overlap исправлен
и покрыт отдельным regression; месячный платёж не становится ценой оборудования.
Первый final gate остановился на устаревшей synthetic fixture; после её приведения
к реальным exact markers полный gate выполнен снова. Ошибки не скрыты.

Реальный HTML 606189bytes/SHA
`3a5db3385d6e7658531753496d0c2701cb64c394db3865830ccc43faad703df6`
исследован offline: 8 карточек, 5 BASE_PRICE_FROM, 2 PRICE_FROM и 7 LEASE_MONTHLY;
скрытая цена восьмой карточки DL580 UNKNOWN. Evidence на VPS:
`/var/lib/eis-browser/research/rejected/s220-frozen-source-offline-proof.json`, SHA
`1e351aa594faddd6a229bbfb9ec62898fa2d22efcb7ae49b6704223497c17558`.
Receipt mtime здесь не объявляется original fetch time.

Installed live 07:47:08UTC: позиция 1 «Сервер», закупка `0133200001726002460`,
v2/XML SHA `c5c9152a7c8012e9da62e33382ec79ca81c1477d5736ca189bdfcdc906de632a`.
Prepare **2236ms**, один GET, 8/8/8 карточек и 14 ценовых наблюдений;
две immutable записи STARTED/final и два audit events. Replay prepare 1513ms,
отдельный read **95ms**, оба source0; jobs0. Восемь HTTP negative gates PASS,
включая auth/no-store, tenant, SHA, strict bool, duplicate/oversized JSON,
refresh cooldown409. Реальный ремонт серверной комнаты QUERY_NOT_COVERED/source0.
Proof `/var/lib/eis-browser/research/rejected/s220-final-supplier-live-proof.json`,
SHA `4c849ade902f8b642f23b884d7f56dce7c5f627602dc3d098978beb3c94227c6`.

Installed NextAction + compiled SSR 07:47:12UTC: read **132ms**, cached prepare
1533ms, 8 предложений, 5 negative gates, source0/jobs0. Proof в server state
`s220-final-supplier-web-proof.json`, SHA
`bdc01fa16e23e586ff60c7be3e9dfb050211d66c44a5f86330cc93be64a0aa74`.
Browser visual check **NOT_PERFORMED**. Сохранённый DOCX повторно прочитан:
33 блока/1732 символа, две страницы 84/76ms, source0; characteristics API/direct
и 3 historical analogs + SSR/negative regression PASS.

## Установленная версия и операции

Backend 07:46:51UTC, web 07:47:00UTC, schema `20261006_02`.
Manifest host166/API33/worker33/web39; все hashes совпали.

- API `sha256:65c5115c97489c3d45eb32e611ddec26c7237f2b0e3214623f86f2aa856831ca`.
- Worker `sha256:9b09555930de2a6ab5867b228eed8e5f787fff208c3b2f8e0ab432a008436ad7`.
- Web `sha256:51d35e0336929f46dbfb94ff2623155f161846879dc5e048d7cf2064a59c9a46`.

Ops 07:47:30UTC: DB5551791127bytes/free251641643008bytes,
testDB0/health200/markersfalse/API1GiB/web768MiB/noOOM. Cron SHA
`012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`,
source corpus/223/docs/priority budgets неизменны. Ops proof SHA
`9e8b95bbe3264e2837ea0ff0132a26c419b8f1e77b39a0a836083de6c8e3b418`.
Ноутбук не хранит массив ЕИС; HTML snapshot остаётся на VPS.

Перед release сохранены code backup SHA
`0f43e3cf50f0750d8736eb611b7fdddb8c4ac391c6fa1917ec0878e795a847b6`
и web backup SHA `80570b448b2381a4748dbf478b9cfe035c06b9c2a662a0f41b4b0084d82db033`
в `/home/syurai/vibe-seller-state/backups/s220-before-20261006T074643Z-code.tar.gz`
и `...T074657Z-web.tar.gz`. Rollback к pinned S219 API/worker/web допустим с
forward-compatible additive schema; историю supplier evidence не удалять.

## Следующие шаги

Добавлять другие категории и поставщиков только с их отдельными проверенными
адаптерами и измеренными лимитами. Затем сопоставить конкретную комплектацию
с reviewed требованиями, подготовить RFQ, получить действительное полное КП,
рассчитать base/realistic/conservative и только тогда принять решение об участии.
