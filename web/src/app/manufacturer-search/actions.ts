"use server";

import { revalidatePath } from "next/cache";

import { ApiError, ConfigurationError, createManufacturerSearch } from "@/lib/procurement-api";
import type { ManufacturerSearchReport } from "@/lib/manufacturer-search";

export type ManufacturerSearchFormState = { error?: string; report?: ManufacturerSearchReport };

export async function startManufacturerSearch(_: ManufacturerSearchFormState, form: FormData): Promise<ManufacturerSearchFormState> {
  const permitted = new Set(["query", "command-id"]);
  for (const [name] of form.entries()) if (!permitted.has(name) && !name.startsWith("$ACTION_")) return { error: "Форма содержит недопустимое поле." };
  const values = form.getAll("query");
  const commandValues = form.getAll("command-id");
  const query = values.length === 1 && typeof values[0] === "string" ? values[0].trim().replace(/\s+/g, " ") : "";
  const commandId = commandValues.length === 1 && typeof commandValues[0] === "string" ? commandValues[0] : "";
  if (!query || query.length > 80 || query.split(" ").length > 5) return { error: "Введите от одного до пяти слов, не более 80 символов." };
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(commandId)) return { error: "Идентификатор команды поиска некорректен." };
  try {
    const saved = await createManufacturerSearch({ command_id: commandId, query });
    revalidatePath("/manufacturer-search");
    return { report: saved.report };
  } catch (error) {
    if (error instanceof ApiError) {
      const message = { 403: "Нужна роль оператора поиска.", 409: "Эта команда уже связана с другим запросом.", 422: "API отклонил запрос поиска.", 429: "Лимит поиска исчерпан. Повторите не раньше чем через 15 минут." }[error.status];
      return { error: message ?? "Поиск временно недоступен. Результат неизвестен." };
    }
    return { error: error instanceof ConfigurationError ? "Поиск производителей не настроен на сервере." : "Поиск временно недоступен. Результат неизвестен." };
  }
}
