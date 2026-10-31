"use server";

import { ApiError, readGosplanDetail, searchGosplan, type GosplanLaw, type GosplanSearchPage, type GosplanDetail } from "@/lib/procurement-api";

type Result<T> = { result?: T; error?: string };
function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) return "Закупка не найдена в ГосПлане.";
  return error instanceof ApiError && error.status === 429
    ? "Превышен лимит запросов. Попробуйте позже."
    : "Источник временно недоступен. Попробуйте позже.";
}
export async function searchGosplanAction(query: string, law: GosplanLaw, offset = 0): Promise<Result<GosplanSearchPage>> {
  if (!query.trim() || query.length > 120 || !["44", "223"].includes(law) || !Number.isInteger(offset) || offset < 0 || offset > 1000) return { error: "Некорректный запрос." };
  try {
    const result = await searchGosplan(query.trim(), law, offset);
    if (result.query !== query.trim() || result.law !== law || result.coverage !== "UNKNOWN" || result.items.some(row => row.law !== law || row.source_sha256 !== result.response_sha256)) throw new Error("source mismatch");
    return { result };
  } catch (error) { return { error: errorMessage(error) }; }
}
export async function readGosplanAction(law: GosplanLaw, number: string): Promise<Result<GosplanDetail>> {
  if (!((law === "44" && /^\d{19}$/.test(number)) || (law === "223" && /^\d{11}$/.test(number)))) return { error: "Некорректный номер закупки." };
  try {
    const result = await readGosplanDetail(law, number);
    if (result.law !== law || result.number !== number || result.documents.some(doc => doc.source_sha256 !== result.response_sha256)) throw new Error("source mismatch");
    return { result };
  } catch (error) { return { error: errorMessage(error) }; }
}
