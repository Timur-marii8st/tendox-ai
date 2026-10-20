# S200 — сверка NO_DATA через публичную выдачу ЕИС

Статус: завершён; установлен на VPS, target-bound live report и offline reparse проверены.
Owner root, самостоятельный review; зависимости S198/S199 и текущий public browser.

## Контракт и ограничения

Нельзя сравнить пустую страницу с SOAP-окном и назвать это доказательством полноты.
SOAP key содержит регион, тип документа, exactDate/offset; публичный поиск здесь
national44/allstages/publicationday. История версий и часовые пояса не сверены.
Это другой путь доступа к тому же ЕИС, не независимый набор данных. Поэтому
source_absence / independent_corroboration / coverage всегда UNKNOWN — даже если
на публичной странице0карточек или все50номеров уже встречались в индексированных
версиях. Результат не закрывает окно, не создаёт canonical receipt и не меняет
рекомендацию участия. Allstages включает завершённые процедуры для диагностики.

## Что реализовано

1. Tenant local-eis-supplier, <=7дней по --since; PG RR/RO/30sSQL.
2. Из <=10latest retained audit candidates выбирается completed daily NO_DATA,
   связанный с последней попыткой этого tenant/window/SHA/actor/time. Future попытки
   не принимаются. Исходный SOAP проходит offline hash/manifest/parser проверку.
3. Одна публичная navigation: national44 за date target, все4этапа, первая страница
   recordsPerPage=_50. Import lease wait<=30s, shared browser60s cooldown/proxy,
   существующий bounded browser timeout. Подзапросы/assets браузера отдельно не
   подсчитаны; source_navigations1 не означает один сетевой HTTP-запрос.
4. В DOM должны совпасть единственные controls обеих дат, blank searchString,
   page1/size50, fz44checked/fz223unchecked и af/ca/pc/pachecked. Проверены law и
   visible Размещено каждой принятой карточки. Чужой host/regNumber отвергается.
5. <=50unique official number candidates сравниваются с tenant eis_notice_versions.
   Known означает наличие любой версии, не актуальность/lexical readiness.
   not_indexed_candidates — кандидаты для адресного получения по номеру, не
   доказанные пропуски данного SOAP-окна. Типы процедур могут быть вне canonical
   allowlist. Автоматической загрузки/ранжирования/оценки выгодности в этом slice нет.
6. Сохраняется rendered DOM (не HTTP response bytes) +SHA/size и typed JSON proof:
   target audit/journal/source manifest, controls scope, candidate URLs/locators,
   partition indexed/notindexed и независимый snapshot индекса.

## Запуск

```bash
cd /home/syurai/vibe-seller
bash scripts/server-eis-no-data-public-check.sh --since 2026-10-05T12:43:08.752311Z
```

Manual operator diagnostic, не cron/не автоуведомление. Нельзя запускать в обход
wrapper и глобального import lease. Source worker budgets/cadence остаются прежними;
одна отдельная диагностическая navigation занимает lease, без параллельного reader.

## Хранение и ошибки

DOM<=8MiB, <=100000nodes/depth64; capture store32MiB/8files на tenant,
`research/rejected/public-no-data/local-eis-supplier`, file0600/root0700.
Exclusive capture lock, no overwrite/delete/eviction; partial failed write откатывается
только для собственного нового файла. Crash-lock требует операторской проверки;
он не удаляется чужим запуском. XML запроса/token не сохраняются; reflection проверяется
в raw/decoded/text fragments/attrs. JSONproof<=1MiB0600, UUID immutable filename.

BLOCKED/FILTER_UNVERIFIED/cooldown/quota/недоступность остаются UNKNOWN. Если DOM
получен и сохранён до ошибки parser, failure proof сохраняет его SHA/ref и target.
Иначе count navigation0 или UNKNOWN, не придумывается успешный сетевой запрос.
Нет target — нет browser call. DB writes0, source checkpoint/index/audit не меняются.
Неизвестные форматы не принимаются за пустую нормальную выдачу.

## Evidence реализации

71Linux/isolatedPG testsPASS2026-10-05T13:56:38Z; Ruff/mypyPASS.
Проверены date/law/stage echo, blocked/empty, duplicate/unparsed/trusted numbers,
artifact quotas/reflection, typed day/hash/partition и latest/tenant/index/RLS/read-only.
Первый PGgate обнаружил отсутствие actor_id в reusable latest CTE; исправлено чтением
actor из самой latest attempt, без изменения существующего source runtime.

Research navigation:03.10.2026, fz44/allstages/page1/_50; controls verified;
50cards/50candidates/0unparsed, источник объявил77records exact. Rendered DOM935504bytes,
SHA `bfaf64da78398b7c9ff5e83ae2c9b14d5561a177c6f8ce8505d965c618576ba2`;
private `/var/lib/eis-browser/research/rejected/s200-probe-33e88ebf-b4aa-45bf-9c15-5a73279033b4.html`.
Этот сохранённый DOM повторно разобран candidate parser без новых source calls.
Официальный scope URL:
[ЕИС, 03.10.2026](https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=&pageNumber=1&recordsPerPage=_50&sortBy=PUBLISH_DATE&sortDirection=false&fz44=on&af=on&ca=on&pc=on&pa=on&publishDateFrom=03.10.2026&publishDateTo=03.10.2026).
Это отдельный research probe, не связанная независимая проверка absence конкретного
NO_DATA. Live target-bound report после host-only rollout требуется отдельно.

Next S201: bounded адресная загрузка поддерживаемых notindexed candidates по номеру
с проверкой XML/типов/receipt, сохранением unsupported evidence и честным scope.
Полный национальный охват и независимая absence verification остаются UNKNOWN.

## Live acceptance — завершено 2026-10-05

Host-only rollout14:01:13UTC:atomic9/host41/API5/worker5hashPASS;
HEAD03 and pinnedS198runtime/API/worker/web/cron/source worker budgets unchanged.
CodebackupSHA `ab9b62837bc0b6ab54164d4c4f5300cede4eea4e41b72886ff498f236876c510`.
Global import lease held for one manual diagnostic public navigation; no API restart,
canonical/index/audit/checkpoint mutation. Research probe earlier was one separate
navigation; these two navigations are not the complete count of browser asset requests.

Target-bound report14:01:11.851990UTC:
`getDocsIP/PRIZ/73/2026-09-02+03:00/epNotificationCancelFailure`.
Retained SOAP was verified and bound to latest tenant NO_DATA attempt/audit before
navigation. Public national44/allstages publication-day2026-09-02/page1/_50:
50scanned/50parsed/0unparsed, 27numbers in tenant versions, 23notindexed candidates.
Source count floor7300, exactfalse; do not state exactly7300 or full pagination.
These50cards are not restricted to region73/cancel-failure documents; no contradiction
or confirmed absence is inferred for the SOAP-window. New23numbers may include
unsupported methods and completed procedures; they are not participation suggestions.

DOM976052bytes, private tenant file
`/var/lib/eis-browser/research/rejected/public-no-data/local-eis-supplier/body-dab2bcb7-d88f-4001-b993-7fb317c0dbdd.html`;
SHA `4f2cb74a5a2e6e301374b8e99df1db33e2a049bfff09f3b70fa6389bf422ed2b`.
Typed proof `/var/lib/eis-browser/research/rejected/s200-public-check-60c82246-c776-421f-b885-216d6d5c41a0.json`;
SHA `e747bf27ea301f86a4087270a992533020ffb318396293a73400274f342c6b27`.
Offline verification after rollout: proof model/hash/DOM size+hash/reparse and target
retained SOAP manifest/hash PASS; source navigations0 / DB writes0 for verifier.

Ops14:01:12UTC:health200/HEAD03/testDBnone/DB4469455895/free258274816000bytes;
ordinary223markertrue, no foreign marker cleanup. OpsSHA
`bad426a59ddf20d4387e10642b2b2234c5f1923fc80ce63f775247716975dfdf`.
S200 complete as bounded access-path cross-check/candidate discovery slice.
Independent source corroboration/absence/fullEIS coverage UNKNOWN.
NextS201: bounded recovery of supported notindexed numbers, exact XML binding and
explicit evidence for unsupported cases, preserving source admission contracts.
