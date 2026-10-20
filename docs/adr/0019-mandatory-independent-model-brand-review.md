# ADR-0019: обязательный независимый review model→brand catalog

Дата: 2026-09-16  
Статус: принято

## Контекст

ADR-0017 ввёл раздельные роли автора и reviewer, append-only proposal/decision и
запрет self-approval. Одновременно публичный `POST /v1/model-brand-catalogs`
временно позволял reviewer опубликовать catalog без proposal. Поэтому наличие
роли reviewer не доказывало независимость решения и оставляло обход основного
workflow.

## Решение

Публичная публикация model→brand catalog выполняется только переходом
`DRAFT → APPROVED` через `POST /v1/model-brand-reviews/{id}/decision`. Автор
proposal и reviewer должны различаться. Прямой catalog POST удаляется из API.

Внутренний repository-метод хранения catalog остаётся реализационной деталью
атомарного approval и не является отдельным полномочием клиента. Историческим
catalog не приписывается независимый review задним числом.

## Последствия

- каждый новый searchable catalog имеет proposal и терминальное решение;
- reviewer не может одновременно создать и утвердить новый catalog через API;
- клиенты прямого import path должны перейти на proposal/decision;
- чтение последнего действующего catalog и exact evidence остаются без изменений;
- проверка атомарности и RLS требует обязательного PostgreSQL integration gate.

## Альтернативы

- Оставить reviewer-only import — отклонено: роль не доказывает независимость.
- Создавать одобренный proposal одним запросом — отклонено: автор и решение снова
  сливаются в одно действие.
- Пометить старые catalog как независимо согласованные — отклонено: такого
  evidence у них нет.
