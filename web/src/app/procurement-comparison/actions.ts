"use server";

import { commandValid, type ComparisonReport } from "../../lib/procurement-comparison";
import { compareProcurements } from "../../lib/procurement-comparison-api";

export type ComparisonState = { error?: string; report?: ComparisonReport };

export async function compareAction(_: ComparisonState, form: FormData): Promise<ComparisonState> {
  const profile = form.get("profile");
  const cases = form.getAll("cases");
  if (typeof profile !== "string" || profile.length > 1000 || cases.length < 2 || cases.length > 5 ||
      cases.some(ref => typeof ref !== "string" || ref.length > 1000)) {
    return { error: "Выберите 2–5 разных закупок и конкретную версию профиля." };
  }
  try {
    const selection = form.get("selection_id");
    const command: unknown = { profile_ref: JSON.parse(profile), case_refs: cases.map(ref => JSON.parse(ref as string)), ...(typeof selection === "string" ? { selection_id: selection } : {}) };
    if (!commandValid(command)) return { error: "Выберите 2–5 разных закупок и конкретную версию профиля." };
    return { report: await compareProcurements(command) };
  } catch (error) {
    return { error: error instanceof SyntaxError ? "Некорректные ссылки на версии." :
      error instanceof Error && !error.message.includes("fetch") ? error.message : "Локальное API недоступно. Повторите попытку." };
  }
}
