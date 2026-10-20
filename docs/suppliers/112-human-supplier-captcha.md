# Ручное прохождение CAPTCHA поисковика

Статус: INSTALLED; настоящее прохождение CAPTCHA человеком pending.
Решение — [ADR0105](../adr/0105-human-supplier-captcha.md).
Зависимости: [SERP105](105-eis-position-supplier-serp.md), persistent profile,
актуальная сохранённая позиция. Это ограниченный срез, не весь поиск изготовителя.

## Владельцы и acceptance

- Root: API/router, storage audit/recovery, retry, web UI, deployment/docs.
- Sol captcha_browser: новый browser manager и его тесты.
- Sol captcha_serp_parsers: supplier_serp source/parser и его тесты.
- Astra captcha_architecture: read-only архитектура и независимый review.

Acceptance: server-derived запрос; tenant/actor isolation; одна сессия до 10
минут; защищённые кадры/команды; отсутствие arbitrary URL/JS/cookie API;
реальная проверка SERP; одноразовый retry без удаления общих блокировок;
сохранение UNKNOWN; гарантированное закрытие процессов и lease.

## Пользовательский путь

В позиции ЕИС открыть сохранённую выдачу или выполнить поиск. При BLOCKED
нажать «Открыть Google/Яндекс/Bing» в блоке ручной проверки. Открывается новый
процесс Chrome с тем же профилем организации. Нажимать на изображение CAPTCHA;
для текста выбрать поле кликом и отправить текст кнопкой. Затем нажать
«Я прошёл проверку — продолжить поиск». Если парсер не подтвердил выдачу,
окно остаётся открытым. После подтверждения выполняется обычный новый поиск.

Отказ может повториться. Прохождение не подтверждает охват рынка, изготовителя
или КП. Сессия ограничена 10 минутами, без продления активностью.

## Границы

API владеет задачей отдельно от 90s subprocess runner. Публичный браузерный порт
не открывается. Снимки и ответы CAPTCHA не попадают в audit; подтверждённый
source DOM/provenance сохраняется отдельно. Старый SERP report неизменяем.

POST endpoints start/status/frame/input/verify/cancel под
`/v1/tender-discovery/supplier-captcha/`. Start принимает только request,
run_id и engine; команды — session_id и ограниченный event. Клиент не выбирает
URL/query/company/actor/профиль. Все ответы no-store/private.

## Evidence

Offline/server checks и реальное прохождение человеком фиксируются отдельно.
До live acceptance ручное прохождение не объявляется реально проверенным.

2026-10-07: 144 bounded Python tests PASS; 6 real PostgreSQL tests PASS;
4 CAPTCHA wire tests и 14 SERP wire/render tests PASS. TypeScript, ESLint,
Ruff и production web build PASS. Полный общий pytest suite не запускался.

Настоящий headed Chrome с выключенной сетью и синтетической страницей:
1280×720 JPEG, клик в нижней части кадра, ACCESS_BLOCKED перед кликом,
VERIFIED с одной organic ссылкой после клика, cleanup/profile lease PASS.
Это проверка механизма, а не решение настоящей CAPTCHA.

Live Яндекс: frame/DOM read подтверждены. Новый процесс сразу показал выдачу
без CAPTCHA; ответов/кликов реальной проверке не отправляли. HTML
2 404 084 bytes, SHA `244637178e3cd4c14d5b9930024abaf1577cbc644561c4f791782f5c30132db0`:
read-only reparse COMPLETED, 24 scanned/9 returned. Лимит поднят до 8 MiB
с проверкой границ и согласован с web; общие bundle/day budgets сохранены.

Next Server Action bridge: same-origin status200 с собственной session;
foreign Origin отклонён (Next500), session/API token в ответ не попали.
Защита HTTP429 проверена также при ошибке startup и transient pacing lease.
RATE_LIMITED и неизвестный COOLDOWN не дают права открыть ручной режим.

Текущий установленный pinned overlay v9: 8 API + 5 web files, schema08,
без migrations/новых портов. Manifest/rollback backups находятся на VPS:
`/home/syurai/vibe-seller-state/supplier-captcha-rollout/release-20261007-v9/manifest.json`.
API SHA `5c6cac213446e19f048e5e1c2eaf7f270447fc0a5de70ceb3b68eb7afb4ace04`;
web SHA `28abf81737db168603a2cf1dcf44bd9c8784119e7b211a092350d040f40190f0`.
API health200 и web discovery200 после установки.

Повторная live выдача Яндекса выявила новый semantic layout. Его адаптер
требует единственную наблюдаемую цепочку `Organic`/`OrganicTitle`/title anchor,
исключает рекламу/скрытые элементы и сохраняет индексы li с placeholder rows.
Полный private DOM 2 390 898 bytes, SHA
`073dd6ccd904febd0b41eae84a52d523671a83ae1f20088f1c1dcb34f4ffa83c`:
COMPLETED, 14 scanned/9 returned, ranks 2,3,4,5,7,8,9,12,13.
Locator указывает точную semantic цепочку, лимит 256 согласован с UI.
Неизвестная разметка и неоднозначные title anchors остаются SOURCE_CHANGED.

Обрыв verify HTTP не отменяет owned финализацию. `finalizing` сохраняет polling
до выдачи permission; status возвращает оставшуюся pacing-паузу, UI запускает
один retry как из verify response, так и из восстановленного status.
Регрессия HTTP disconnect/незавершённый audit/одна запись VERIFIED PASS.
Отмена/expiry настоящей сессии убирают Chrome/Xvfb и освобождают профиль.
Live v9: server session `392aca6d-0826-4efb-8f23-42ced1cbaa62` вернула
VERIFIED/retry_ready после проверки настоящего DOM; audit
SUPPLIER_CAPTCHA_VERIFIED записан 2026-10-07 05:52:32 UTC (server clock),
source_status COMPLETED, DOM SHA
`bf84d00657eaecc0e1f608c2a392e05c5844b19616c709f089f93846416900cd`.
CAPTCHA в этой сессии не появилась; реальных ответов/кликов не отправляли.

Один обычный retry действительно выполнился и сохранил run
`ae44956d-e7b6-4a24-8166-74c03b5fbfb6`: Bing EMPTY, Яндекс SOURCE_ERROR,
Google SOURCE_CHANGED/QUERY_BINDING_INVALID, по одному переходу каждый.
Strict live source acceptance ожидал Яндекс COMPLETED/EMPTY и получил FAIL;
успешная выдача после нового перехода **не подтверждена**. Причина ошибки
обычного transport ещё не установлена. Нельзя считать retry гарантией доступа.
Source0 read и validator фактически установленного web PASS: PARTIAL, requests0.
Механизм frame/verification/audit/one retry работает; настоящее прохождение
CAPTCHA человеком и успешный source outcome после него остаются pending.
