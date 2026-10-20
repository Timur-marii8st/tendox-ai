# ADR 0048: буквальные ячейки legacy XLS и новая версия разбора

Дата: 2026-10-02. Статус: принято; S141 проверен и развёрнут на VPS.

## Основание

В реальном shortlist сохранён XLS на 44 032 bytes. Native v1 сообщает
UNSUPPORTED_FORMAT. XLS часто содержит формулы: [xlrd документация](https://xlrd.readthedocs.io/en/latest/)
предупреждает, что библиотека возвращает их сохранённые результаты. Они
не становятся подтверждённой ценой/требованием. [MS-XLS Formula](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/bccb00ac-67a1-490a-9f0b-5ce59978eb9a)
описывает source row/column и cached value отдельно.

## Решение

Поддержать только OLE BIFF8 XLS с MIME application/vnd.ms-excel и отдельным
native_xls extractor. [olefile API](https://olefile.readthedocs.io/en/latest/Howto.html)
читает streams в памяти: directory/stream sizes проверяются до чтения Workbook.
Структура, BIFF record lengths/count, source capacity, размер и text limits
проверяются; VBA/macros и FILEPASS отвергаются. [MS-XLS BOF](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/4d6a3d1e-d7c5-405f-bbae-d01e9cb79366)
задаёт BIFF8 и тип macro substream. Иные BIFF версии дают явный UNKNOWN при
EIS analysis, не объявляются поддержанными.

Formula coordinates фиксируются до xlrd; такие ячейки и cached values не
дают blocks. Литеральные TEXT/NUMBER сохраняются с sheet!cell locator,
formula presence делает результат UNKNOWN. Dates/errors/boolean cells пока
UNSUPPORTED_SOURCE_UNITS; drawing/embedded objects и внешние supporting
links дают UNKNOWN. [MS-XLS SupBook](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/31ed3738-e4ff-4b60-804c-ac49ac1ee6c0)
позволяет отличить self reference от иных links. Сеть/Office/формулы/макросы
не запускаются. Числа выводятся строками через Decimal; финансовый вывод
не делается. XLS в ZIP сохраняет archive member provenance и прежние guards.

Native parser pins: xlrd 2.0.2, olefile 0.47; xlwt 1.3.0 только dev synthetic
fixtures. Legacy DOC выполняется отдельным следующим срезом.

## Cache и миграция

eis-native-v2-xls добавляется к explicit допустимым DB versions. v1 analysis,
receipt и bytes остаются immutable. Worker делает максимум один cached
reanalysis step без source I/O, проверив tenant/exact ref/current version,
manifest byte count и SHA исходных bytes; пишет новый analysis/audit.
Полученные документы просроченной/отменённой current карточки могут быть
разобраны из cache; новые файлы по ней блокирует S140. STALE ref не
переразбирается. Повтор той же parser version использует cache.
Downgrade не удаляет v2: constraint validation отказывает при таких строках.

## Границы

PASS extraction подтверждает буквальный native text, не полноту комплекта,
семантическую роль или соответствие. Старый DOC, сканы, media и непрочитанные
формулы остаются UNKNOWN. Версия parser не делает весь ЕИС полным и не
создаёт PARTICIPATE. Проверки и runtime evidence ведутся в live плане.
