# ADR 0049: ограниченная текстовая производная legacy DOC

Дата: 2026-10-02. Статус: принято; S142 проверен на Linux и развёрнут на VPS.

## Основание и контракт

Два полученных документа shortlist имеют OLE Word binary signature. Расширение
DOC само по себе не доказывает формат. [MS-DOC FibBase](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/26fb6c06-4e5c-4778-ab4e-edbf26a545bb)
задаёт signature, encryption flag и выбранный Table stream.

Читаем OLE Word 97–2003: WordDocument, FIB wIdent/nFib, 0Table/1Table,
directory/stream limits. VBA/Macros и encryption отклоняются до конвертера.
RTF/HTML под .doc и старые Word binary версии не объявляются поддержанными.
Olefile 0.47 проверяет структуру с DEFECT_INCORRECT и явными resource bounds.

Серверный [antiword 0.37-16 из Ubuntu Noble](https://packages.ubuntu.com/source/noble/antiword)
фиксируется в Dockerfile.api. [Руководство](https://manpages.debian.org/unstable/antiword/antiword.1.en.html)
описывает stdin, UTF-8 mapping и -w 0 (абзац на строке). Используем точный argv
`/usr/bin/antiword -t -m UTF-8.txt -w 0 -`; shell, Office, macros, hidden/deleted
revision text и remote links не запускаются. Это текстовая производная:
legacy_doc_text имеет is_lossy, результат всегда UNKNOWN/LAYOUT_NOT_VERIFIED.
Locator `antiword-0.37-16 utf8 w0 :: line N` относится к фиксированному выводу
конвертера, не к странице/абзацу оригинального Word. SHA исходных bytes остаётся
document_id. ZIP добавляет archive member prefix.

## Ограничение процесса

Linux child launcher выполняет setup в отдельном Python процессе с -I;
preexec_fn в threaded API не применяется. CPU 4/5 seconds, address space
256 MiB, file output до min(4*character limit+1,20 MiB+1), 32 file descriptors,
core dump 0, wall timeout 8 seconds. Stdout/stderr идут в TemporaryFile,
читаются bounded; частичный stdout, warning stderr, nonzero exit/invalid UTF-8
не становится evidence. Timeout/output/CPU signals дают отдельный rejection.

Child получает только HOME/ANTIWORDHOME/LANG; API/DB credentials не наследуются.
Root child сбрасывает UID/GID/groups до nobody. no_new_privs и libseccomp filter
запрещают network socket operations, fork/clone, ptrace/mount/namespaces.
[Linux seccomp contract](https://man7.org/linux/man-pages/man2/seccomp.2.html)
сохраняет фильтр после exec. Ошибка setup блокирует извлечение. Это ограничение
процесса внутри контейнера; оно не объявляется полной файловой sandbox.
Сам документ не создаёт команд/аргументов/пути. Windows без binary возвращает
UNKNOWN/CONVERTER_UNAVAILABLE после format preflight.

## Immutable версии и границы

Миграция 20261002_02 добавляет explicit eis-native-v3-doc рядом с v1/v2-xls.
Cached reanalysis S141 сохраняет bytes, receipts и прежние analyses; проверяет
exact current ref, tenant, SHA/size, сохраняет новый audit. Replay не парсит
повторно и не скачивает. Downgrade отказывает с v3 evidence, не удаляет её.

Отдельно проверяются роль документа, таблицы/колонки, поля/вложения, revision
state и полный набор требований. Native text snippets — гипотезы для review,
не утверждённые требования. Full EIS coverage и PARTICIPATE этим не достигаются.
