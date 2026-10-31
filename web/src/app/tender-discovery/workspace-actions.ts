"use server";

import { type TenderLaw, type TenderLawFilter, type WorkspaceResult } from "@/lib/tender-workspace";
import { ApiError, searchGlobalPrice, readTenderNavigation } from "@/lib/procurement-api";
import {
  loadIndexed223SearchPage,
  loadIndexedSearchPage,
  searchIndexed,
  searchIndexed223,
} from "./actions";

/** Один пользовательский запрос; независимые снимки и ошибки каждого закона. */
export async function searchWorkspace(query: string, law: TenderLawFilter): Promise<WorkspaceResult> {
  if (typeof query !== "string" || !query.trim() || query.length > 120 ||
      !["all", "44", "223"].includes(law)) {
    return { query: "", law: "all", error: "Укажите товар до 120 символов и выберите закон." };
  }
  const normalized = query.trim();
  const form = new FormData();
  form.set("query", normalized);
  form.set("search_scope", "NOT_EXPIRED_OR_UNKNOWN");
  // Без refresh: поиск не ставит загрузку ЕИС в очередь и не меняет данные.
  const [part44, part223] = await Promise.allSettled([
    law === "223" ? Promise.resolve(undefined) : searchIndexed({}, form),
    law === "44" ? Promise.resolve(undefined) : searchIndexed223({}, form),
  ]);
  const result: WorkspaceResult = { query: normalized, law };
  if (law !== "223") {
    if (part44.status === "fulfilled" && part44.value) {
      result.result44 = part44.value.result;
      result.error44 = part44.value.error;
    } else result.error44 = "Не удалось прочитать результаты 44-ФЗ. Повторите поиск.";
  }
  if (law !== "44") {
    if (part223.status === "fulfilled" && part223.value) {
      result.result223 = part223.value.result;
      result.error223 = part223.value.error;
    } else result.error223 = "Не удалось прочитать результаты 223-ФЗ. Повторите поиск.";
  }
  return result;
}

/** Продолжение только одного снимка; курсор другого закона не подставляется. */
export async function loadWorkspacePage(
  query: string, law: TenderLaw, cursor: string,
): Promise<WorkspaceResult & { restartRequired?: boolean }> {
  if (typeof query !== "string" || !query.trim() || query.length > 120 ||
      (law !== "44" && law !== "223") || typeof cursor !== "string" ||
      !/^[A-Za-z0-9_-]{1,2048}$/.test(cursor)) {
    return { query: "", law: "all", error: "Некорректное продолжение поиска.", restartRequired: true };
  }
  const normalized = query.trim();
  try {
    if (law === "44") {
      const next = await loadIndexedSearchPage(normalized, "NOT_EXPIRED_OR_UNKNOWN", cursor);
      return { query: normalized, law, result44: next.result, error44: next.error, restartRequired: next.restartRequired };
    }
    const next = await loadIndexed223SearchPage(normalized, cursor);
    return { query: normalized, law, result223: next.result, error223: next.error, restartRequired: next.restartRequired };
  } catch {
    return { query: normalized, law, ...(law === "44"
      ? { error44: "Не удалось загрузить продолжение 44-ФЗ. Попробуйте ещё раз." }
      : { error223: "Не удалось загрузить продолжение 223-ФЗ. Попробуйте ещё раз." }) };
  }
}


export type WorkspaceNavigationRef = { id: string; law: TenderLaw; number: string; version: number; sha256: string };

/** Cached navigation is optional enrichment; the initial list must not wait for it. */
export async function enrichWorkspaceNavigation(refs: WorkspaceNavigationRef[]): Promise<{ navigation: NonNullable<WorkspaceResult["navigation"]>; failed: number }> {
  if (!Array.isArray(refs) || refs.length > 200 || refs.some(ref => !ref ||
    !["44", "223"].includes(ref.law) || typeof ref.id !== "string" || ref.id.length > 200 ||
    typeof ref.number !== "string" || !(ref.law === "44" ? /^\d{19}$/ : /^\d{11}$/).test(ref.number) ||
    !Number.isSafeInteger(ref.version) || ref.version < 1 || typeof ref.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(ref.sha256) ||
    ref.id !== `${ref.law}:${ref.number}:${ref.version}:${ref.sha256}`)) throw new Error("invalid navigation references");
  const navigation: NonNullable<WorkspaceResult["navigation"]> = {};
  let failed = 0;
  for (let offset = 0; offset < refs.length; offset += 3) {
    const batch = refs.slice(offset, offset + 3);
    const reports = await Promise.allSettled(batch.map(ref => readTenderNavigation({ law: ref.law,
      purchase_number: ref.number, version_number: ref.version, notice_xml_sha256: ref.sha256 })));
    reports.forEach((report, index) => { if (report.status === "fulfilled") navigation[batch[index].id] = report.value; else failed++; });
  }
  return { navigation, failed };
}


/** Global corpus selection and a single cursor across both laws. */
export async function searchGlobalWorkspace(query: string, law: TenderLawFilter, region: string, includeUnknown: boolean, cursor?: string): Promise<WorkspaceResult & { restartRequired?: boolean }> {
  if (typeof query !== "string" || !query.trim() || query.length > 120 ||
      !["all", "44", "223"].includes(law) || typeof region !== "string" || region.length > 200 ||
      typeof includeUnknown !== "boolean" || (cursor !== undefined && !/^[A-Za-z0-9_-]{1,2048}$/.test(cursor))) {
    return { query: "", law: "all", error: "Некорректный запрос поиска по цене.", restartRequired: Boolean(cursor) };
  }
  try {
    const report = await searchGlobalPrice(query.trim(), law, region.trim(), includeUnknown, cursor);
    if (report.query !== query.trim() || report.law !== law || report.delivery_region !== region.trim() || report.include_unknown_region !== includeUnknown) {
      return { query: query.trim(), law, error: "Ответ относится к другому запросу. Повторите поиск.", restartRequired: true };
    }
    return { query: report.query, law: report.law, result44: report.result44 ?? undefined, result223: report.result223 ?? undefined,
      navigation: report.navigation, globalPrice: { next_cursor: report.next_cursor, page_snapshot_sha256: report.page_snapshot_sha256,
        snapshot_at: report.snapshot_at, matched_count: report.matched_count, unknown_region_count: report.unknown_region_count,
        delivery_region: report.delivery_region, include_unknown_region: report.include_unknown_region } };
  } catch (error) {
    const restartRequired = error instanceof ApiError && [409, 410, 422].includes(error.status);
    return { query: query.trim(), law, error: restartRequired ? "Снимок поиска изменился или истёк. Повторите поиск." : "Поиск по цене временно недоступен. Повторите запрос.", restartRequired };
  }
}
