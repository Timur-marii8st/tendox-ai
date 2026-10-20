# S215 — неподдерживаемый диапазон не отбрасывает архив

Статус: завершено, 2026-10-06. Измеренный блокер: 27 окон за 3–5 октября
завершились `CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED` (S214 census).

## Контракт

Неподдерживаемая/неоднозначная структура rangeSet/valueRange сохраняет карточку,
названия, суммы, вложения и exact XML provenance. Частичные границы не утверждаются:
min/max/raw/operators None, range_source_complete false, strict source marker
range_structure_unknown true. Пустой valueRange также неоднозначен.
Malformed numeric scalar в распознанной структуре сохраняет raw и остаётся UNKNOWN.
Ошибки XML, идентичности, вложений и других дублирующихся контейнеров неизменны.

Если хотя бы одно значение содержит этот marker, characteristics_status всей
его позиции UNKNOWN. Это консервативно блокирует наблюдения SAME/DIFFERENT,
включая сочетание с qualityDescription/concrete_values; другие позиции сохраняются.
Отдельный wire marker не нужен: существующий position status уже выражает gate.
Новую проекцию создаёт только r2; чтение r2 > r1 > исходная v3 > v2,
без изменения старых payloads и без fallback при повреждении предпочтительной версии.
Старый exact error классифицируется PARSER_REVIEW, не source retry или canonical.

## Проверка

Тесты проверяют неоднозначные формы, mixed archive, strict marker, смешанные
значения через saved fields и immutable projection, старые версии, tenant/SHA/holds,
replay, bounds и source0 сравнение. Бюджеты источника и памяти не увеличиваются.
142 локальных и 398 изолированных PG/unit/API тестов PASS (38.94s, без skips),
Ruff и Astra review PASS. PG log SHA256:
`79eefa4a51f5e1dcc7855d465058dbf6c4b710ed511f5247d9ac1c9b2f5159c8`.

Backend-only deployment 05:39:48UTC: atomic13, host122/API24/worker24 hashes PASS.
Без миграций, изменения зависимостей, cron и бюджетов памяти/источника.
API image `sha256:29ff2c93d25ba7e3007fb90e2c342da6d4f7c2fabdf3ba7002b0e38df30cc378`;
worker `sha256:25673b2f99e2672361eb98649b4720aacc0b3aabc610e5b01818fd65eec243be`.
Web остаётся S213. Backup:
`/home/syurai/vibe-seller-state/backups/s215-before-20261006T053943Z-code.tar.gz`,
SHA256 `48c06ddbdb742fd7097d706abd3910b48346a11ed25deef0618ebe8a2cab8658`.

## Проверка на реальном источнике

Один ограниченный повтор окна `getDocsIP/PRIZ/16/2026-10-05+03:00` завершился
SYNCED 05:40:29UTC за 11.171s: 2 SOAP POST, 2 archive GET, два ZIP (1622611 bytes),
123 новые версии карточек. Старый замороженный парсер на тех же байтах снова
выдал `CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED` для одного архива; второй
распознал. Это проверка причины ошибки, а не дополнительный сетевой запрос.
Прежние 27 записи попыток сохранены, новый journal/audit append-only.

Независимая read-only проверка 05:46:21UTC: 123 версии = 123 lexical rows;
одна карточка содержит явный ambiguous-range marker. Canonical checkpoint:
два архива/123 карточки, новые journal/audit и response SHA согласованы.
Источник SHA256 `664978d528e3ac10c8c744134018912daeb51d08d4cfb7e51200d2dd8ae3d07b`.
Private proofs в `/var/lib/eis-browser/research/rejected/`:

- `s215-one-window-live-proof.json`, SHA256 `7bdd3daf7957d39d622bf9f8ac9e384b419604e76bf2824f41532afa999fbd9c`.
- `s215-one-window-verification-proof.json`, SHA256 `67576cc64c3e5dc1c8c346972c7a90106e06eeed81a3d5a7e20b247ebd10f633`.

Шесть installed API/direct сравнений PASS (HTTP80–238/direct78–234ms), шесть
негативных проверок; Next Action/compiled SSR шесть чтений86–178ms, пять
негативных PASS. Browser visual NOT_PERFORMED. Старые проекции читаются без
массового переписывания. Analog regression остаётся BLOCKED размером кандидата;
исправляется отдельно в S216.

Ops05:40:47UTC: DB5498280983/free252101967872, schema20261005_01/testDB0,
health200, request markers false. Ops proof SHA256
`df321c98541baf925b78bbc81626d19bb00348ce97129633de59ef544b2a965f`.
Остальные 26 прежних ошибок требуют отдельного ограниченного восстановления;
полнота ЕИС, технический допуск и прибыль UNKNOWN.
