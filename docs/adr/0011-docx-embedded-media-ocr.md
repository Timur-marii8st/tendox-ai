# ADR 0011: отдельный OCR связанных изображений DOCX

Дата: 2026-09-15. Статус: принято для S4.

## Контекст

Реальный закупочный DOCX содержал около 2,9 тыс. символов нативного текста и один
JPEG размером более 8 МиБ с разрешением 9921×7016. Нативный парсер не читал
изображение, поэтому прежний `PASS` не доказывал полноту документа. Guard
`UNKNOWN/EMBEDDED_MEDIA_IGNORED` закрыл ложный допуск, но не давал отдельного
проверяемого пути к содержимому изображения.

OOXML хранит изображения как package parts и связывает их с Main Document,
Header, Footer и другими частями явными image relationships. Само присутствие
файла в `word/media` не доказывает, что он используется документом. PaddleOCR
принимает как PDF, так и одиночные изображения; для image input `page_index`
может отсутствовать.

Источники решения:

- [ECMA-376: Office Open XML file formats](https://ecma-international.org/publications-and-standards/standards/ecma-376/);
- [PaddleOCR General OCR Pipeline](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html);
- [Pillow security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html).

## Решение

- Следовать только внутренним image relationships, ID которых реально
  используется в XML исходной части. Непривязанные ZIP entries не становятся
  OCR-источниками; внешние, отсутствующие и битые цели остаются видимыми issues.
- Разрешить только проверенные PNG/JPEG. До inference проверять extension, MIME,
  Pillow format/verify, SHA-256, размер до 10 МиБ, сумму media до 20 МиБ,
  измерение до 12000 px и площадь до 80 млн пикселей. Decompression bomb warning
  считать ошибкой, DTD/entity в relationship XML отклонять.
- Каждому изображению выдавать стабильный ID `<document_id>:media:<index>` и
  сохранять связь с SHA-256 внешнего DOCX, собственным digest, archive path,
  размерами и relationship locator. Исходные bytes исключать из сериализации.
- Расширить локальный `PaddleOcrRunner` на `image/png` и `image/jpeg`. Для
  одиночного изображения нормализовать отсутствующий `page_index` в image 1;
  digest и ресурсные лимиты повторно проверять непосредственно перед inference.
- Хранить OCR как отдельную `OcrDerivative`; locator имеет форму
  `DOCX media "word/media/image1.jpeg" :: image 1 bbox ...`. Нативный результат
  остаётся `UNKNOWN/EMBEDDED_MEDIA_IGNORED`, автоматического слияния фактов нет.
- Предоставить локальный CLI `ocr-docx-media`. Полный отчёт содержит
  распознанный текст и хранится только в приватном игнорируемом каталоге; stdout
  показывает digest, статусы и счётчики.
- Для server workflow хранить отдельную immutable DOCX-media OCR derivative с
  digest внешнего DOCX и изображения, tenant FK, RLS, append-only audit и
  idempotency. Перед записью repository повторно проверяет media relationship по
  сохранённым исходным bytes; бинарные данные не входят в публичный ответ.
- Визуальную AI-разметку хранить как отдельный review provenance. Разрешать на ней
  диагностические метрики, но блокировать production threshold до статуса
  `HUMAN_CONFIRMED`; подтверждённый человеком review не может содержать
  unresolved uncertainties.

## Последствия

Связанный JPEG из реального ТЗ прошёл полностью локальный PP-OCRv5 workflow и дал
95 блоков: минимальный принятый confidence 0,8276, средний 0,9588. Все bbox
связаны с media source; исходные image bytes в JSON не сериализуются. Другой
реальный `.png` не прошёл Pillow verify и честно остался `UNKNOWN/INVALID_IMAGE`.

Технический `PASS` OCR-производной не является production-калибровкой порога.
Без полного ручного эталона результаты не подключаются к hard gates и не снимают
блокировку мониторинга. Tenant-scoped API/persistence реализованы отдельным
восемнадцатым срезом, но сами по себе не подтверждают качество OCR.

Pillow становится прямой core-зависимостью: media bytes проверяются до optional
Paddle runtime, а одинаковые лимиты действуют в extractor и runner. CPU и память
на больших изображениях остаются заметными; очередь и worker isolation требуют
отдельного эксплуатационного решения.

## Альтернативы

OCR всех файлов из `word/media` проще, но создаёт ложные источники из
неиспользуемых package entries. Автоматически объединять нативный текст и OCR
удобнее для потребителя, но скрывает происхождение и неполноту. Конвертация всего
DOCX в PDF зависит от офисного renderer и меняет байтовый источник. Эти варианты
отклонены в пользу явных relationships и отдельных immutable производных.
