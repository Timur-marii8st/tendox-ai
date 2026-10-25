# Сохранение накопленных изменений — 25 октября 2026

Владелец: root. Задача пользователя: проверить коммиты, сохранить все текущие
изменения и отправить их в GitHub. База: `04139a7`, ветка `main`,
remote: `Timur-marii8st/tendox-ai`. После fetch база совпадала с `origin/main`.

## Границы среза

Owned files: весь накопленный diff `main` в `src/`, `migrations/`, `scripts/`,
`tests/`, `web/`, `examples/comparison/`, `docs/`, `CLAUDE.md` и `README.md`.
Список до добавления этого отчёта: `tmp/git-cleanup-20261025/owned-files.txt`.
Срез объединяет восстановление/поиск ЕИС, профиль компании, сравнение закупок,
бета-КП и shortlist, миграции, эксплуатационные изменения и их документацию.
Локальные экспериментальные ветки сохранены; их история не переписывается.

Критерий результата: накопленные изменения сохранены в коммите `main`,
отправлены в `origin/main`, рабочее дерево чистое. Это сохранение исходников;
существующие ограничения продуктовой готовности в live-плане сохраняются.

В `web/pnpm-workspace.yaml` исправлена текстовая заглушка разрешения сборки
`unrs-resolver`: установлено булево `true`. После исправления offline install
с frozen lockfile прошёл. Сгенерированный при проверке `pnpm-lock.yaml` удалён;
существующий `package-lock.json`, используемый CI, сохранён.

## Проверки

Логи: `tmp/git-cleanup-20261025/` (локальные, исключены из Git).
Python-зависимости установлены через `uv sync --frozen --extra dev`;
`uv lock --check` PASS. Frontend проверен существующими entrypoints через Node:
`scripts/run-web-tests.mjs`, `eslint`, `next build`.

- `ruff check .`: PASS.
- `mypy src/procurement/domain`: PASS, 24 модуля.
- Domain doctests: PASS, 9 примеров.
- Python unit/API pytest: 3984 PASS, 27 SKIP, 0 FAIL; exit code 0.
- Frontend: 201 PASS, 0 FAIL, 0 SKIP; lint и production build PASS.
- Integration pytest: 5 PASS, 579 SKIP; PostgreSQL не настроен,
  optional OCR runtime отсутствует. PostgreSQL acceptance остаётся UNKNOWN.
- `check_quality_scope.py --check`: PASS; 36 frontend test files в 23 configs,
  71 PostgreSQL module в 15 изолированных группах.
- Alembic: единственный head `20261023_02`; применение к БД не проверено.
- `check_docs.py`: PASS, 298 Markdown files, 959 local links, 14 полных индексов.
- Проверка распространённых форматов credential и private key в diff:
  совпадений нет; бинарных добавлений нет.
- `git diff --check` с `core.whitespace=cr-at-eol`: PASS; учтены уже
  существующие окончания строк CRLF. Байтовое содержимое исходников сохранено.

После commit/push проверяются совпадение локального HEAD с удалённой веткой
и чистое рабочее дерево. Для PostgreSQL acceptance требуется отдельный полный
gate с изолированными БД. Серверный rollout этим срезом не выполняется.
