# Целевая архитектура

## Контуры

```text
Web UI / API
     │
Case Orchestrator ─── Policy & Legal Rules Registry
     │
     ├── Source ingestion ── ЕИС / ЭТП / сайты / exports
     ├── Document pipeline ─ native parsers / OCR / LLM extraction
     ├── Search ──────────── taxonomy / relational filters / vector index
     ├── Supplier/RFQ ────── catalog / email / marketplace adapters
     ├── Platform sales ─── eligibility / offer drafts / approved publication / orders
     ├── Deterministic core ─ eligibility / compliance / economics / decision
     ├── Application builder
     └── Contract workflow / analytics projections

PostgreSQL + object storage + event/audit log + job queue
     │ mTLS, only approved command with exact payload hash
Local Agent on customer PC ─ browser/API adapter / КЭП / execution receipt
```

## Разделение ответственности

LLM извлекает структуру, классифицирует текст, предлагает синонимы и готовит
черновики. Детерминированное ядро проверяет сроки, числа, правила, соответствие,
экономику и допустимость действия. Orchestrator управляет состоянием кейса, но
не может повысить автономию инструмента.

## Источники и коннекторы

Приоритет: официальный API → штатный export/feed → разрешённый local browser →
открытая страница. Каждый адаптер имеет:

- tenant/platform credential reference (секрет не попадает в LLM);
- terms/permission record и rate-limit policy;
- checkpoint/watermark и идемпотентный ключ;
- raw immutable snapshot и parser version;
- health, lag и contract tests.

Список площадок задаётся конфигурацией клиента. Фраза «искать везде» не даёт
разрешения нарушать условия доступа или обходить защиту.

## Хранение

- PostgreSQL: транзакционные агрегаты, версии профилей и rulesets;
- pgvector/full-text: семантический и лексический поиск;
- S3-совместимое object storage: исходные документы и версии артефактов;
- append-only audit/event stream: решения, approvals, execution receipts;
- read models/warehouse: главный экран и аналитика без нагрузки на workflow.

## Мультитенантность

`company_id` обязателен во всех агрегатах, задачах, объектах и audit events.
Нужны row-level security, tenant-scoped encryption keys/paths, RBAC и тесты на
невозможность межтенантного чтения. Модель предпочтений обучается отдельно для
каждой компании.

## Надёжность 24/7

Мониторинг — периодические идемпотентные задачи, а не бесконечный LLM-сеанс.
Очереди разделяются по источникам и приоритету deadline; retries имеют backoff и
dead-letter queue. Для каждой карточки показываются свежесть и полнота данных.

## Локальный агент

КЭП, сессии и platform cookies остаются на ПК клиента. Облако отправляет только
команду, одобренную для точного payload. Агент повторно проверяет hash, price
floor, срок approval и отображает финальный payload перед действием. Возвращает
подписанный execution receipt или ошибку; не получает полномочие `A3`.

## Цифровые платформы с первого этапа

Sourcing adapter ищет товары для нашей закупки; Platform sales adapter ведёт
предложения нашей компании для заказчика. Capability flags разделяют чтение
каталога, RFQ, публикацию, изменение оферты и принятие заказа. Регистрация на
маркетплейсе не включает все capabilities автоматически.

Rules Registry хранит проверенные нормы, реестр платформ и перечень операторов
как отдельные versioned snapshots. Проверяется дата публикации извещения,
получатель, предмет, правовое основание и логистика оператора. Для оферты нужны
tenant, версия, SKU/характеристики, цена/НДС, остаток, срок цены, документы и
условия доставки. Обновление остатка/цены создаёт новый черновик; публикация — A1.

Внешний заказ проходит дедупликацию, повторную проверку наличия и экономики,
подтверждение точных условий и общий Contract Controller. Отзыв допуска платформы
останавливает новые действия и создаёт задачу пересмотра действующих кейсов.
Отправки и receipts журналируются через transactional outbox; неопределённый
результат сети сначала сверяется на площадке, а не отправляется повторно.

Сейчас реализована только чистая модель platforms.py. Ни API операторов,
ни фоновые задания, ни outbox в репозитории ещё не существуют.
