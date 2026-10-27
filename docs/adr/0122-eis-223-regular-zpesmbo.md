# ADR0122: запросы предложений МСП в регулярном потоке

27 октября2026. Владелец root. Статус: INSTALLED; обычная региональная приёмка PENDING.
[Контракт V54](../eis/ingestion/142-eis-223-regular-zpesmbo.md).

## Контекст

На установленном V52 воспроизведён DOCUMENT_TYPE_UNSUPPORTED всех четырёх
редакций реального purchaseNoticeZPESMBO №32616349722. Retained BY_NUMBER UID
b8e7735c-9762-4e6e-bcb0-4dfcca80e57e/ZIP6f0438eb фиксирует namespace/data QName;
прежние XSD16.2/16.3 PASS — историческое evidence. Старая local реализация13Oct
не установлена и не служит новым baseline. Координаты региона/дня не выводятся
из адресного ответа, ИНН или publicationDateTime.

## Решение

Добавить явное пятое notice family, отдельно разрешить BY_NUMBER только для
KESMBO/ZPESMBO. Новый ZP требует factory binding как BY_NUMBER, так и BY_REGION;
проверки key/kind/UID/response hashes/full archive set обязательны.
Адресный импорт не пишет региональный attempt; повторное получение той же XML
версии через другой режим сохраняет первоначальный canonical source. LegacyKES
и прежние три семейства сохраняют принятый контракт. Признак МСП/сроки/Decimal
не выводятся из названия семейства.

Точные старые множества5/6 families с pinned catalog переходят новой волной к7,
с теми же frozen start/end. Старые targets/ordinals/attempts сохраняются;
последние исходы используются по неизменному ключу. Неполный/mismatched scope
блокируется. При равном now новая ZP волна приоритетнее KES и legacy5 до UUID.
90регионов дают1260 координат, максимальные99 —1386.

Миграция20261027_01 расширяет пять CHECK: windows/snapshot/attempts/targets/
wavebounds. Downgrade до любого narrowing проверяет все tenants при
row_security=off, запрещается при любых ZP данных/planned keys или count>1188;
неполная видимость означает отказ. Все потребители и WEB должны быть совместимы,
forwardbarrier записан до первого нового ключа. После него старый consumer
не восстанавливается даже при отсутствии импортированного ZP ZIP.

## Последствия и альтернативы

Появляется регулярный путь отсутствовавшего семейства, но национальный охват
UNKNOWN. Historical BY_NUMBER доказывает parser/key contract, не BY_REGION
координаты и не текущую стадию. Региональная приёмка требует настоящего binding
обычного source turn. Старые fixed3/4 caps в local13Oct не переносятся;
актуальные byte/XML/item limits,54min/hour,180s,32/60,SQL/resource/tenant guards
и cron сохраняются. Подмена типа на generic/KES или перезапись старой волны
теряют provenance и не рассматриваются.

## Уточнение миграции после проверки на рабочем объёме

ADD CHECK со сканированием snapshot превысил SQL5s на ~56тыс. редакций;
транзакция откатилась, schema26_03/runtimeV52 сохранены. В той же транзакции
под ACCESS EXCLUSIVE сначала проверяются точная таблица/тип/выражение и
convalidated=true прежнего CHECK. PostgreSQL-нормализация сравнивается с
точными BEFORE/AFTER через временные CHECK NOT VALID; наследование запрещено.
BEFORE⇒AFTER: добавлено одно значение enum/regex либо расширена граница1188→1386;
остальные условия неизменны. При ещё действующем validated BEFORE создаётся
расширенный NOT VALID CHECK, затем заменяется имя. Новые INSERT/UPDATE проверяются;
старые строки доказаны прежним validated CHECK. convalidated=false отражается
честно; VALIDATE и изменение pg_catalog не выполняются. Exact validated AFTER
допускается только как уже обеспеченное состояние historical metadata bootstrap.
Отсутствие/дрейф/NOT VALID старого CHECK, временное имя или иной scope блокируют
миграцию. Все пять замен атомарны; downgrade сохраняет guards и полноценный scan.
Лимиты SQL5s/lock2s прежние. Старый PREPARED/failure сохраняется; продолжение —
новый точный reviewed план после сверки отсутствия barrier/данных и старых pins.
