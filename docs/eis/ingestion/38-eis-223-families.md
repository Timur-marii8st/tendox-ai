# Проверка дополнительных семейств 223-ФЗ

S152 проверяет public/actual `purchaseNotice` (иной способ) и
`purchaseNoticeZKESMBO` (электронные котировки для МСП) из официального NSI.
S152 — исследование source contract. В S153 ZKESMBO подключено к индексу;
«иной способ» остаётся в карантине.

Владелец: основной агент. Operator probe запускается на VPS под общим
eis-import.lock, region50/day2026-10-01/+03:00, по одному request на семейство.
Max4prepared polls/10s, max2ZIP/16MiB каждый, max200XML/4MiB,
max32MiB expanded/ZIP. Полный archive set и UID проверяются до GET.
XML root/Data должны совпадать с выбранным семейством; каждый XML валидируется
обоими локальными официальными purchase.xsd16.2/16.3 из S149.
SchemaLocation из XML не загружается, DTD/entities/unsafe paths запрещены.

Исходящие SOAP и credentials не сохраняются. Tenant source selection,
полученные SOAP, ZIP и metadata inventory записываются immutable/0600 на VPS.
Inventory содержит exact XML SHA, прямой Data locator, исходный title/deadline
и список прямых fields. Это диагностика структуры, а не вывод о прибыльности,
актуальной стадии или полном ЕИС. Никаких source/index admissions по названию.

Официальный контракт и SHA пакетов — [документ S149](37-eis-223-notices.md).
## S152 результаты

16 synthetic security/binding tests прошли наWindows/Linux; Ruff/mypy4files.
ZKESMBO:35XML/35номеров, одинZIP3138246bytes,
SHA88bd8a62ea088a0f3c0a1d41153ad34f4ae013ffd91985c2809d6acfff334b9f.
Все35валидны пообоим официальнымXSD. Direct Data: registrationNumber/version,
name, submissionCloseDateTime, lots/attachments и method fields; naive сроки
не преобразованы вactive deadline. Live18.779575s, cached replay0.261793s
безPOST/GET. Proof0d9e0dbe-4539-47ee-bbdf-33c1aa5d8a4f-proof.json,
SHAe79cc4a8991350381bc7b889c7d53e8ae1a7fe1db89158b9ef830650707e4310;
replaySHA0fba9ebdcb047eacf47964d385d43f2cb1a2db12d10289e0f7e6d185beee7276.

«Иной способ»:25XML, одинZIP2778437bytes,
SHA7dfacc0da896a1779b01430c4981096363394303c3582c6c0a8373c412eefb40.
24из25валидны вкаждойXSD; у одного placingProcedure отсутствует обязательное
summingupDateTime. Весь архив SOURCE_REJECTED; fact inventory не опубликован.
Сохранены проверенные на ZIP/XML security/token reflection исходные bytes и
25per-member XSD diagnostics. Source schema не ослаблена ради успешного импорта.
Recovery использовал прежнийUID17911292-48dd-4892-90ac-0caaa3b67013/сохранённые
SOAP/selection, одинGET3.685515s. Proof
17911292-48dd-4892-90ac-0caaa3b67013-replay-20261002T095250029410Z-proof.json,
SHA799d2e4d2303446306a08bf496f579676f0d9eded004b61188a0f7fbafbdc83e.

Все raw/proofs только наVPS:
`/var/lib/eis-browser/research/223-families/local-eis-supplier/{family}/`.
Cached replay требует exact company/family/day/region/offset/UID selection;
immutable write допускает только identical bytes. Proof ошибки имеет отдельное
имя, исходный успешно проверенный proof не переписывается. Выгода, eligibility,
глобальнаяcoverage UNKNOWN. Следующий срез подключает только ZKESMBO к metadata
индексу; generic source-quality handling требует отдельного решения.

## S153 — электронные котировки в индексе

Reader/intake/search допускают только AESMBO и ZKESMBO. Root/Data, provenance
и SQL snapshot family связаны с точным source window. Migration20261002_06
сохраняет AES history; downgrade с котировками запрещён. Refresh пока AES.
35версионный ZKESMBO sample импортирован0.351389s; replay0.201899s без мутаций.
Всего54версии/50текущих карточек/4окна/3ZIP. Search«центрифуга»0.166236s,
32616427422v1; BFF/UI подтвердил метод,339994.15RUB,4ссылки, source locator/SHA.
Без timezone срок UNKNOWN, descriptions UNKNOWN; profit/eligibility/coverage
UNKNOWN.76local/43PGtests,Ruff/mypy/webbuild/ESLint прошли. Proof
s153-index-proof-20261002T100735671307Z.json, SHA
b6ce16975db2560b7dec6c978906b2e24426abf6dc65831053eb24cf8056faa3.

## S154 — refresh двух223семейств

Region50/today+yesterday+03:00 дляAESMBO/ZKESMBO. Due targets4, oldest checked_at
first; max2за проход/180s,6h success/1h error, cron11,41 иобщийlock/budgets
сохранены. Migration20261002_07 расширяет immutable journal, history сохраняется.
83local/23Linuxsync/44PGtests, Ruff/mypy/shellsyntax/deploy прошли.
Live37.372801s:8new/2SYNCED; repeatNOT_DUE/0requests.
62версии/56current/6windows/4ZIP/4attempts. Proof
s154-refresh-proof-20261002T105057620924Z.json,
SHA66a090a3195a76ee1dbfde11179d4dab4b82f66e754c63742e0280c85497d246.
Full-XSD61/62validbothreleases;1XMLsubstantiationNationalRegimeValue104>100.
Typed metadata projection иfull-XSD — разные проверки; SYNCED неXSD PASS.
Raw history сохранена, eligibility/economics/coverage/freshness UNKNOWN.

## S155 — полная XSD проверка отдельным evidence

Точный номер/версия/XMLSHA связан compositeFK с immutable FORCE RLS quality
journal. Official schema package/root/tree SHA и parser version сохранены;
отсутствие полного evidence двух releases — UNKNOWN, любая schema ошибка — FAIL.
Schema PASS не даёт допуск/полное ТЗ/прибыль. Диагностика видна в API/UI.
Offline audit bounded200versions/32MiB compressed, без HTTP; pinned trees
проверяются целиком, external schemaLocation запрещён. [ADR0051](../../adr/0051-eis-223-schema-quality.md).

Deployment2026-10-02:79версий/72current/10windows;158checks,156PASS/2FAIL
дляXML32616432455v1, SHA d95f415b79ee37f87d8a64e602a2ad62f2ed1cd5276d4ba56a709e4fb11fdc97.
Replay0new/source0; API0.324525s/GETне меняетaudit/jobs; CUA подтвердил
FAIL обеихXSD иисходнуюцену1615916.67RUB.97local/45PG/37Linuxtests,
Ruff/mypy/webbuild/ESLint прошли. Production schema20261002_08; testDBудалена.
Proofs s155-schema-proof-20261002T172747460572Z.json,
SHA1d46cb2a7ec7a42f4f0acebda883e06564bdbd889df04d2a366b4ca9ee5b5254;
APIproofs155-ui-api-proof-20261002T172855560054Z.json,
SHAbbfdf0bbc3084e0a45416a22215521cf6c9ae3232e97755659fa9ca15bdc39ec.
