# Syurai Procurement — виртуальный тендерный отдел

Система ведёт закупочный кейс компании-поставщика от непрерывного поиска процедуры
до оплаты выигранного контракта: извлекает требования, применяет юридические и
коммерческие hard gates, ищет поставщиков, собирает КП, считает три сценария
экономики и готовит объяснимую рекомендацию.

Ключевой принцип: **ИИ извлекает и предлагает, детерминированные правила решают,
юридически значимое действие подтверждает человек**. Зелёный рейтинг не может
перекрыть запрет, `FAIL` или `UNKNOWN` по обязательному требованию.

## Текущий статус

Завершены S1 и первый серверный срез S2: доменное ядро, локальный расчёт,
PostgreSQL 16 с RLS, immutable-версии кейсов, bearer identity, audit,
идемпотентность и FastAPI. Профиль, процедура, выбранное КП и три сценария
связаны с оценкой точного снимка. Недостающий фильтр, истёкшее КП,
неподтверждённый расход или изменение данных блокируют положительное решение.
Следующий этап — первый пользовательский экран; live-статус находится в
[плане реализации](docs/15-implementation-plan.md).

- требования и provenance, товары, сертификаты, `PASS | FAIL | UNKNOWN`;
- профиль компании, география, финансовая политика и раздельные юридические /
  коммерческие запреты;
- процедура, статус подачи, точный deadline с часовым поясом и схема доставки;
- полная структура расходов и обязательные `base / realistic / conservative` сценарии;
- независимые риски, объяснимый рейтинг и deterministic recommendation gate;
- human-in-the-loop: подтверждение связано с SHA-256 точного исходящего payload;
- этапы исполнения контракта и предупреждения о сроках.
- каркас цифровых платформ: раздельные поиск поставщика и продажи «с полки»,
  проверки допуска канала с источниками и версией правил.

Это ещё не production-система: нет UI, очередей, production IAM/TLS и коннекторов
к ЕИС, ЭТП, почте, маркетплейсам, логистике и банкам.

Исходные пробелы описаны в [историческом аудите](docs/13-partner-spec-audit.md).
S1 закрывает типизированный ручной ввод КП, полноту проверок/расходов и связь
оценки со снимком. Автоматическое извлечение, актуальные нормативные rulesets,
денежный график и одноразовое исполнение approvals ещё требуют реализации.

## Запуск первого сценария

```powershell
uv sync --extra dev
uv run python -m procurement evaluate examples/paper_case.json --actor demo-operator --at 2026-09-08T12:00:00+03:00
```

Пример целиком синтетический. Команда выводит решение и сохраняет полный снимок
расчёта в `data/evaluations/`. `--at` фиксирует время для воспроизведения;
без него проверяется актуальность на текущий момент. Подробности и ограничения —
[инструкция локального расчёта](docs/16-local-case-workflow.md).

Проверено: 303 unit/API-теста, 12 PostgreSQL integration-тестов, 9 doctests,
ruff и mypy домена.

## Локальный сервер S2

Скопируйте `.env.example` в `.env`, замените оба пароля, затем выполните:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Полный контракт и команды интеграционной проверки описаны в
[инструкции PostgreSQL и API](docs/17-storage-api.md).

## Документация

| Документ | Назначение |
|---|---|
| [11-product-requirements.md](docs/11-product-requirements.md) | Нормализованное ТЗ партнёра и критерии приёмки |
| [12-requirements-traceability.md](docs/12-requirements-traceability.md) | Трассировка требований в компоненты и релизы |
| [13-partner-spec-audit.md](docs/13-partner-spec-audit.md) | Исторический аудит готовности по состоянию на 2026-09-07 |
| [14-product-agents.md](docs/14-product-agents.md) | Реестр продуктовых агентов и границы их автономии |
| [15-implementation-plan.md](docs/15-implementation-plan.md) | Актуальный порядок работ и live-статус срезов |
| [16-local-case-workflow.md](docs/16-local-case-workflow.md) | Запуск CLI, формат данных и журнал расчётов |
| [17-storage-api.md](docs/17-storage-api.md) | PostgreSQL, RLS, bearer auth и FastAPI |
| [00-vision.md](docs/00-vision.md) | Видение, границы продукта и модель решений |
| [01-domain-model.md](docs/01-domain-model.md) | Объекты и инварианты домена |
| [02-architecture.md](docs/02-architecture.md) | Целевая архитектура SaaS + Local Agent |
| [03-compliance-engine.md](docs/03-compliance-engine.md) | Методика доказательного соответствия |
| [04-economics.md](docs/04-economics.md) | Полная экономика и три сценария |
| [05-roadmap.md](docs/05-roadmap.md) | Вертикальные срезы MVP → v1 → v2 |
| [06-legal-security.md](docs/06-legal-security.md) | Юридические правила, approvals и ИБ |
| [07-research-log.md](docs/07-research-log.md) | Проверенные и непроверенные внешние факты |
| [AGENTS.md](AGENTS.md) | Правила разработки, роли владельцев и порядок выполнения задач |

HTML-файлы `08–10` — презентационные снимки исходной концепции. До их регенерации
нормативными источниками являются Markdown-документы выше. `docs/ии.docx`
сохранён как исходный архив и не является актуальной спецификацией.

## Проверка

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src/procurement/domain
PYTHONPATH=src uv run python -m pytest --doctest-modules src/procurement/domain
```

С заполненными `DATABASE_URL` и `DATABASE_ADMIN_URL` команда `pytest` также
выполняет 12 PostgreSQL integration-тестов; без них этот набор явно пропускается.
