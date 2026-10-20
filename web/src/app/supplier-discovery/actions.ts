"use server";

import {
  ApiError,
  ConfigurationError,
  runDocumentSupplierSearch,
  type DocumentSupplierSearchRun,
} from "@/lib/procurement-api";

export type DocumentSearchState = {
  run?: DocumentSupplierSearchRun;
  error?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;

export async function executeDocumentSearch(
  _: DocumentSearchState,
  form: FormData,
): Promise<DocumentSearchState> {
  const documentId = form.get("document_id");
  const digest = form.get("plan_sha256");
  const mode = form.get("mode");
  if (
    typeof documentId !== "string" || !ID.test(documentId) ||
    typeof digest !== "string" || !SHA256.test(digest) ||
    (mode !== "AUTO" && mode !== "HTTP" && mode !== "BROWSER")
  ) {
    return { error: "План поиска некорректен. Откройте документ снова." };
  }
  try {
    return { run: await runDocumentSupplierSearch(documentId, digest, mode) };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Нет соединения с API." };
    if (error instanceof ApiError) {
      if (error.status === 409) return { error: "План устарел или в ТЗ нет однозначного товара. Обновите страницу." };
      if (error.status === 404) return { error: "Документ не найден в текущей компании." };
      if (error.status === 403) return { error: "Для запуска поиска нужна роль оператора." };
    }
    return { error: "Поиск не завершился. Результат неизвестен; попробуйте позже." };
  }
}
