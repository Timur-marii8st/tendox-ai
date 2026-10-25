export type Knowledge = "KNOWN" | "UNKNOWN" | "NOT_APPLICABLE";
export type FactValue = string | boolean | string[] | null;
export type FactInput = { knowledge: Knowledge; value: FactValue; reason: string | null };
export type ProfileSource = {
  company_id: string; kind: "manual_declaration"; source_sha256: string;
  recorded_at: string; recorded_by: string;
  provenance: { document_id: string; locator: string; extractor: "manual"; confidence: number };
};
export type ProfileFact = FactInput & { sources: ProfileSource[] };
export type ProfileSnapshot = {
  schema_version: "company-profile-snapshot-v1";
  company_id: string; version: number; parent_version: number | null;
  created_at: string; created_by: string; effective_at: string;
  currency: "RUB"; amount_basis: "EX_VAT";
  facts: Record<string, ProfileFact>; snapshot_sha256: string; audit_event_id: string;
  critical_settings_status: "OWNER_AUTHORIZATION_UNAVAILABLE" | "OWNER_AUTHORIZED";
  policy_confirmation?: { command_sha256: string; confirmation_sha256: string; confirmed_by: string; confirmed_at: string; changed_paths: string[] };
};
export type ProfileSelection = {
  schema_version: "company-profile-selection-v1"; company_id: string;
  selection_id: string;
  profile_ref: { company_id: string; version: number; snapshot_sha256: string };
  selected_at: string; selected_by: string; audit_event_id: string;
};
export type ProfileCapabilities = {
  company_id: string; actor_id: string; access_role: "OPERATOR" | "COMPANY_PROFILE_OWNER" | "AUDITOR";
  can_edit: boolean; critical_settings_editable: boolean; blocked_fields: string[]; field_paths: string[];
};
export type VersionPage = { items: { version: number; created_at: string; created_by: string }[]; next_before: number | null };
export type ProfileSaveCommand = { schema_version: "company-profile-save-command-v1"; expected_version: number; changes: Record<string, FactInput>; confirmation_sha256?: string };
export type ProfileField = { path: string; label: string; group: string; kind: "text" | "list" | "boolean" | "decimal"; hint?: string; optional?: boolean };

export const profileFields: ProfileField[] = [
  { path: "identity.name", label: "Название компании", group: "Реквизиты", kind: "text" },
  { path: "identity.inn", label: "ИНН", group: "Реквизиты", kind: "text", hint: "10 цифр для организации или 12 для ИП" },
  { path: "identity.kpp", label: "КПП", group: "Реквизиты", kind: "text", hint: "9 цифр; для ИП можно отметить неприменимость", optional: true },
  { path: "identity.ogrn", label: "ОГРН / ОГРНИП", group: "Реквизиты", kind: "text", hint: "13 или 15 цифр" },
  { path: "identity.legal_form", label: "Организационно-правовая форма", group: "Реквизиты", kind: "text", hint: "Например, ООО или ИП" },
  { path: "okved", label: "ОКВЭД", group: "Деятельность", kind: "list", hint: "Один код на строку" },
  { path: "business_description", label: "Чем занимается компания", group: "Деятельность", kind: "text" },
  { path: "supplied_goods", label: "Поставляемые товары", group: "Деятельность", kind: "list", hint: "Одна категория на строку" },
  { path: "performed_works", label: "Выполняемые работы", group: "Деятельность", kind: "list" },
  { path: "provided_services", label: "Оказываемые услуги", group: "Деятельность", kind: "list" },
  { path: "geography.all_russia", label: "Интересуют закупки по всей России", group: "География поиска", kind: "boolean" },
  { path: "geography.federal_districts", label: "Федеральные округа", group: "География поиска", kind: "list" },
  { path: "geography.regions", label: "Регионы", group: "География поиска", kind: "list" },
  { path: "geography.cities", label: "Города", group: "География поиска", kind: "list", hint: "Указывайте город вместе с регионом" },
  { path: "geography.max_distance_km", label: "Предельное расстояние, км", group: "География поиска", kind: "decimal", optional: true, hint: "Положительное число; это заявленный интерес, а не расчёт маршрута" },
  { path: "finance.min_contract_amount", label: "Минимальная сумма контракта, ₽ без НДС", group: "Критические настройки", kind: "decimal" },
  { path: "finance.max_contract_amount", label: "Максимальная сумма контракта, ₽ без НДС", group: "Критические настройки", kind: "decimal" },
  { path: "finance.min_margin", label: "Минимальная маржа, доля", group: "Критические настройки", kind: "decimal" },
  { path: "finance.min_expected_profit", label: "Минимальная прибыль, ₽ без НДС", group: "Критические настройки", kind: "decimal" },
  { path: "finance.max_contract_without_extra_approval", label: "Контракт без дополнительного согласования, ₽", group: "Критические настройки", kind: "decimal" },
  { path: "finance.max_application_security", label: "Обеспечение заявки, ₽", group: "Критические настройки", kind: "decimal" },
  { path: "finance.max_performance_security", label: "Обеспечение исполнения, ₽", group: "Критические настройки", kind: "decimal" },
  { path: "finance.price_floor_margin", label: "Маржа для порога снижения цены, доля", group: "Критические настройки", kind: "decimal" },
  { path: "enabled_platforms", label: "Разрешённые площадки", group: "Критические настройки", kind: "list" },
  { path: "allowed_procedure_methods", label: "Разрешённые способы закупки", group: "Критические настройки", kind: "list" },
  { path: "subcontracting_allowed", label: "Допустимость субподряда", group: "Критические настройки", kind: "boolean" },
  { path: "prohibitions", label: "Юридические и коммерческие запреты", group: "Критические настройки", kind: "list" },
];

export const unknownFact = (): FactInput => ({ knowledge: "UNKNOWN", value: null, reason: "NOT_PROVIDED" });
export function factInput(fact?: ProfileFact): FactInput {
  return fact ? { knowledge: fact.knowledge, value: fact.value, reason: fact.reason } : unknownFact();
}
export function factLabel(fact?: FactInput): string {
  if (!fact || fact.knowledge === "UNKNOWN") return "Не указано";
  if (fact.knowledge === "NOT_APPLICABLE") return "Не применяется";
  if (typeof fact.value === "boolean") return fact.value ? "Да" : "Нет";
  if (Array.isArray(fact.value)) return fact.value.length ? fact.value.join("; ") : "Подтверждённый пустой список";
  return fact.value ?? "Не указано";
}
export function changedFacts(original: ProfileSnapshot | null, draft: Record<string, FactInput>, blocked: string[]): Record<string, FactInput> {
  return Object.fromEntries(profileFields.filter(field => !blocked.includes(field.path)).filter(field => JSON.stringify(factInput(original?.facts[field.path])) !== JSON.stringify(draft[field.path] ?? unknownFact())).map(field => [field.path, draft[field.path] ?? unknownFact()]));
}
export function validSnapshot(value: unknown): value is ProfileSnapshot {
  if (!value || typeof value !== "object") return false;
  const s = value as ProfileSnapshot;
  const confirmed = s.critical_settings_status === "OWNER_AUTHORIZED";
  return s.schema_version === "company-profile-snapshot-v1" && typeof s.company_id === "string" && Number.isSafeInteger(s.version) && s.version > 0 && /^[0-9a-f]{64}$/.test(s.snapshot_sha256) && s.currency === "RUB" && s.amount_basis === "EX_VAT" && (s.critical_settings_status === "OWNER_AUTHORIZATION_UNAVAILABLE" || confirmed) && (!confirmed || !!s.policy_confirmation && /^[0-9a-f]{64}$/.test(s.policy_confirmation.command_sha256) && /^[0-9a-f]{64}$/.test(s.policy_confirmation.confirmation_sha256) && typeof s.policy_confirmation.confirmed_by === "string" && Array.isArray(s.policy_confirmation.changed_paths)) && typeof s.facts === "object" && s.facts !== null && profileFields.every(field => {
    const f = s.facts[field.path];
    if (!f || !["KNOWN", "UNKNOWN", "NOT_APPLICABLE"].includes(f.knowledge) || !Array.isArray(f.sources)) return false;
    if (f.knowledge !== "KNOWN") return f.value === null && typeof f.reason === "string";
    const typed = field.kind === "boolean" ? typeof f.value === "boolean" : field.kind === "list" ? Array.isArray(f.value) && f.value.every(v => typeof v === "string") : typeof f.value === "string";
    return typed && f.reason === null && f.sources.length > 0 && f.sources.every(source => source.company_id === s.company_id && source.provenance.locator === field.path && source.kind === "manual_declaration" && /^[0-9a-f]{64}$/.test(source.source_sha256));
  });
}
