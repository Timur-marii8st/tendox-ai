# Навигация backend

Общие инструкции — в [корневом AGENTS.md](../../AGENTS.md) и [CLAUDE.md](../../CLAUDE.md).
Статус и текущий срез — в [live-плане](../../docs/15-implementation-plan.md).
Перед кодом выбрать один контракт по области:

| Область | Контракт / навигация |
|---|---|
| domain/ | [Архитектура, compliance и экономика](../../docs/architecture/README.md) |
| documents/ | [Документы и независимый review](../../docs/documents/README.md) |
| sources/ | [ЕИС](../../docs/eis/README.md) или [поставщики](../../docs/suppliers/README.md) |
| storage/ и api/ | [PostgreSQL/API](../../docs/operations/17-storage-api.md) плюс контракт конкретного workflow |
| CLI и runtime | [Операции](../../docs/operations/README.md) |

Тесты искать по имени модуля в tests/, persisted сценарии — также в tests/integration/.
Не читать всю историю перед ограниченной задачей. Правила поведения не дублировать
здесь: инварианты остаются в корневых инструкциях и контракте домена.
