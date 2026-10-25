# B11: вход бета-тестера по приглашению

Дата: 2026-10-24. Владелец: root. Статус: INSTALLED, live проверки PASS. [ADR0114](../adr/0114-beta-company-invitations.md).
Evidence: `tmp/beta-invitations-20261023-v33/`.

## Для участника

1. Организатор присылает личную ссылку. Откройте её целиком, включая часть после
   `#`. Если сайт спрашивает общий пароль закрытой беты, используйте пароль
   организатора; персональный ключ вводить не нужно.
2. Нажмите «Войти и заполнить профиль». Ссылка работает один раз, обычно48часов.
   Если она недействительна, попросите новое приглашение. Само открытие ссылки
   и preview её не расходуют.
3. Заполните профиль, сохраните и выберите версию. Перейдите к поиску закупок,
   выберите регион и откройте карточку → «КП и расходы». Введите действующее
   полное КП, расходы, налоги и основания. Пропуски остаются UNKNOWN.
4. Рабочий доступ действует7дней. После выхода/отзыва/истечения срока нужна
   новая ссылка. Пересылать личное приглашение другим людям нельзя.
5. Сотрудники одной компании работают с одним профилем и КП. Независимые
   компании получают отдельные пространства. Расширенные pilot/reviewer инструменты
   в этом входе недоступны. Финансовый подбор не является допуском к участию.

## Для организатора и администратора

Приглашения выпускаются owner CLI, не публичной формой. Runtime не может выдавать
доступ. Организатор заранее определяет компанию и участника. Новая компания
генерируется по умолчанию; `--company-id` используется только для явно выбранной
существующей beta-компании. Корпус ЕИС не является компанией тестера.

В окружении owner-процесса должны быть `DATABASE_ADMIN_URL`, `EIS_PILOT_COMPANY`
и `BETA_INVITE_ORIGIN=https://www.syurai.su`. Не выводить окружение/секреты в логи.

```sh
python -m procurement.api.beta_invite_admin \
  --actor-id participant-001 --issued-by beta-organizer \
  --output /private/invite-participant-001.json
```

CLI создаёт новый файл0600 с URL и идентификаторами. Секрет не печатается в stdout;
там только status/company/invite_id. Файл не должен существовать заранее.
Для повторного входа после выхода/истечения срока сохранять исходный company_id:
новое приглашение выпускается с `--company-id`, иначе возникнет новая компания.
Для коллег добавить `--company-id <выданная-beta-компания>`, для другой компании
создать отдельное приглашение без этого параметра. Передавать ссылку адресно,
не публиковать в чате. Создание реальных доступов не входит в тестовый прогон.

Отзыв приглашения одновременно прекращает его сессию:

```sh
python -m procurement.api.beta_invite_admin \
  --company-id <beta-компания> --actor-id participant-001 \
  --issued-by beta-organizer --revoke-invite-id <invite_id>
```

## Acceptance и установка

Обязательны: конкурентное погашение (ровно1успех), expired/used/revoked,
серверный expiry сессии, logout, отказ runtime выдавать/менять доступ,
отказ caller tenant/role, FORCE RLS и отсутствие plaintext в БД/audit,
два профиля и два разных КП одной публичной закупки без cross-read/write,
запрет заимствования shared pilot/reviewer credentials, fragment cleanup,
GET/scanner без погашения, actual-image browser E2E и полный release gate.
Миграция `20261023_01` добавочная. Downgrade отказывает при истории приглашений;
откат приложения сохраняет таблицы и историю. Релиз требует отдельного точного
payload с migration/API/web images, проверками, backup и rollback. Старые EIS
планы и их approvals к этому релизу не относятся.

Сборка API использует [официальный Ubuntu snapshot](https://snapshot.ubuntu.com/)
`20261021T000000Z`: исходная pinned версия исчезла из mutable apt. Список510
пакетов сохраняет исходный SHA a94c2d704b6e6f6a00ccbf644d34c7fcfcc2fb9d836e8ce15bad6ffff13fdca5;
проверка inventory не ослаблена.

## Evidence подготовки B11

Владелец root; owned files/acceptance — `tmp/beta-invitations-20261023-v33/scope.json`.
Изолированный candidate основан на принятом R4; текущий dirty checkout не выкатывается.
Scoped PostgreSQL11 PASS; web205 PASS, lint/types PASS. Два actual compiled images
прошли synthetic browser без ручных ключей: profile/КП/reload/разная прибыль,
одноразовая ссылка/GET-preview/logout, page_errors0. Это изолированная база;
приглашения реальным людям не выпускались. Экран390px визуально проверен.

Gatev4 прошёл проверки исходников/БД/web, но build-api отказал: pinned apt package
исчез из mutable archive. Официальный snapshot восстановил exact510-package SHA.
Gatev5 для source archive `0300d019c9ca3a76c9f2498636179ab31b4c44caad1f2b26762af3372bf07639`
завершён со всеми50стадиями PASS. Предыдущие неуспешные прогоны не являются release receipt.

Backup: каталог существующего дампа22Oct читается, получен свежий schema-only dump.
Новый полный data backup/полное restore НЕ выполнены: native guard требует около60GiB
свободного места, guard не обходится. Установка добавочная; app rollback сохраняет
новую schema/audit/профили/КП. При подготовке disk reserve временно снижался ниже40GiB;
восстановлен удалением unused rebuildable BuildKit cache и только двух собственных
временных preview images после итогового E2E. Production/rollback images, backups и volumes сохранены.
Окончательная установка требует повторного disk>=40GiB и exact approval.

Администратор запускает CLI из нового API image через migration-only compose overlay,
с owner environment, приватным каталогом output и явным company_id для повторной ссылки.
Установленный worker остаётся на старом image и сам этот CLI не содержит.

## Подготовка23Oct, до установки

Source archive SHA0300d019, tree0bcfcde7; trusted receipt:
`gate-state-v5/runs/release-20261023-134447-fe5ad32e8dbe/release-receipt.json` на сервере.
Все50стадий PASS: unit3837PASS/27существующих allowed skips, PG717PASS/0skip,
web205PASS/0skip,9domain doctests, Ruff/mypy/docs/lint/types/build/smoke PASS.
API `7e2b5207`, WEB `f4e6e60d`; все252Python modules source-exact, migration SHA exact.
Изменены только8API modules; остальной R4 код сохранён. Старый workerab3 умеет
читать/писать native journal после новой схемы на disposable PG (без source requests).

На принятых OCI images повторён browser E2E:2компании, без ввода ключа,
отдельные профили/КП/прибыль35000и24000, reload, used-link отказ, logout; ошибокJS0.
Screenshot390px визуально проверен. Реальная БД:44/0325200000326000113 и
223/32616494439 найдены новым API в readonly20s окружении; anonymous profile401,
business writes0/source requests0. Диагностические пробы с искусственным5s SQL
limit дали QueryCanceled в неизменённой R4 проверке целостности; они не PASS.
20s — существующий B9 readonly harness; production таймауты не менялись.
Рабочая DB role не superuser и не BYPASSRLS; owner подходит для SECURITY DEFINER.

Пакет: `tmp/beta-invitations-20261023-v33/activation-plan.json`, SHA:
`3627e90ea83b477d732817a43cd0a7bfc806a52888c42d5ff717486ba0cd926b`.
Server preflight PASS/production writes0. Guard simulations11PASS: exact payload,
missing approval, self-hash, image scope, migration identity/failure cleanup/log,
success/rollback и concurrent-edit refusal до записи/при откате. Executor35457100.
Резерв диска перед preflight восстановлен до44,518,252,544 bytes (>40GiB).
Повторный guard при установке обязателен. Полные proof SHA — в acceptance.json.

Установка только после подтверждения этого SHA: native deployment lease,
свежий schema-only dump, owner migration20261023_01, замена API/WEB в двух
существующих compose files, health/image/schema/config/cron/disk checks и audit.
Workerab3/Caddy/cron/source budgets не меняются; реальных приглашений0.
При отказе — rollback API/WEB с сохранением добавочной схемы/истории/данных.
Human approval reference указывается по фактическому сообщению, не придумывается.
После установки проверить route/health и отдельным запросом определить участников
и компании для персональных приглашений. Старые EIS approvals к B11 не применимы.

## Установка и live acceptance24Oct

Пользователь подтвердил exact SHA3627e90e. Неизменённый executor35457100
прошёл свежий preflight и native deployment lease; выполнена добавочная миграция
20261023_01, установлены API7e2b5207/WEBf4e6e60d. Status INSTALLED_HEALTH_PASS.
DB container сохранился; workerab3, cron/host223 и runtime/budget contracts прежние.
Свежий schema-only dump под lease записан с SHA в activation-audit.json.
После проверок API/web health PASS, disk43,935,539,200bytes (>40GiB).
Evidence: `tmp/beta-invitations-20261023-v33/installed-acceptance.json`,
`activation-audit.json`, `live-verification/result.json`.

На установленном Next action/API/реальной БД проверены две помеченные private
компании `beta-verification-20261024-b11-a` и `-b`. GET не расходует ссылку;
acceptBetaInvite выдаёт HttpOnly/Secure/Strict cookie и redirect/company-profile.
Повторная redemption410, профили созданны201/выбраны201/повторно прочитаны,
два разных тестовых КП одной существующей223 закупки32616494439/v2/lot1 сохранены
и прочитаны раздельно. Все17расходов явно0 — только синтетическая декларация.
Инъекция company_id422; служебная source job403; runtimeRLS чужие profile/КП0.
Private profile/quote counts общего public corpus не изменились. Logout204 и
следующий запрос401. Все тестовые приглашения отозваны; активных тестовых
приглашений и аутентифицируемых сессий0. Реальным участникам доступы не выдавались.
Тестовые immutable profile/quote/audit rows сохранены для трассировки, не удаляются.

Это native HTTP проверка установленного web action/API и БД через private network;
полный Playwright browser E2E выполнен ранее на exact accepted images в disposablePG.
Ошибки проверочного сценария сохранены: формат public action ID, отсутствующий
corpus env, непубликуемый host3000, текстовая проверка нормализованного Decimal.
Write-stage v2 сохранил обе декларации; readback-v3 проверил именно их без перезаписи.
Итоговый PASS не переименовывает предыдущие неуспешные проверки в успешные.

### Проверенная команда выдачи приглашения

Worker environment содержит owner URL, но НЕ EIS_PILOT_COMPANY/BETA_INVITE_ORIGIN.
Оба параметра передавать явно. Сначала создать приватный каталог0700 и заменить
actor/company при необходимости; повторная ссылка всегда для прежнего company_id.
Ключи участник не вводит. JSON с URL0600 передавать адресно, не в общий чат.

```sh
sudo -n docker --host unix:///var/run/docker.sock compose -p vibe-seller \
  -f /home/syurai/vibe-seller/docker-compose.server.yml \
  -f /home/syurai/vibe-seller-state/discovery-pagination-20261007/compose-release-v9.yml \
  -f /home/syurai/vibe-seller-state/beta-invitations-20261023-v33/migration-only-beta.yml \
  run --rm -T --no-deps --pull never --user "$(id -u):$(id -g)" \
  -v /home/syurai/vibe-seller-state/beta-invitations-private:/private \
  -e BETA_INVITE_ORIGIN=https://www.syurai.su \
  -e EIS_PILOT_COMPANY=local-eis-supplier worker \
  python -m procurement.api.beta_invite_admin \
  --actor-id participant-001 --issued-by beta-organizer \
  --output /private/invite-participant-001.json
```

Установку3627e90e не повторять. Следующий организационный шаг — имена участников
и распределение по компаниям; новые приглашения не являются публичной регистрацией.
