import "server-only";
import { cookies } from "next/headers";
import { profileCookie } from "./company-profile-api";
import { catalogValid, commandValid, reportMatches, type CompareCommand } from "./procurement-comparison";

async function request(path: string, command?: CompareCommand & { selection_id?: string }): Promise<unknown> {
  const demo = process.env.COMPARISON_MODE === "demo";
  const base = demo ? process.env.COMPARISON_DEMO_API_URL : process.env.PROCUREMENT_API_URL;
  const token = demo ? process.env.COMPARISON_DEMO_TOKEN : (await cookies()).get(profileCookie)?.value;
  if (!base || !token || (demo && !/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}$/.test(base))) {
    throw new Error("Подключитесь персональным ключом; выберите сохранённую версию в профиле компании.");
  }
  const route = demo ? path : path.replace("/v1/local-comparison", "/v1/procurement-comparison");
  const response = await fetch(`${base.replace(/\/$/, "")}${route}`, {
    method: command ? "POST" : "GET", cache: "no-store", signal: AbortSignal.timeout(10_000),
    headers: { Authorization: `Bearer ${token}`, ...(command ? { "Content-Type": "application/json" } : {}) },
    ...(command ? { body: JSON.stringify(command) } : {}),
  });
  if (!response.ok) throw new Error(({ 401: "Доступ к локальному API не подтверждён.",
    403: "Запуск сравнения доступен оператору.",
    404: "Выбранная версия не найдена.", 409: "Версия или hash изменились. Перезагрузите страницу.",
    422: "Выберите 2–5 разных закупок и конкретную версию профиля." } as Record<number, string>)[response.status] ??
    "Локальное API сравнения недоступно.");
  return response.json();
}

export async function comparisonCatalog(cursor?: string) {
  const catalog = await request("/v1/local-comparison/catalog" + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""));
  if (!catalogValid(catalog)) throw new Error("Некорректный каталог сравнения.");
  return catalog;
}

export async function compareProcurements(command: CompareCommand) {
  if (!commandValid(command)) throw new Error("Выберите 2–5 разных закупок и конкретную версию профиля.");
  // Проверка доступа и membership повторяется в каждом Server Action.
  const catalog = await comparisonCatalog();
  if (catalog.mode === "SAVED_CASES" && (!command.selection_id || !/^[0-9a-f-]{36}$/.test(command.selection_id))) throw new Error("Выберите сохранённую версию профиля заново.");
  const report = await request("/v1/local-comparison", command);
  if (!reportMatches(report, command, catalog.company_id)) throw new Error("Отчёт не соответствует выбранным точным версиям.");
  return report;
}
