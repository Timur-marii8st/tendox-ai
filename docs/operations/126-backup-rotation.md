# Ротация резервных копий PostgreSQL

24.10.2026. Owner root. INSTALLED 10:48:51UTC; первый production cycle PASS11:53:04UTC.
Контракт: пользователь разрешил автоматическую ротацию после успешного создания
новой копии, сохраняя две последние проверенные и исходную.
Эксплуатационный вход — [28](28-eis-server-operations.md); [live-план](../15-implementation-plan.md).
Owned: scripts/server-backup.sh, scripts/server-backup.py, tests/test_server_backup.py,
этот отчёт, operations/28, operations/README и live-план. Evidence:tmp/eis-backup-rotation-20261024/.

## Поведение

Прежний shell entrypoint запускает стандартную Python-программу. Новый helper нужен
для проверяемого retention manifest, identities и fail-closed audit; прежний shell
умел только создавать дамп и читать оглавление. Cron остаётся03:20MSK ежедневно.
Один server-backup.lock удерживается на всё создание, проверку и удаление.
Недостаток места DBsize+40GiB блокирует создание; старые копии не удаляются,
чтобы освободить место перед новым бэкапом.

Новый pg_dump пишется в приватный временный файл, fsync, затем pg_restore полностью
декодирует данные в /dev/null. Это не восстановление в новую БД и не проверка
прикладных инвариантов восстановленной БД. SHA256 и filesystem identity связывают
проверенные байты; успешный архив публикуется атомарно без перезаписи файла.
Предыдущая самая свежая копия также полностью читается и хешируется при каждом
запуске. Ошибка её проверки сохраняет новый архив и все старые, ротация блокируется.

Хранятся новая и предыдущая проверенные копии, плюс исходная
procurement-20260927T202610Z.dump с pinned SHA
`a51b9165049995110ae1ea44e3ec077e2050b0afe78d309e6bedfb5a95d1657d`.
На первоначальном наборе без предыдущей копии ничего не удаляется.
Ротация касается только регулярных procurement-YYYYMMDDTHHMMSSZ.dump в backups.
Другие архивы, temporary files, evidence, Docker volumes/images и Forgejo не входят.
Symlinks, hardlinks, будущие даты, изменённые identities/набор файлов блокируют запуск
или удаление. Имя исходной копии фиксировано, не определяется по oldest mtime.

До первого unlink сохраняется durable неизменяемый tenant-scoped manifest и
PREPARED audit EIS_BACKUP_ROTATION в PostgreSQL. После каждого unlink — fsync каталога
и локальная запись удалённого identity; после всех удалений — COMPLETED receipt/audit.
При audit отказе до удаления все старые файлы сохраняются. При сбое после отдельного
unlink оставшиеся старые сохраняются; проверенная пара и исходная не входят в delete.
Повторный запуск сначала создаёт новую копию; отдельного prune-only режима нет.
Backup охватывает installation PostgreSQL; metadata/audit принадлежат операторскому
company_id local-eis-supplier. Содержимое БД/токены в журналы не выводятся.

Crash между hard-link публикацией и unlink temporary может оставить st_nlink=2;
следующий запуск откажет безопасно. Оператор сверяет inode/SHA и обе ссылки,
убирает только подтверждённую временную ссылку, затем повторяет обычное создание.
При других частичных сбоях сверять plan/completed/deleted receipts и PG audit;
не запускать ручное массовое удаление. Плановая ротация не заменяет off-host backup.

## Проверка и выпуск

22unit cases PASS: повторная ротация, dump/verify/audit отказ, corrupted previous,
изменение keep/delete/original, чужой новый файл, symlink, отсутствующий/изменённый
original, future date, collision, reserve, concurrent lock, plan/journal write failure.
Независимые runtime/adapter review PASS; 11adapter cases PASS (rollback и legacy guard).
Trusted gate release-20261024-094017-0a6c198d5111:50/50PASS,
Python3929PASS/27SKIP; PG718PASS; web205PASS; builds/smokes/cleanup PASS.
Source archive9efdcae2/tree754c8c16/manifest3399d35a; exact receipt в evidence.
План eeeeffac48e2c552f46f97be422462878d3add8292ac80bc8ba02ac195a01a42
установил только scripts/server-backup.py и server-backup.sh под deployment/backup locks.
Перед заменой исключены старый процесс, временный дамп и окно cron03:15–03:25MSK.
Host tree77→78; schema20261023_01/images/config/cron сохранены. Tenant activation audit PASS.
Первый реальный запуск20261024T111414Z:BACKUP_OK/exit0, завершён11:53:04UTC.
Дамп создавался около28мин; полный цикл с чтением и SHA занял38мин50с.
Проверено сохранение точных identities нового/предыдущего/original, originalSHA,
installed bytes/modes и неизменного cron. PG audit PREPARED/COMPLETED совпадает
с completed receipt. Evidence:production-acceptance.json и20261024T111414Z.*.json.

Сохранено:
- procurement-20261024T111414Z.dump:21,460,962,137bytes;
- procurement-20261022T002001Z.dump:17,715,973,054bytes;
- procurement-20260927T202610Z.dump:32,057,804bytes, исходная.

Удалён только procurement-20261016T002001Z.dump:13,877,507,493bytes(12.92GiB).
После нового бэкапа и ротации free191.78GiB. Следующий cron03:20MSK ещё не наблюдался;
он вызывает тот же успешно проверенный entrypoint. Автоматическая ротация включена.
