# S219 — просмотр точного сохранённого DOCX в интерфейсе ЕИС

Статус: завершён 2026-10-06 в указанных границах. Зависимость: sealed S218 / head20261006_01.

POST /v1/tender-discovery/eis-document-review/prepare принимает точный notice/
UID/documentSHA, только OPERATOR; page принимает request и строгие offsets/limit,
доступен авторизованным читателям. JSON <=4096bytes до parsing, unique keys,
finite values, extra fields rejected, no-store, whitelist/redacted errors.
Prepare — отдельный POSIX child: один slot на API process, busy503, CPU30s,
address space512MiB и wall45s (terminate/kill). Источник и задания ЕИС не вызываются.
API storage exception не раскрывает DSN или исходный текст. Child получает только
private stdin request/tenant/actor и transient DB env; source credentials удалены.

В полученном DOCX с известным SHA доступна отдельная панель проверки текста.
Prepare/replay и cached read разделены. Страница заменяется по нажатию; автоматической
загрузки всех страниц нет. Previous stack обновляется только после успешного ответа,
panel key содержит notice/version/XMLSHA/UID/docSHA; late unmounted responses ignored.
Строгий wire validator связывает response с request и обоими offsets, проверяет
source0, body scope, UNKNOWN conclusions, counts/provenance/spans/continuation.
Unicode lengths используют codepoints, а не UTF16; response stream<=256KiB.
Raw document text выводится React text escaping. Имя файла не утверждает роль.

Видны ограничения, native/fullTSpec UNKNOWN, retention totals/truncation и raw
фрагменты о поставке с контекстом. Сохранение всех извлечённых параграфов/таблиц
тела не доказывает покрытие колонтитулов, чертежей, остальных частей DOCX и ТЗ.
КП и сценарии экономики здесь не создаются; PARTICIPATE остаётся запрещённым.

Release evidence добавляется после isolated Linux gates и реального API/NextAction/SSR.
Browser visual отмечается отдельно. Источники, бюджеты и cron без изменений.

## Выпуск и проверяемые результаты

509 isolatedPG PASS73.54s/zero skips (source/storage и первая API revision);
после локальных OpenAPI/auth исправлений34 focused Linux API/runner/characteristic
PASS11.17s/zero skips. Node8 review wire/render +13characteristic/11analog/8protocol,
TS/ESLint/production build PASS; Astra material blockers closed. Auth regression
проверяет missing/malformed/invalid bearer до body parsing и сохраняет challenge.
OpenAPI новые requestBody полностью inline, без неразрешённых local $defs refs.
PG log SHA256 `08445991d905f0e84c84bf2d9e4865ef0296b13623735ba2eb83853136603dd0`;
final API log `87b0a092a5f6fbc1b5967e3bad3b3ce98d49a7f865ab35b440e7d86b0a9624a3`;
web build `f1d77c143fb9c5b6ff7e51660c9a3a60723a7269d5249a4298c22fa423ce08c3`.

Backend06:49:44UTC atomic9/host138/API29/worker29; web06:50:39UTC atomic11/
host147/web31. Auth no-store correction06:58:12UTC с повторными hash gates:
API `sha256:73d7bd4d2179953fe3d790be98b10d4041d9a3bbc22c6728e3fd00901f2fa374`;
worker `sha256:04f38406e24f0698b132294eb4bfe87b2c03815dde5f078052986c3a177c72f6`;
web `sha256:851fb1ca4112d1df20e61f9f905c34b59b75cf778085631cccb43b398a33bd36`.
Schema20261006_01/source budgets/cron unchanged. Runtime child cache proof1959ms,
source0/analysis_createdfalse; SHA256
`bf5ded30d83bddcbc272f720af2d85866ebe2fe9f6825253d268e4a0ba0bf084`.

Реальный API06:59:19UTC: current0107300009526000178v2,
UID01A0E7C8E19477C8A507A0C39F6BCCFF,
SHA0a17042337943da92666e42ef2b2970eaee7aeb775c08e8b77f85018af5b9337,
DOCX18550bytes/33blocks/1732chars. Название содержит «обоснование цены», роль
остаётся UNKNOWN. Firstprepare1698ms/replay1541ms,2pages66–107ms, точное
восстановление всех retained strings,1analysis/1audit/replay0writes/source0/jobs0,
notice/v3digests unchanged. Ten negatives401/404/409/413/422 с no-store PASS.
Private proof `/var/lib/eis-browser/research/rejected/s219-final-review-live-proof.json`,
SHA256 `25288e07e8d44e92804010183fc20ca682894c017e0b3b6fb719a0755a858ec6`.

Установленный NextAction+compiledSSR06:59:45UTC:2pages76–77ms/6negatives,
cacheprepare1540ms, native/role/requirements/fullTSpec UNKNOWN. Proof
`/home/syurai/vibe-seller-state/s219-final-review-web-proof.json`, SHA256
`17a0190fc17449af713c623afddd1577535cf9f07100587bd841239bddd6b341`.
Более крупный второй DOCX164blocks/27116chars прошёл7pages19–26ms; использован
реальный React Flight decoder (большие строки outline, нельзя считать результат
всегда JSON line1). Proof SHA256
`f32332de18f39444afea565dab7504146389d9a8e3d95699bcc29fc8ad2e9362`.
Его первый capture остановил verification на отсутствии auth no-store; созданный
анализ/audit и page proofs сохранены неизменными, новые доказательства имеют
отдельный final prefix. Никаких удалений или повтора записи для маскировки ошибки.

Шесть characteristic API/direct identities/negative gates и NextAction/SSR6reads/
5negative PASS;3analogqueries1233–2358ms/19admitted/1omitted/157positions PASS.
Regression proof SHA256
`79edf77e58b3adfa2eb9b89fe67662fc84184879182bf71a5be5500487188596`.
Ops07:00:23UTC DB5525920791/free251823386624/head06/testDB0/health200/markersfalse;
proof SHA256 `6a5600ea9553ece6723788d57018cc302ac47e6243f81f034286bafab81b3fa3`.
Browser visual NOT_PERFORMED. Native full coverage и полный охват ЕИС UNKNOWN.

Rollback snapshots в `/home/syurai/vibe-seller-state/backups/`:
- `s219-before-20261006T064939Z-code.tar.gz`, SHA256
  `0eddfb8ad31c78a49f4acd340b442a7b3ed6b25c5e47dc3a4e6209f87d4d2d95`;
- `s219-before-20261006T065036Z-web.tar.gz`, SHA256
  `4169336627cd7f4a4f614736101f69ca1b46d6c9121859b9fe3ff4923d471627`;
- `s219-authfix-before-20261006T065806Z-code.tar.gz`, SHA256
  `c547d1b7035db339ec1d628ccb784d0a45b9812328010c5904d160efd6ba172f`.
Откат кода/образов не удаляет immutable review evidence. После S219 следующий
продуктовый срез — поиск источников снабжения из exact позиции ЕИС (S220).
