"use server";

import { revalidatePath } from "next/cache";

import { ApiError, createCase, createEvaluation } from "@/lib/procurement-api";

export type FormState = { error?: string; success?: string };

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return (
      {
        401: "Не удалось подтвердить доступ к API.",
        403: "Кейс принадлежит другой компании.",
        404: "Кейс или версия не найдены.",
        409: "Эта версия уже сохранена или запрос конфликтует с предыдущим.",
        422: "Проверьте формат данных и обязательные поля.",
      }[error.status] ?? "Сервис временно недоступен. Повторите попытку позже."
    );
  }
  return "Сервис временно недоступен. Проверьте подключение к API.";
}

export async function importCase(_: FormState, form: FormData): Promise<FormState> {
  const source = form.get("case-json");
  if (typeof source !== "string" || !source.trim()) {
    return { error: "Вставьте полный JSON-снимок кейса." };
  }
  if (source.length > 1_000_000) {
    return { error: "JSON превышает лимит пилотного импорта 1 МБ." };
  }
  try {
    await createCase(JSON.parse(source) as unknown);
    revalidatePath("/");
    return { success: "Кейс сохранён. Список обновлён." };
  } catch (error) {
    return {
      error: error instanceof SyntaxError ? "JSON не удалось прочитать." : errorText(error),
    };
  }
}

export async function evaluateCase(_: FormState, form: FormData): Promise<FormState> {
  const caseId = form.get("case-id");
  const version = form.get("version");
  if (
    typeof caseId !== "string" ||
    typeof version !== "string" ||
    !caseId ||
    !/^\d+$/.test(version)
  ) {
    return { error: "Не удалось подготовить запрос на оценку." };
  }
  try {
    await createEvaluation(caseId, version, new Date().toISOString());
    revalidatePath("/");
    return { success: "Оценка на текущее время сохранена." };
  } catch (error) {
    return { error: errorText(error) };
  }
}
