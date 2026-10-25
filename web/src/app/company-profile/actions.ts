"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createHash } from "node:crypto";
import { profileCookie, ProfileApiError, readCapabilities, saveProfile, selectProfile } from "@/lib/company-profile-api";
import { profileFields, type ProfileSaveCommand } from "@/lib/company-profile";

export type ProfileFormState = { error?: string };
const criticalPaths = new Set(profileFields.filter(field => field.group === "Критические настройки" && field.path !== "prohibitions").map(field => field.path));
const setPaths = new Set(["geography.federal_districts", "geography.regions", "geography.cities", "enabled_platforms", "allowed_procedure_methods"]);

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${stableJson(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
function sha256(value: unknown): string { return createHash("sha256").update(stableJson(value), "utf8").digest("hex"); }
class ProfileDecimalError extends Error {}
function normalDecimal(value: string): string {
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value.replace(/_/g, ""));
  if (!match) throw new ProfileDecimalError();
  const exponentText = (match[5] ?? "0").replace(/^([+-]?)0+(?=\d)/, "$1");
  if (exponentText.replace(/^[+-]/, "").length > 4) throw new ProfileDecimalError();
  let exponent = BigInt(exponentText);
  // Bound expansion before allocating strings; larger exponents get a visible input error.
  if (exponent < BigInt(-1000) || exponent > BigInt(1000)) throw new ProfileDecimalError();
  const fraction = match[3] ?? match[4] ?? "";
  let digits = ((match[2] ?? "") + fraction).replace(/^0+/, "");
  if (!digits) return "0";
  exponent -= BigInt(fraction.length);
  // Match Decimal.normalize() with the domain's 28-digit ROUND_HALF_EVEN context.
  if (digits.length > 28) {
    const kept = digits.slice(0, 28);
    const dropped = digits.slice(28);
    const roundUp = dropped[0] > "5" || dropped[0] === "5" && (/[1-9]/.test(dropped.slice(1)) || /[13579]/.test(kept.at(-1)!));
    digits = (BigInt(kept) + (roundUp ? BigInt(1) : BigInt(0))).toString();
    exponent += BigInt(dropped.length);
  }
  const trimmed = digits.replace(/0+$/, "");
  exponent += BigInt(digits.length - trimmed.length);
  digits = trimmed;
  // Number is used only for bounded string positions; the monetary coefficient stays exact.
  const point = Number(BigInt(digits.length) + exponent);
  const result = point <= 0 ? `0.${"0".repeat(-point)}${digits}` : point >= digits.length ? `${digits}${"0".repeat(point - digits.length)}` : `${digits.slice(0, point)}.${digits.slice(point)}`;
  return `${match[1] === "-" ? "-" : ""}${result}`;
}
function exactOwnerConfirmation(command: ProfileSaveCommand, companyId: string, actorId: string): string {
  const changes = Object.fromEntries(Object.entries(command.changes).map(([path, fact]) => {
    let value = fact.value;
    const field = profileFields.find(item => item.path === path);
    if (typeof value === "string") value = field?.kind === "decimal" ? normalDecimal(value.trim()) : value.trim();
    if (Array.isArray(value)) {
      value = Array.from(new Set(value.map(item => item.trim()).filter(Boolean)));
      if (setPaths.has(path)) value.sort();
    }
    return [path, { knowledge: fact.knowledge, value: fact.knowledge === "KNOWN" ? value : null, reason: fact.reason }];
  }));
  const commandSha = sha256({ schema_version: command.schema_version, expected_version: command.expected_version, changes });
  return sha256({ company_id: companyId, actor_id: actorId, command_sha256: commandSha });
}
function errorMessage(error: unknown): string {
  if (error instanceof ProfileDecimalError) return "Введите десятичное число цифрами 0–9, например 0.15 или 1e-1. Допустимый показатель степени — от -1000 до 1000.";
  if (!(error instanceof ProfileApiError)) return "Не удалось связаться с сервисом. Введённые данные сохранены в форме; повторите запрос.";
  if (error.status === 401) return "Доступ не подтверждён. Подключитесь снова.";
  if (error.status === 403) return "Нет права изменить эти настройки. Критические поля требуют подтверждённого владельца.";
  if (error.status === 409) return "Профиль изменён в другом окне или сохранённый запрос конфликтует. Откройте актуальную версию и перенесите свои изменения.";
  if (error.status === 422) {
    const fields = typeof error.detail === "object" && error.detail !== null && "fields" in error.detail && Array.isArray(error.detail.fields) ? error.detail.fields.filter((value): value is string => typeof value === "string") : [];
    if (fields.includes("geography")) return "Укажите разрешённую территорию или выберите поиск по всей России. Подтверждённая пустая география не задаёт область поиска.";
    const labels = fields.map(path => profileFields.find(field => path === field.path || path.startsWith(`changes.${field.path}`))?.label).filter(Boolean);
    return `${labels.length ? `Проверьте поля: ${Array.from(new Set(labels)).join(", ")}. ` : "Проверьте реквизиты и числовые значения. "}ИНН содержит 10 или 12 цифр, КПП — 9, ОГРН — 13 или 15; расстояние должно быть положительным.`;
  }
  return "Сервис профиля временно недоступен. Повторите попытку позже.";
}
export async function connectProfile(_: ProfileFormState, form: FormData): Promise<ProfileFormState> {
  const credential = form.get("credential");
  if (typeof credential !== "string" || credential.length < 8 || credential.length > 500 || /\s/.test(credential)) return { error: "Введите действующий персональный ключ доступа." };
  try { await readCapabilities(credential); } catch (error) { return { error: errorMessage(error) }; }
  (await cookies()).set("company_profile_session", "", { path: "/company-profile", maxAge: 0 });
  (await cookies()).set(profileCookie, credential, { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 3600 });
  redirect("/company-profile");
}
export async function disconnectProfile(): Promise<void> {
  (await cookies()).set("company_profile_session", "", { path: "/company-profile", maxAge: 0 });
  (await cookies()).set(profileCookie, "", { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
  redirect("/company-profile");
}
export async function saveProfileAction(_: ProfileFormState, form: FormData): Promise<ProfileFormState> {
  const raw = form.get("command");
  const key = form.get("command-key");
  if (typeof raw !== "string" || raw.length > 65536 || typeof key !== "string" || !/^[0-9a-f-]{36}$/.test(key) || form.get("confirmed") !== "yes") return { error: "Проверьте изменения и подтвердите сохранение." };
  let version: number;
  try {
    const command = JSON.parse(raw) as ProfileSaveCommand;
    if (Object.keys(command.changes).some(path => criticalPaths.has(path))) {
      const capabilities = await readCapabilities();
      if (!capabilities.critical_settings_editable) return { error: "Критические поля может подтверждать только владелец компании." };
      command.confirmation_sha256 = exactOwnerConfirmation(command, capabilities.company_id, capabilities.actor_id);
    }
    version = (await saveProfile(command, key)).version;
  }
  catch (error) { return { error: errorMessage(error) }; }
  revalidatePath("/company-profile");
  redirect(`/company-profile?version=${version}&saved=1`);
}
export async function selectProfileAction(_: ProfileFormState, form: FormData): Promise<ProfileFormState> {
  const version = form.get("version");
  const sha = form.get("snapshot-sha");
  const key = form.get("selection-key");
  if (typeof version !== "string" || !/^[1-9]\d*$/.test(version) || typeof sha !== "string" || !/^[0-9a-f]{64}$/.test(sha) || typeof key !== "string" || !/^[0-9a-f-]{36}$/.test(key)) return { error: "Не удалось выбрать сохранённую версию." };
  try { await selectProfile(Number(version), sha, key); } catch (error) { return { error: errorMessage(error) }; }
  revalidatePath("/company-profile");
  redirect(`/company-profile?version=${version}&selected=1`);
}
