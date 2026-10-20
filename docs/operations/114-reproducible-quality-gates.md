# M1 — воспроизводимый снимок и постоянные проверки

Дата: 2026-10-07. Владелец: root. Статус: M1 COMPLETE в scope локального candidate-triggered provider; приёмка и границы ниже.
Контракт программы — [16](../product/16-improvement-program.md).

## Владельцы и acceptance

Root: `scripts/package-server-release.py`, `tests/test_release_package.py`,
адаптация `tests/test_eis_pilot_runtime.py`, test-only clocks в `case_support.py`,
storage/requirement-set SQL tests и corpus tests; base pins в Dockerfiles,
`.gitattributes`, этот отчёт и live-план.
Sol: `.github/workflows/quality.yml`, `web/package.json`, `scripts/run-web-tests.mjs`,
`scripts/check_quality_scope.py`, `tests/test_quality_scope.py`; следующий bounded
slice — девять migration PG modules и `tests/integration/migration_support.py`.
Astra: независимый read-only review; Luna: контракт программы и path inventory.
Файлы владельцев не пересекаются. Зависимости: существующий рабочий код,
неизменяемые образы установленного релиза и одноразовые тестовые базы.

Acceptance: воспроизводимый архив тех же байтов; SHA каждого файла и ledger
удалений; приватные данные исключены даже если tracked; полный обязательный
набор тестов инвентаризируется; destructive PG tests используют отдельные базы;
сборка из чистого снимка и восстановление installed images проверены отдельно.
WORKTREE_SNAPSHOT не объявляется точным исходным деревом installed images.

## Текущие результаты

- Whole-repository Ruff PASS; mypy домена 21 files PASS; 9 doctests PASS.
- После исправления проверки lazy FastAPI router: 3101 unit/API PASS,
  157 skips, 210.11 s, Windows. Skips включают PostgreSQL, Linux-only,
  optional browser/OCR и symlink privilege. Это не полный обязательный gate.
- 16 scoped packaging/runtime PASS, 2 Windows symlink skips; дополнительные
  cache exclusions проверяются следующим запуском и Linux gate.
- Sol: все 29 Node test files / 18 configs, 153 tests PASS без skips;
  lint/build PASS. Real PG выполнен; обязательный набор расширен 57→60 modules.
- Packaging/release source inventory и guards проверены независимыми агентами;
  image archive load/startup PASS в узком scope; DB/live recovery NOT_PERFORMED.
  Clean Docker API/web build и network-none startup PASS; финальный полный Linux/PG
  gate PASS. Постоянный CI остаётся PENDING; архитектура — [ADR-0107](../adr/0107-candidate-triggered-quality-gate.md).

### Полный Linux/PG прогон и исправления тестовых контрактов

Frozen source `f59f3caa` / session `m1-20261007-a6046fef`: Linux JUnit —
3259 cases, 3228 PASS, 27 skips, 4 FAIL. Все 15 fresh-DB upgrades до head PASS;
тесты двух PG groups PASS, тринадцати FAIL (45 failing/error cases).
Aggregate корректно `FAIL`, complete=true; все task containers/volumes удалены
после проверки exact ID/session labels. Production не изменён.

Исправлены фикстуры календаря и независимые ограничения времени/сегментов;
два corpus test modules повторно прошли 61 Linux tests за 44.73 s.
Синтетические SQL cases с текущими wall-clock API сдвигают относительные даты;
fixed-time domain examples неизменны. Старый истёкший кейс остаётся
DO_NOT_PARTICIPATE, новый нерассмотренный — NEEDS_ANALYSIS. Mock observers
теперь требуют и проверяют company_id. CAPTCHA module перенесён в S209 group.

Четыре точных исторических release-code oracle найдены в сохранённых code
backups, проверены по SHA/AST и включены в `tests/fixtures/eis_release_baselines`.
Git `-text` сохраняет исходные bytes. Три equivalence PG modules обязательны;
прежнее временное исключение из-за отсутствия baseline снято. Только PaddleOCR
assets и отсутствие browser/E2E suite раскрываются отдельно.

Девять старых migration test modules проверены на реальном PG: реальные
guard SQL конкретных revisions в rollback-only транзакции и пустые исторические
roundtrips в отдельных fresh DBs. Новейший запрет destructive downgrade
`20261006_12` не снимается. Все проверки прошли в финальном gate ниже.

### Финальный sealed source-v2 gate

Архив SHA `45788de7784a631fe897abe87cd09bb356ae501579214b00f1bb542010bac991`;
canonical tree SHA `72e9b09f44dc5e47cf32ab736db91940c68d24152d20918d449ab46582393dff`,
1178 files. Две независимые упаковки совпали побайтово. Session
`m1-20261007-v2-b74c91`, 08:43:11–08:53:14 UTC: `PASS`, complete=true,
fatal=null, failed_steps=[]; Ruff/mypy и 9 doctests PASS.
Linux unit/API: 3260 cases = 3233 PASS + 27 explicit skips, ошибок нет.
Все 60 обязательных PostgreSQL modules / 15 groups: 608 PASS, zero skips/errors;
все 15 fresh-DB upgrades PASS. Exact-ID/session cleanup PASS, task containers,
images и listener 25432 отсутствуют. Independent archive/member SHA verification PASS.
Evidence: `tmp/improvement-program/m1-v2-evidence/` и server
`improvement-m1-20261007/gates/m1-20261007-v2-b74c91/evidence/`.
Unit PG skips отдельно покрыты матрицей; browser/Paddle остаются NOT_PERFORMED.

Audited baseline зафиксирован в отдельном managed worktree, branch
`codex/m1-release-baseline`, commit `8115d298bc54ed689337344e8278e061be7b8c12`;
Git tree `d105922f332c56711e5832e2581e00153740e216`. Это производный снимок:
1177 captured files точны, один legacy README исправляет ссылку на исключённый
пользовательский DOCX, плюс сохранён unchanged-parent `web/.gitignore`.
Runtime/build/test-policy bytes неизменны; lock check и чистый docs check
(253 Markdown / 722 links) PASS, независимый review ACCEPT. Commit не объявлен
тем же canonical source SHA; derivation — `baseline-index-receipt.json`.
Primary checkout, его исходные private документы и незакоммиченные изменения сохранены.

### Чистая сборка

Из exact frozen source построены API `sha256:d4b593a215fbd88021dd588ba5d79eb9b03f1a1d70bfd413f0045031d5bd590d`
и web `sha256:07c1eb593c05bc32f96cdce7613ec9e8e3cc5c5e334569e8bf43115c79ad7d2d`.
Build steps PASS (53.818 s / 78.079 s); оба образа прошли network-none startup
с exact-owned cleanup. Они не установлены в production. Base images зафиксированы
по фактически полученным registry digests в Dockerfiles; package locks неизменны.
Evidence: `tmp/improvement-program/clean-build-results.json`, server stage
`improvement-m1-20261007/clean-build/`. Финальная source version с исправленными
тестами имеет отдельный build/startup receipt: tree `72e9b09f`, API
`sha256:b9f54dba87b21b0bb61ac75746a33027be405b9254223c1ae1b3e6da8e52195f`, web
`sha256:a3ce8b0982a58d4cea574b2488e474a61d19b1d8a2483cbf5ac8de5c22c42b0f`.
Build PASS (36.768 s / 74.117 s), exact-image network-none startup PASS;
`clean-build-v2-results.json` / `clean-smoke-v2-results.json`, stage `clean-build-v2/`.
Эти новые образы также не установлены в production.

Evidence и короткие handoffs: `tmp/improvement-program/` (ignored/private).
Предшествующая Git history сохранена в bundle; ветка `codex/improvement-program`.
Рабочие изменения не удаляются и не выдаются за опубликованный релиз.

## Backup установленного образа и изолированный startup restore

На 2026-10-07 создан `INSTALLED_IMAGE_BACKUP` для текущих API/web images:
SHA-256 архива `2ca1b295f6b4a954a1626785e422e2014a89845e60e019db4ff234509ae2442d`,
2,040,975,360 bytes; closure проверил 177 OCI blobs. Затем тот же архив загружен
через `docker load`; API health вернул HTTP 200, web image ответил HTTP 200.
Неаутентифицированный GET `/v1/tender-discovery/runs` отдельно вернул ожидаемый
HTTP 401. Оба startup smoke runs завершились с кодом 0 при `network=none`, а ID
уже установленных production containers не изменились. Источники:
`tmp/improvement-program/installed-release.json` и
`image-restore.json`.

Это подтверждает сохранение и загрузку идентичности образов и ограниченный
startup smoke. В backup явно не входят переменные окружения, база данных,
browser state и credentials; эта проверка не выполняла восстановление БД и не
проверяла живые закупочные workflows. WORKTREE source snapshot — отдельный
артефакт: frozen tree SHA начинается `f59f3caa`, archive SHA — `952aec`, в нём
1,171 файл. Он не является точным source tree установленного образа.

Первый полный Linux/PG gate дал FAIL и сохранён как evidence выше. Clean build
и image archive load/startup PASS в описанных границах; M1 остаётся IN PROGRESS
до постоянного CI, связанного с exact source version; финальный полный gate PASS.

Следующий bounded slice: Sol owns `scripts/run_release_gate.py`,
`release_gate_receipt.py`, `release_gate_policy.json`, `tests/test_release_gate.py`;
root owns запрет legacy install/install_locked/enable-init без принятого адаптера
в двух `server-supplier-*-rollout.py` и `tests/test_release_entrypoints.py`.
Дополнительный root slice: `scripts/activate_quality_provider.py`,
`tests/test_quality_provider_activation.py`; named local-only docs inventory в
`scripts/check_docs.py` / `tests/test_docs_local_material.py`. Root 17 focused
tests PASS/Ruff PASS, независимый review ACCEPT внутри подготовки. Проверены
повреждённые байты/preconditions, stale lock, rollback одного/двух guards,
сохранение первоначальной ошибки и retry после частичной записи controller.
Установщик не выполняет Docker/config/DB/cron actions; activation NOT_PERFORMED.
Build environment уточнён после независимого review: шесть pinned PEP backend
requirements совпадают с metadata проверенного `b9f54dba` и между pyproject/lock.
Три apt packages pinned; полный sorted dpkg inventory (510 packages) обязан
совпасть с SHA `a94c2d704b6e6f6a00ccbf644d34c7fcfcc2fb9d836e8ce15bad6ffff13fdca5`.
Drift/unavailable version блокируют build. API зависимости загружаются до COPY
source, финальная установка offline/network-none; web dependency acquisition
без scripts, compile network-none. Два exact Dockerfile SHA проверяет trusted
policy. Новый real build выявил отсутствие Buildx: legacy builder не поддерживает
`RUN --network=none`; первое свидетельство FAIL сохранено. Приватный diagnostic
Buildx v0.37.2 (65,806,498 bytes, SHA `982ca20490b45ed1ec8d99795974d3d874a358f75938c9c237305010e6b7e548`)
проверен по [официальному release](https://github.com/docker/buildx/releases/tag/v0.37.2).
Docker 29.1.3/default docker driver использует BuildKit v0.26.2. Следующий FAIL
выявил динамический backend `editables`; релизный API теперь устанавливает
обычный пакет через offline `--no-editable`, с теми же шестью pinned requirements.
Повторная сборка tree `df0e3843` PASS: API 15.471s/image `27af2462`, web
64.206s/image `80c5c119`; network-none startup обоих PASS, полный controller run pending.
Evidence: `build-recipe-buildkit-2-results.json`, `build-recipe-buildkit-2-smoke.json`, `private-buildx-receipt.json`;
это build-input preflight, не full candidate acceptance. Permanent package явно
включает exact binary/config в отдельном tools scope и identity; binary не входит
в source archive. Root 22 provider/docs/refusal tests и 8 classifier tests PASS.
ZIP parametrization имеет стабильные explicit IDs; ordinal сверка отклонена,
так как позволяла подменить один параметр повторным выполнением другого.
Первый полный provider run `release-20261007-095734-d29581a22dae` дал FAIL:
3302 unit cases =3194 PASS/81 FAIL/27 skips. Private `/test` tmpfs имел implicit
noexec, что сломало synthetic shell/converter/plugin harnesses; JUnit root:root
0600 не читался host controller. Все четыре owned resources удалены, cleanup
complete=true. Evidence: `provider-v1-failure-evidence/`; архив tree `807492b4`
не получает PASS и не считается accepted candidate. Исправление v2: workers
под UID/GID host controller, exec только private `/test` с nosuid/nodev/mode0700,
запись только в private web copy; source bind остаётся RO. Dedicated real Python/
Node probe PASS (1000:1002, synthetic exec, source write refusal, umask077
reports0600 читаются controller, npm пишет private copy); полный повтор pending.
Повтор `release-20261007-110820-7982d2a81733` тоже FAIL, но unit failures 81→3:
3272 PASS/3 FAIL/27 skips. Report owner/readability исправлены; cleanup всех
четырёх owned ресурсов complete=true. Два legacy-doc synthetic converters
создавались в hardcoded noexec `/tmp`, а fixture tamper-copy сохраняла mode400.
Root исправил только эти test fixtures: используется executable TMPDIR,
owner-write добавляется только private tamper-copy. Production sandbox и четыре
исторических fixture bytes/SHA не менялись. Linux focused 17/17 PASS, zero skips;
3302 exact collection SHA `cab65be7` прежний, Ruff PASS. Evidence:
`provider-v2-failure-evidence/`, `focused-fixtures-v3-receipt.json`,
`provider-v3-collection-check.json`; полный source v3 gate ещё pending.
Full v3 `release-20261007-112006-0b02dc0a42a3` завершился FAIL после unit3302
(3275 PASS/27 known skips), doctest9 и Node153/lint/build PASS. Шесть PG groups:
385 cases, 384 PASS/1 FAIL, zero skips. Direct downgrade guard в шестой группе
не импортировал `migrations`: test runtime включал только `/workspace/src`,
без sealed root `/workspace`. Cleanup всех семи owned resources complete=true.
Следующее исправление ограничено test-runtime PYTHONPATH; API Dockerfile,
миграции и запрет потери истории не меняются. Полные 15 PG groups проверяются
отдельно перед повторным full v4; evidence `provider-v3-failure-evidence/`.
Test-runtime correction и существующий assertion приняты независимым review:
`PYTHONPATH=/workspace/src:/workspace`, runner SHA
`2ed49ebd9fd430259ef528dd8d37d5f4b5333075584497bef9eeae7b9a54f2e0`;
20 controller tests/Ruff/compile PASS, test inventory не меняется. Package v3
plan `c4c7ece02a6bd2b46d9f0f299c7ae8c866e9c29ff9fc2d7045d87083059b727a`
прошёл actual server preflight: NOT_ACTIVATED. Диагностический harness SHA
`8fd8804afa7395965cfadf83ab0b4eef05a837e458161857bd094fa1369c73b1`
проверяет все 15 PG groups и исходные exact counts/collection hashes; отдельная
in-memory проекция 34 stages не меняет permanent policy. Его schema/file/run-id
явно non-accepting: `NOT_A_RELEASE_GATE_RECEIPT`. Запущен 11:41:45 UTC против
sealed source v3 и нового trusted controller; результат и full v4 PENDING.
Focused run `pg-diagnostic-20261007-114145-d5673d49bc86` завершился 11:48:05 UTC:
15 groups/608 PASS/zero failures/errors/skips, 34 diagnostic stages; четыре
owned resources удалены. Независимо проверены 65 report hashes, все collection
IDs и исходная policy; live label searches не нашли остатков. Evidence:
`pg-diagnostic-v4-evidence/`. Это только `DIAGNOSTIC_PASS`.
Full v4 `release-20261007-114917-b83047917ea8` (11:49:17–12:02:47 UTC) — FAIL
при финальной сверке: `python-unit collection identity differs from policy`.
Unit3302 (3275 PASS/27 known skips), doctest9, Node153, все 15 PG groups608,
API/web build/startup выполнены без ошибок; usable release receipt не создан.
Cleanup одиннадцати owned resources, включая provisional images, complete=true.
Evidence `provider-v4-failure-evidence/`; source archive
`c5722667295d90512c017e1cc57e4072d9a702fc94c5a6deb14610872f9ce300`,
tree `0ca28620b1005c5c802d5ee276f5b03d583a740efb4804f776465b73c928aebf`.
Независимая начальная сверка обнаружила одинаковые 3302 IDs в Linux v3/v4;
расхождение с зафиксированным expected hash существовало до изменения
PYTHONPATH. Точная причина и новый неизбирательный full v5 остаются PENDING;
подмена expected hash без сверки полного membership недопустима. Activation
NOT_PERFORMED, условная готовность package v3 к approval отозвана.
Причина доказана независимо: Windows stdout экранировал кириллицу в 12 точных
class/test IDs файла `test_document_ocr.py`; path normalization этих escaped
строк дала прежний expected `cab65be7`. Применение ASCII/backslashreplace к
Linux collection воспроизводит этот hash точно. Native UTF-8 Linux collection
и JUnit v3/v4 имеют одинаковые 3302 IDs/hash
`c2d871a5c799680ec845e8a12d9254b39adb820391def2ca77a0e52f2f4c58f0`.
Следующий bounded fix меняет только unit expectation и версию policy; exact ID
enforcement, scope, count и skip allowlist сохраняются. Новый full v5 обязателен.
Policy `2026-10-07.2` принята независимым exact-diff review: только version и
unit expectation изменились; raw SHA
`01f7db10d9a78bd2058eb2c03c299512020d26725e0f3632e9e211dbfff4a10f`,
canonical SHA `f4d17fa49f6550a5a476e6d10ba8e4c425a9323e6a8d7a033953bb7296ba1efe`.
Fresh Windows subprocess с explicit UTF-8 даёт те же 3302 exact IDs, что Linux;
evidence `provider-v5-utf8-collection.json` / `.log`. Ни один предыдущий FAIL
не преобразован в PASS; full v5 и activation остаются PENDING.
Package v4 plan
`b025eecb48cf5b0ea5c7b434b9fb2d4f0a83bc873656c81297a0e1ed7b996f50`,
bundle `03abb8b05808fd2b679a0b5557e5ae917e976ad761e6451427d273d7d55eb2aa`
прошёл actual server preflight `PREFLIGHT_PASS; NOT_ACTIVATED`. Новый private
trusted preparation использует policy `.2`; installer/tool/guard bytes прежние.
Full v5 `release-20261007-121512-94dd68d23b4a` (12:15:12–12:27:28 UTC) создал
типизированный `release-receipt.json`: PASS/complete=true, все 50 required stages.
JUnit3919 =3892 PASS/27 exact known skips, включая doctest9 и PG608 в 15 fresh
groups без skips; Node153 PASS без skips. Docs/lock/Ruff/mypy/lint/build/startup
PASS. Source archive
`88950ba5bbb6d9cc38d67389f7571f404047045d94ecf68691f8e9c9e0e9e2e1`,
tree `40d04da9f8f52ae9a672fbe4b3b383dfd708157d9116b30e23e55d944b7d5ea9`,
1189 files; manifest
`2df6976f8b6efed4016a603dcad34eff659d78817f26d08b594ec9d6d714436e`.
API/worker image `12f41e054f4137e6032aa42ffd1f8929e74c5b42ad8e0cd831bf5d55d1ac606a`,
web `2cd6e22bf33c1d865cbfaf803e055bd9e40b2ecec9fc2dce28b188d70d6d5da0`;
девять disposable resources verified/removed, два accepted images сохранены.
Evidence `provider-v5-evidence/`; независимый финальный audit
`provider-v5-independent-review.json` — `PASS_TECHNICAL_PREPARATION_ONLY`, SHA
`87ac6424d3b86d587a53d58abc928288ba0a1f03bbd1ce5af59ec3026b7c5152`.
Проверены 89 report hashes, exact 50 stages/17 XML, source/recipe/artifact IDs,
typed verifier и production fingerprints. Повторные live queries использовали
фактический label `com.syurai.release-gate.run`: v4 и PG diagnostic без
остатков, v5 без контейнеров/сетей и с двумя сохранёнными accepted images.
Ранние reviewer queries с prototype label `com.syurai.quality-gate.session`
не доказывали cleanup permanent controller; исправленная независимая проверка
заменяет именно эти live-filter claims, не меняя receipt cleanup evidence.
Это preinstallation candidate receipt; actual activation, два fresh full installed
runs и четыре installed refusals ещё не выполнены. M1 не объявлен закрытым.
Exact 1189 archived files закоммичены в managed branch
`codex/m1-release-baseline`: commit `9bffe2c9e979aa922af340f8793a97786a0f28ef`,
Git tree `237f91f5a35e8758056d6f203acbc1eda5d24bf6`; отдельно сохранён parent
`web/.gitignore`. Git tree и source tree SHA — разные виды идентификатора.
Обновления этого отчёта и operator runbook после sealing — doc-only derivation,
не байты receipt-bound source v5. Архив и receipt сохраняются неизменными.

Перед активацией обнаружено: обычный запуск Python может создать `__pycache__`
в immutable release и нарушить exact six-file inventory. Контракт запуска
trusted controller/verifier — `python3 -B`; allowlist не расширяется.
Свежий server probe `bytecode-bundle-probe-v1/result.json` — focused PASS:
точные шесть файлов/hash/modes совпадают до и после `--help` и verifier import,
`sys.dont_write_bytecode=true`, cache отсутствует. Probe SHA
`e8947e24ec19a705e1a11e5ee8df22547c5114e9c418f259b35fe4e8027a52d5`
принят независимым review. Это `NOT_INSTALLED; NOT_FULL_GATE`; перед и после
каждого из двух installed runs требуется повторная exact six-file проверка.

Current-artifact recovery v5, session `recovery-a76433e3c3570e8b1c232b26`,
остановился с `FAIL` до load/create: `DOCKER_CONFIG_ID_UNEXPECTED:8a15a414…`.
Экспортирован private archive 1582686208 bytes; result и archive сохранены.
Read-only archive/inspect сверка установила: accepted image IDs — OCI index
digests, terminal runtime config IDs — отдельные digests. Каждый index содержит
amd64 runtime manifest и attestation; Docker manifest указывает runtime config
и ordered layers. Старый диагностический validator ошибочно сравнивал config
с root index ID. Исправление должно проверять full tag → pinned root index →
runtime/attestation manifests → configs/layers и соответствующий Docker manifest;
незавершённая проверка не объявлена восстановлением. Disposable resources не создавались,
cleanup.complete=true с пустым inventory; accepted images и production не менялись.
Evidence `artifact-recovery-v5/result.json`; новая попытка требует отдельного
private output, exact identity proof и независимого review.
Независимое metadata proof `recovery-v5-oci-diagnosis.json`, SHA
`1fc764461986a72efbdf861d9aa2518530d8d19c6b07b788eef97a231a8db38c`,
подтверждает root/manifests/config digests, ordered descriptors и layer member
presence/sizes; оно само не подтверждает layer contents или весь archive hash.

Новая recovery v5b `recovery-9d9d4df937a155c69732e118`
(13:04:22–13:05:16 UTC) — actual PASS: fresh export, полная проверка archive,
load того же archive и два network-none startup smokes PASS. Archive
`829c818103037d4ed89d1fd764e23f6ea048f969de2007e583b9850368366dd1`,
1582686208 bytes, 41 regular files, все 38 blobs проверены и точно связаны с
двумя receipt-pinned OCI roots/configs/ordered layers/tags. API/worker и web IDs
до export, после load и после cleanup совпадают с v5 receipt. Два disposable
контейнера без ports/mounts/explicit env, 512MiB/1 CPU каждый, identity verified
и removed с authoritative absence; cleanup.complete=true. Result SHA
`b0d4268a34875db9f88404852ecc97f3f7c0c29cfbb86e6fd049ee811fcafbe1`.
Harness SHA `211be98ea89758997ab8131306f86d376c85b9e7057a70d53f8071922b714ba2`:
11 focused tests/Ruff PASS, independent code review ACCEPT. Evidence
`artifact-recovery-v5b-result.json` / `artifact-recovery-v5b-evidence/`.
Independent actual-run audit `recovery-v5b-independent-review.json` —
`PASS_ARTIFACT_RECOVERY_ONLY`, SHA
`447a2948bced30bd11f9bbcd78ef0211d8efc161835257f36c5789e1c569a606`:
archive/log hashes и closure проверены повторно; accepted images/tags live
совпадают; exact ID/name и правильный session label подтверждают отсутствие
контейнеров/сетей/volumes и новых image resources. Production IDs/images/running,
compose и оба before-guard hashes не изменились; current pointer отсутствует.
Поля sandbox/exit/provisional identity подтверждены inspection из pinned result,
полученного reviewed harness; исторические события независимо NOT_REOBSERVED,
нового прямого наблюдения уже удалённых контейнеров не заявляется.
Это восстановление image artifacts,
не DB restore, full release receipt или разрешение deployment; первый FAIL сохранён.
Default server package-v4 preflight после recovery снова
`PREFLIGHT_PASS; NOT_ACTIVATED`; installer и plan SHA совпадают с exact action.
Acceptance: неизбирательный автоматический pipeline при каждой submission,
полный policy/scope и exact source/artifact receipt, fail-closed повреждение,
пропуск, неизвестный policy или незавершённый run; два независимых полных запуска
и отдельная проверка установленного provider. Архитектура принята, activation
NOT_PERFORMED; локальный run identity уточнён в программе 16, scope не уменьшен.

Постоянный hosted CI маршрут пока не подтверждён: у локального checkout и
server checkout нет настроенного Git remote, поэтому доступность/настройка
hosted runner остаётся открытым вопросом; успешного remote workflow run нет.

При первом запуске вспомогательная проверка не нашла remote. Первый smoke probe
обратился к несуществующему search route и получил 404; затем его исправили на
`/runs`. Health route не менялся. Эти ошибки относились к диагностическим
инструментам, не к отказу продукта.

## Фактическая активация M1 — installed acceptance PENDING

После предъявления exact action JSON
`858e7b2216928c9c4beb9054afdce03e03cac4ed054d1b7b3657eb5f1facd1c4`
человек прямо подтвердил «потдверждаю»; отдельный record
`human-activation-approval-v4.json` сохраняет scope/plan/installer identity.
Исходный reviewed JSON с историческим received=false не изменён.
Перед исполнением повторно проверены installer/plan/before-guards SHA и
default server preflight. Actual installer returned
`INSTALLED; WORKFLOW_ACCEPTANCE_PENDING`, plan `b025eecb…`, bundle `03abb8b…`.
Server audit/backups: `/home/syurai/vibe-seller-state/quality-provider/activations/b025eecb48cf5b0e-e1e59ccdfef2/`;
local result `provider-activation-v4-result.json`. Изменены только provider files,
current pointer и два reviewed operational guards; runtime_changes=[] в record.
Actual installed refusal probe `4751da72…` прошёл четыре проверки:
browser install/install_locked/enable_init и CAPTCHA install.
Scope `POST_ACTIVATION_INSTALLED_READ_ONLY`, guards имеют exact after-SHA;
lease/loader/Docker/file mutations forbidden and not reached. Evidence
`provider-installed-refusals-v4-result.json`; это installed proof, отдельно
от прежней проверки package copy. Independent installed identity audit
`provider-installed-independent-review.json` —
`PASS_INSTALLED_IDENTITY_ONLY_WORKFLOW_ACCEPTANCE_PENDING`, SHA
`f0104f9f0ac60ba72c88a4ea5b399d58afa01a2d65e764ea7d5d0c3210651ae1`.
Проверены exact six-file inventory/hashes/modes, private dirs и отсутствие
cache; current pointer0600, exact after-guard/before-backup hashes, audit
plan/result/2backups0600, отсутствие lock/failure files. Actual guard mode0664
сохранён; независимый prior-mode comparison не заявлен. Production fingerprints
и compose совпадают с предыдущим audit. Два полных свежих installed-command
runs и их independent receipts/cleanup audit остаются незавершёнными. Первый
installed run `release-20261007-135738-fe79f5d192ca` начат через опубликованный
controller; ordinal1 state `provider-installed-state-1`, второй ordinal имеет
отдельный `provider-installed-state-2` и стартует последовательно после первого.
Launcher SHA `177319ba3caadcfcd4fcf6a318658f1af4dc1e06d7860bf62c50f5ea0dd9c82e`:
9 focused tests/Ruff и независимые 3 negative branches PASS; review
`installed-launcher-independent-review.json`, SHA
`cbcfe6055d1255a11720d44fe62f78fa6fe5e82a84653ad3fa511b52c6682b7d`.
Exact six-file/current pointer/source proof проверяется перед и после каждого;
все Python invocations `-B`, без stage selection/reuse/daemon/cron. Wrapper raw
exit не является typed acceptance. Dispatch PID2598557 подтверждён live;
в начале run1 RUNNING, run2 PENDING; actual результаты фиксируются отдельно.
M1 открыт.

Первый installed run завершён 13:57:38–14:09:47 UTC: полный typed PASS,
50/50 stages, 17 XML3919=3892PASS/27 known skips (PG608/15groups zero skips),
Node153 zero skips. Receipt SHA
`b95eef8f8957282ed8a663cbcc2ae5de42c4577080b0ec143d0c5e68b3864e7a`.
Source archive/tree/manifest совпадают с immutable v5, current six-file proof
до/после совпадает. Новые clean-built API/worker
`c600128e8e7a19381218e3ef8f9eb98848356c7fe87741b585068ade59e42e75`, web
`9cd4a560f267d28afdff14908848ee9f5a979352b6cd0632d5c010cead98224d`;
девять disposable resources удалены, два accepted images сохранены.
Independent audit `provider-installed-run-1-review.json` PASS, SHA
`38f4457e0c0c04a2647595bd9ced32cb45a18c782af0f866ecdf52a3e40b16ad`:
installed verifier, 89 hashes, source/collection/execution/recipe/live exact
cleanup и неизменные production fingerprints/guards/current подтверждены.
Evidence `provider-installed-run-1-evidence/`; scp всей receipt/reports/logs и
wrapper execution завершён exit0. Второй run
`release-20261007-140948-4cdf2036cdb2` стартовал автоматически на отдельном state2;
Он завершён 14:09:48–14:21:55 UTC; receipt сообщает complete PASS, 50 stages,
17 XML3919=3892PASS/27 known skips, raw controller exit0. Receipt SHA
`9180e99a122270d53c8a02a19e03528699a88f39acce0703709e5958163a0c12`;
полные receipt/reports/logs и wrapper execution сохранены в
`provider-installed-run-2-evidence/`, transport exit0. Pre/post bundle proof
совпадает; это capture, независимый typed audit ещё ожидается. Master result
`provider-installed-double-launch-v4-evidence/result.json` подтверждает два
последовательных завершённых запуска и явно не выдаёт typed acceptance.
Первый PASS и reported второй PASS сами по себе не закрывают M1.

## Приёмка M1 — два полных installed runs независимо PASS

Root принимает M1 по программе 16 и ADR0107 после независимого второго audit
`provider-installed-run-2-review.json`, SHA
`b5a896338afadb367c857381f23108843300c95452836f2ffcbf8f3540f64de6`.
Controller run2 завершён 14:21:54 UTC, wrapper — 14:21:55 UTC. Installed trusted
verifier, 50 stages, 89 report hashes, 1189 source files и точные collections
подтверждены независимо; состав PASS/skips совпадает с run1. Новые API/worker
`df390b2046ae4edc433999f55f2be9fc61866fe7d7b692a2d8f362ce0e3ad66f`, web
`902d723c97914dd5bd489f361d86a58f2a304a58369c15c7641cc7df1844c7e9`
проверены live. Девять exact disposable resources отсутствуют; правильный
run-label оставляет только два accepted images. Before/after six-file/current
proof совпадает, guards/production IDs/images/compose неизменны.

Независимый M1 checklist подтвердил все 1189 bytes и executable modes архива
в commit `9bffe2c9e979aa922af340f8793a97786a0f28ef`, tree
`237f91f5a35e8758056d6f203acbc1eda5d24bf6`; единственный дополнительный файл —
неизменённый parent `web/.gitignore`. Активация, четыре installed refusals,
два автоматических fresh full workflows, clean build/startup и архивный
export/load/startup v5b дают acceptance внутри опубликованного local-provider
контракта. Recovery использует preparation images `12f41e…`/`2cd6e2…` того же
immutable v5 candidate; экспорт новых run1/run2 images не заявляется.

Исторические FAIL и PENDING выше сохраняют последовательность evidence.
После тестов изменена только документация; её derivation не является новым
receipt-bound source. Hosted PR/push CI, приложение/DB/cron deployment, DB restore,
browser/Paddle E2E и качество/полнота поиска этим milestone не подтверждены.
Следующий milestone M2 фиксирует эталон поиска и baseline метрик.

## Команды воспроизведения

`python scripts/package-server-release.py --output tmp/improvement-program/source-snapshot.tar.gz`
создаёт deterministic TAR/GZIP и `release-manifest.json` внутри него.
Manifest содержит source kind, Git context, paths/modes/bytes/SHA, tree SHA и
deleted paths. Gzip/tar metadata нормализованы; опубликование атомарное.
Одинаковый captured payload даёт одинаковые bytes; Git context не доказывает
атомарность всего меняющегося checkout. Исторические пользовательские документы
сохраняются в workspace, но не входят в deployable source bundle.

`python scripts/check_quality_scope.py --check` проверяет классификацию.
`npm --prefix web test` запускает все compiled Node wire/render suites.
`python scripts/check_quality_scope.py --postgres-matrix` описывает изолированные
группы. Реальные PG запускаются только с одноразовым marker, точными совпадающими
DSNs без query/fragment и `--require-postgres`; skips обязательных тестов — FAIL.
Vendored release-code baselines проверяются по SHA; OCR/browser assets раскрываются отдельно.
