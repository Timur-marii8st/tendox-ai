# V58: свежий census44/223 и восстановление лекарственных позиций

Владелец root; ACCEPTED_BOUNDED_INSTALLED_SIX_DRUG_SOURCE0. Зависимость — принятый
[V57](145-eis-zp-corpus-search.md). Evidence `tmp/eis-completeness-census-20261027-v58/`.
Owned files: этот отчёт, ingestion README, live-план и evidence V58.
Acceptance: свежий tenant-scoped census обоих законов; source/native доказанный пробел;
адресное восстановление, основной HTTP поиск, actual UI, audit/replay и независимый review.

## Свежий срез 27 октября, 08:27 МСК

44-ФЗ: 414155 закупок/452119 версий; все версии имеют lexical index.
В очереди 339031 окон: 32664 canonical completed, 306367 pending;
153527 unattempted, 152773 NO_DATA, 67 FAILED, 46 transport-only.
Окно очереди не равно отдельной закупке; NO_DATA не доказывает пропуск закупки.
За сутки сохранено 10539 новых версий44 и 4486 версий223.

223-ФЗ: 50899 закупок/59095 версий. Волна26–27Oct: 1260/1260 attempted,
341 SYNCED/919 NO_DATA/0 FAILED; 90 регионов, due295/cooling965.
COMPLETE относится только к зафиксированному planned scope;
national coverage и freshness UNKNOWN. SQL5s/lock2s, read-only; source0.

## Подтверждённые пробелы

Из первых30 пустых latest карточек каждого закона зафиксированы6+6 случаев.
12 XML/10 ZIP, около28MiB: metadata-first, ≤16MiB/archive и ≤64MiBtotal,
SHA и canonical identity проверены. Independent diagnosis review PASS:
14 лекарственных позиций/112 fact slots и 106 joint223 lotItems подтверждены native XML.

44: 0101500000326000235, 0101500000326000248, 0102200001626002327,
0102200001626002334, 0102200001626002337, 0102200001626002338; всеv1.
Canonical items0/mainHTTP0, UI первой карточки «Позиции не подтверждены».
Действующий v4 drug projector извлекает14 позиций. Пять количеств UNKNOWN:
raw totals присутствуют, но ветвь drugInterchangeReferenceInfo не даёт поддержанного
однозначного сопоставления единицы/альтернативы; числа не выдумываются.

223: 32616316174v5 KESMBO(32), 32616327569v4 general(2),
32616374237v2 general(7), 32616399522v6 general(40),
32616403675v3 AESMBO(19), 32616407474v4 general(6).
Всего106 joint items, пока не восстановлены: установленный joint projection
ограничен ZPESMBO. Расширение типов требует отдельного среза и миграции.

## Точный адресный план44

План3ef81d02ab992358b1a8fe1eb66b2780d5a3ccb06ec9c20d8f6062cdf2e37374:
6 immutable projections/6 projection audits и4 release audits;14 позиций/5UNKNOWN.
Canonical/search keys/КП, образы, schema27_02 и cron не меняются; source0.
Используются принятые V55 четыре lease и V50 drug producer/audit protocol;
V45/V50 executable hashes проверяются до runpy,8 negative guard tests PASS.
Точная версия/XML/ZIP/canonical SHA, source hold, отсутствие прежнего v4,
expiry и неизменность runtime проверяются под lease. При сбое append-only
история сохраняется, собственный producer завершается до освобождения lease.
Повтор после prepared требует reconciliation. Ручное подтверждение заменено
постоянным поручением пользователя; hard gates/квоты/TLS/cooldown сохраняются.

## Принятый результат

Exactplan review PASS, установлен source0:6projections/6projectionaudits,
14positions/5UNKNOWN; replay каждой строкиFalse и канонические SHA неизменны.
Real mainHTTP6/fullprojectionSHA и actualbrowser6/sourceXML/member/14summarylines PASS.
Неизвестные количества и единицы видны явно. Screenshot actual-ui-final.png.
Release audit4stages;27_02/APIad34/WEBca9d/containers/config/cron прежние,
собственный V50 producer отсутствует. Independent installed-review PASS
SHAf4d68645e1ee10fd7c977649f17bae250d375f4a69475da8b06bf66f6487eb09.
На 08:46 МСК штатная волна223:345SYNCED/915NO_DATA/0FAILED, due236/cooling1024;
это обычный продолжающийся сбор, не14drugbackfill sourcecalls.

Следующий срез — [V59](147-eis-223-joint-families.md):6joint223/106nativeitems.
Полнота страны/ТЗ,
экономика, региональный прогноз и PARTICIPATE UNKNOWN.
