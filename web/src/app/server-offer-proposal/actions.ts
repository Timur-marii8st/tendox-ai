"use server";

import {
  ApiError,
  ConfigurationError,
  createServerOfferProposal,
  type ServerOfferBomLineInput,
  type ServerOfferCommercialTermsInput,
  type ServerOfferPartKind,
} from "@/lib/procurement-api";

export type ServerOfferFormState = {
  error?: string;
  success?: string;
  offerId?: string;
  proposalSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,499}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const DECIMAL = /^(?:0|[1-9]\d{0,15})(?:\.\d{1,4})?$/;
const LINE_FIELD = /^line-(\d{1,3})-(kind|manufacturer|sku|description|quantity|unit|unit-price|line-total|locator)$/;
const KINDS = new Set<ServerOfferPartKind>([
  "CHASSIS", "CPU", "MEMORY", "STORAGE", "RAID_CONTROLLER", "NETWORK", "PSU",
  "COOLING", "RAILS", "CABLE", "LICENSE", "SERVICE", "OTHER",
]);
const SINGLETONS = new Set([
  "case-id", "case-version", "binding-id", "binding-sha256", "sourcing-run-id", "lead-id",
  "source-document-id", "source-document-sha256", "quote-number", "supplier-id",
  "supplier-name", "amount-ex-vat", "nds-rate", "issued-at", "valid-until",
  "covers-full-scope", "availability-terms", "delivery-terms", "payment-terms",
  "terms-locator",
]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function optional(form: FormData, name: string): string | null {
  const value = one(form, name);
  return value ? value : null;
}

function errorText(error: unknown): string {
  if (error instanceof ConfigurationError) return "Серверный доступ к API не настроен.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Для proposal требуется роль OPERATOR.";
    if (error.status === 404) return "Case, binding, sourcing lead или КП-документ не найдены.";
    if (error.status === 409) return "Такой immutable proposal уже существует.";
    if (error.status === 422) return "Exact binding, lead, КП или BOM не прошли серверную проверку.";
  }
  return "Proposal не сохранён. Проверьте API и повторите запрос.";
}

export async function submitServerOfferProposal(
  _: ServerOfferFormState,
  form: FormData,
): Promise<ServerOfferFormState> {
  const lineFields = new Map<number, Map<string, string>>();
  const singletonCounts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (typeof value !== "string") return { error: "Форма содержит недопустимое поле." };
    if (SINGLETONS.has(name)) {
      singletonCounts.set(name, (singletonCounts.get(name) ?? 0) + 1);
      continue;
    }
    const match = LINE_FIELD.exec(name);
    if (!match) return { error: "Форма содержит неизвестное поле." };
    const ordinal = Number(match[1]);
    const fields = lineFields.get(ordinal) ?? new Map<string, string>();
    if (fields.has(match[2])) return { error: "Строка BOM содержит повторяющееся поле." };
    fields.set(match[2], value.trim());
    lineFields.set(ordinal, fields);
  }
  if ([...SINGLETONS].some((name) => singletonCounts.get(name) !== 1)) {
    return { error: "Коммерческие условия или exact references заполнены не полностью." };
  }
  const caseId = one(form, "case-id");
  const version = one(form, "case-version");
  const bindingId = one(form, "binding-id");
  const bindingSha = one(form, "binding-sha256");
  const runId = one(form, "sourcing-run-id");
  const leadId = one(form, "lead-id");
  const documentId = one(form, "source-document-id");
  const documentSha = one(form, "source-document-sha256");
  if (
    !caseId || !ID.test(caseId) || !version || !/^\d{1,9}$/.test(version) || Number(version) < 1
    || !bindingId || !ID.test(bindingId) || !bindingSha || !SHA256.test(bindingSha)
    || !runId || !ID.test(runId) || !leadId || !ID.test(leadId)
    || !documentId || !ID.test(documentId) || !documentSha || !SHA256.test(documentSha)
  ) return { error: "Проверьте exact case, binding, sourcing lead и КП-документ." };

  if (!lineFields.size || lineFields.size > 500) return { error: "Добавьте 1–500 строк BOM." };
  const bomLines: ServerOfferBomLineInput[] = [];
  for (let ordinal = 1; ordinal <= lineFields.size; ordinal += 1) {
    const fields = lineFields.get(ordinal);
    const kind = fields?.get("kind");
    const sku = fields?.get("sku") ?? "";
    const description = fields?.get("description") ?? "";
    const quantity = fields?.get("quantity") ?? "";
    const unit = fields?.get("unit") ?? "";
    const unitPrice = fields?.get("unit-price") || null;
    const lineTotal = fields?.get("line-total") || null;
    const locator = fields?.get("locator") ?? "";
    if (
      !fields || !kind || !KINDS.has(kind as ServerOfferPartKind) || !sku || sku.length > 300
      || !description || description.length > 2_000 || !DECIMAL.test(quantity) || !unit
      || unit.length > 50 || (unitPrice !== null && !DECIMAL.test(unitPrice))
      || (lineTotal !== null && !DECIMAL.test(lineTotal)) || (unitPrice !== null && lineTotal === null)
      || !locator || locator.length > 1_000
    ) return { error: `Проверьте строку BOM №${ordinal}.` };
    bomLines.push({
      ordinal,
      kind: kind as ServerOfferPartKind,
      manufacturer: fields.get("manufacturer") || null,
      sku,
      description,
      quantity,
      unit,
      unit_price_ex_vat: unitPrice,
      line_total_ex_vat: lineTotal,
      source_locator: locator,
    });
  }

  const amount = one(form, "amount-ex-vat");
  const ndsRate = optional(form, "nds-rate");
  const scope = one(form, "covers-full-scope");
  const issuedAt = one(form, "issued-at");
  const validUntil = one(form, "valid-until");
  if (
    !amount || !DECIMAL.test(amount) || (ndsRate !== null && !DECIMAL.test(ndsRate))
    || (scope !== "true" && scope !== "false" && scope !== "unknown")
    || !issuedAt || Number.isNaN(Date.parse(issuedAt)) || !validUntil || Number.isNaN(Date.parse(validUntil))
  ) return { error: "Проверьте сумму, НДС, scope и timezone-aware даты КП." };
  const terms: ServerOfferCommercialTermsInput = {
    quote_number: one(form, "quote-number") ?? "",
    supplier_id: one(form, "supplier-id") ?? "",
    supplier_name: one(form, "supplier-name") ?? "",
    amount_ex_vat: amount,
    nds_rate: ndsRate,
    currency: "RUB",
    issued_at: issuedAt,
    valid_until: validUntil,
    covers_full_scope: scope === "unknown" ? null : scope === "true",
    availability_terms: optional(form, "availability-terms"),
    delivery_terms: optional(form, "delivery-terms"),
    payment_terms: optional(form, "payment-terms"),
    source_locator: one(form, "terms-locator") ?? "",
  };
  if (!terms.quote_number || !terms.supplier_id || !terms.supplier_name || !terms.source_locator) {
    return { error: "Номер КП, поставщик и locator коммерческих условий обязательны." };
  }
  try {
    const proposal = await createServerOfferProposal(caseId, Number(version), {
      requirement_set_binding_id: bindingId,
      requirement_set_binding_sha256: bindingSha,
      sourcing_run_id: runId,
      lead_id: leadId,
      source_document_id: documentId,
      source_document_sha256: documentSha,
      bom_lines: bomLines,
      commercial_terms: terms,
    });
    return {
      success: "Exact BOM и КП сохранены как proposal, ожидающий независимого review.",
      offerId: proposal.offer_id,
      proposalSha256: proposal.proposal_sha256,
    };
  } catch (error) {
    return { error: errorText(error) };
  }
}
