# Syurai Procurement

Виртуальный тендерный отдел: найти процедуру, проверить требования, собрать
предложения, рассчитать экономику и подготовить контролируемое действие.
ИИ извлекает и предлагает; детерминированные правила решают; внешнее
юридически значимое действие требует exact-payload approval.

## Текущий статус

Внутренний пилот. Есть доменное ядро, PostgreSQL/API, интерфейс, обработка
документов, индекс/очереди ЕИС и ограниченный поиск поставщиков/карточек товаров.
Текущий приоритет, открытые acceptance и следующий шаг ведутся только
в [live-плане](docs/15-implementation-plan.md).

Полный охват ЕИС, полнота всего ТЗ и полный путь до КП, экономики, внешней подачи
и оплаты не подтверждены. Выпущенный отдельный механизм не означает production
готовность всего продукта. Актуальные границы — в [live-плане](docs/15-implementation-plan.md),
точные проверки выпуска — в [S228](docs/documents/110-eis-independent-requirement-review.md).

## Разработка и документация

Перед задачей: [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md),
[карта документации](docs/README.md), затем контракт нужной области.
Полная история не требуется для входа; прежний README сохранён в
[историческом снимке](docs/history/root-readme-2026-10-06.md).

## Локальный запуск

```powershell
uv sync --extra dev
uv run python -m procurement evaluate examples/paper_case.json --actor demo-operator --at 2026-09-08T12:00:00+03:00
```

Пример синтетический; фиксированное время служит воспроизведению, а не проверке
актуальности сегодня. Формат и audit — в [локальном workflow](docs/operations/16-local-case-workflow.md).

Для серверного API скопировать .env.example в .env, задать пароли и выполнить:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Настройка — в [PostgreSQL/API](docs/operations/17-storage-api.md).
Интерфейс — в [web/README.md](web/README.md), локальный поиск ЕИС — в
[контракте discovery](docs/eis/search/25-eis-tender-discovery.md),
серверный доступ — в [runbook VPS](docs/operations/28-eis-server-operations.md).

## Проверки

```powershell
uv run python scripts/check_docs.py
uv run pytest -q
uv run ruff check .
uv run mypy src/procurement/domain
uv run python -m pytest --doctest-modules src/procurement/domain -q
uv lock --check
```

В web/: `npm ci`, `npm run lint`, `npm run build`.
PostgreSQL integration требует отдельных DATABASE_URL/DATABASE_ADMIN_URL;
OCR regression — opt-in окружения. Пропущенные проверки не означают PASS.
CI-конфигурация: [.github/workflows/quality.yml](.github/workflows/quality.yml).
