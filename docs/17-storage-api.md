# Хранение и API — S2

Статус: **первый серверный срез завершён 2026-09-08**.

## Цель

Сохранить immutable-версии `ProcurementCase`, получить их через аутентифицированный
API и воспроизводимо записать оценку вместе с audit. В S2 нет отправки RFQ,
заявки, ставки или другого внешнего действия.

## Модель доверия

Bearer-ключ определяет `company_id` и `actor_id` на сервере. Заголовок или
query-параметр с tenant не является аутентификацией. Тело кейса сверяется с
tenant ключа; запрос чужого идентификатора возвращает тот же `404`, что
отсутствующий объект.

PostgreSQL применяет RLS по transaction-local `app.company_id`. Репозиторий
ставит tenant-контекст в каждой транзакции. Runtime-роль `procurement_app` не
владеет таблицами и не имеет `BYPASSRLS`; миграции выполняет отдельный владелец.
Проверка только в Python недостаточна.

Ключ хранится как SHA-256 digest, исходное значение БД не хранит и API не
логирует. Для production потребуется внешний secret manager и процедура ротации;
локальный bootstrap S2 предназначен только для разработки.

## Локальная БД

1. Скопировать `.env.example` в `.env` и задать два разных локальных пароля.
2. Запустить `docker compose up -d postgres`.
3. Выполнить миграции через `DATABASE_ADMIN_URL`.
4. Запускать приложение и интеграционные тесты через runtime `DATABASE_URL`.

Compose публикует PostgreSQL только на `127.0.0.1`. Инициализационный скрипт
создаёт runtime-роль только при первом создании volume. Изменение пароля в `.env`
после этого не меняет роль автоматически. `.env` исключён из Git.

Владельческое подключение обходит RLS и не используется приложением. Успешные
тесты через owner URL не являются доказательством tenant isolation.

Команды после заполнения `.env`:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

Bootstrap выводит новый bearer secret один раз. Его нельзя помещать в Git,
документацию, URL или тело кейса. `DATABASE_ADMIN_URL` нужен миграции/bootstrap,
а сервер использует только `DATABASE_URL` runtime-роли.

## Контракт API

- `GET /health` — проверка процесса без раскрытия конфигурации;
- `POST /v1/cases` — immutable-сохранение версии кейса;
- `GET /v1/cases/{case_id}/versions/{version}` — точная версия своего tenant;
- `GET /v1/cases` — ограниченный список с cursor;
- `POST /v1/cases/{case_id}/versions/{version}/evaluations` — сервер загружает
  снимок, рассчитывает рекомендацию на timezone-aware момент и атомарно пишет audit.

Записи требуют `Idempotency-Key`. Повтор с тем же ключом и payload возвращает
исходный результат; другой payload — конфликт. Клиент не передаёт готовую
рекомендацию, actor или company для audit.

## Проверка и границы

Интеграционный набор запускается только с двумя URL и проверяет приложение через
runtime non-owner role:

```powershell
uv run pytest tests/integration -q
```

На PostgreSQL 16 проходят 12 тестов: RLS и guessed-ID isolation, immutable
UPDATE/DELETE, отсутствие чтения digest runtime-ролью, глобальная bearer auth,
конкурентная идемпотентность, cursor, точный JSON/Decimal roundtrip, атомарная
evaluation + audit и сквозной HTTP-сценарий.

API в S2 не доказывает production security: TLS, rate limits, ротация ключей,
централизованные логи и deployment secrets относятся к следующим операционным
срезам. Снимок кейса целиком immutable; отдельные independently edited версии
профиля и КП появятся только вместе с самостоятельными workflow их изменения.
