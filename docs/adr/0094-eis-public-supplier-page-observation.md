# ADR 0094 — ограниченное чтение сайта из сохранённого SERP evidence

Дата: 2026-10-06. Статус: accepted для S224.

## Решение

URL выводится только из tenant-owned immutable parent SERP run/engine/rank,
привязанного к действующей позиции ЕИС. Отдельный DNS-pinned HTTPS transport
читает один HTML документ с TLS hostname verification, проверкой каждого hop
и лимитами ресурсов. Внешний child deadline ограничивает также DNS.

Наблюдение структурированного Product/Offer отделено от технического соответствия,
подтверждённой supplier identity и коммерческого предложения. Цена — Decimal,
границы AggregateOffer не становятся ценой единицы комплектации. Факты имеют
HTML SHA256/locator; все отсутствующие условия UNKNOWN.

STARTED, source outcome и audit сохраняются неизменно. Parent/report/position/link
bindings проверяются в приложении и PostgreSQL. Read/cache не открывают сайт,
не загружают body и не маскируют последнюю неудачную попытку старым успехом.

## Последствия

Низкие стоимость и память; нет платного search API и личного browser profile.
JS-only сайты и страницы без поддержанной разметки не дают подтверждённой цены.
Необходимы отдельные срезы product selection/spec matching и сопоставимого КП.
