"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  createApplicationPackage,
  loadApplicationPackage,
  type ApplicationAttachmentInput,
  type ApplicationDocumentRequirement,
  type ApplicationRequirementKind,
} from "@/lib/procurement-api";

export type ApplicationPackageState = {
  error?: string;
  success?: string;
  packageSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MONEY = /^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$/;
const FILENAME = /^[^/\\]{1,255}$/;
const KINDS = new Set<ApplicationRequirementKind>([
  "FORM", "DECLARATION", "ELIGIBILITY", "CERTIFICATE", "AUTHORITY",
  "TECHNICAL_PROPOSAL", "PRICE_PROPOSAL", "OTHER",
]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function count(form: FormData, name: string): number | null {
  const value = one(form, name);
  if (!value || !/^[1-9][0-9]?$/.test(value)) return null;
  const parsed = Number(value);
  return parsed <= 50 ? parsed : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен server-only token оператора.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли OPERATOR.";
    if (error.status === 404) return "Exact participation decision не найдено в текущем tenant.";
    if (error.status === 409) return "Пакет уже сохранён. Обновите страницу.";
    if (error.status === 422) return "Состав, цена или evidence не прошли серверную проверку.";
  }
  return "Пакет не сохранён. Проверьте API и повторите запрос.";
}

export async function submitApplicationPackage(
  _: ApplicationPackageState,
  form: FormData,
): Promise<ApplicationPackageState> {
  const requirementCount = count(form, "requirement-count");
  const attachmentCount = count(form, "attachment-count");
  if (requirementCount === null || attachmentCount === null) {
    return { error: "Нужны хотя бы одно требование и один файл; максимум 50 строк каждого типа." };
  }
  const expected = new Set([
    "decision-id", "decision-sha256", "proposed-price-ex-vat",
    "requirement-count", "attachment-count",
  ]);
  for (let index = 1; index <= requirementCount; index += 1) {
    for (const suffix of ["kind", "title", "source-id", "source-sha256", "locator"]) {
      expected.add(`requirement-${index}-${suffix}`);
    }
  }
  for (let index = 1; index <= attachmentCount; index += 1) {
    for (const suffix of ["requirements", "document-id", "document-sha256", "filename"]) {
      expected.add(`attachment-${index}-${suffix}`);
    }
  }
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!expected.has(name) || typeof value !== "string" || form.getAll(name).length !== 1) {
      return { error: "Форма содержит неизвестное или повторяющееся поле." };
    }
  }
  if ([...expected].some((name) => form.getAll(name).length !== 1)) {
    return { error: "Состав пакета заполнен не полностью." };
  }

  const decisionId = one(form, "decision-id");
  const decisionSha = one(form, "decision-sha256");
  const proposedPrice = one(form, "proposed-price-ex-vat");
  if (
    !decisionId || !ID.test(decisionId) || !decisionSha || !SHA256.test(decisionSha)
    || !proposedPrice || !MONEY.test(proposedPrice) || Number(proposedPrice) <= 0
  ) {
    return { error: "Exact decision или цена имеют неверный формат." };
  }

  const requirements: ApplicationDocumentRequirement[] = [];
  for (let ordinal = 1; ordinal <= requirementCount; ordinal += 1) {
    const kind = one(form, `requirement-${ordinal}-kind`) as ApplicationRequirementKind | null;
    const title = one(form, `requirement-${ordinal}-title`);
    const sourceId = one(form, `requirement-${ordinal}-source-id`);
    const sourceSha = one(form, `requirement-${ordinal}-source-sha256`);
    const locator = one(form, `requirement-${ordinal}-locator`);
    if (
      !kind || !KINDS.has(kind) || !title || title.length > 1_000
      || !sourceId || !ID.test(sourceId) || !sourceSha || !SHA256.test(sourceSha)
      || !locator || locator.length > 1_000
    ) {
      return { error: `Проверьте строку требования №${ordinal} и её exact provenance.` };
    }
    requirements.push({
      ordinal, kind, title, source_document_id: sourceId,
      source_document_sha256: sourceSha, source_locator: locator,
    });
  }

  const attachments: ApplicationAttachmentInput[] = [];
  for (let ordinal = 1; ordinal <= attachmentCount; ordinal += 1) {
    const mapping = one(form, `attachment-${ordinal}-requirements`);
    const documentId = one(form, `attachment-${ordinal}-document-id`);
    const documentSha = one(form, `attachment-${ordinal}-document-sha256`);
    const filename = one(form, `attachment-${ordinal}-filename`);
    const requirementOrdinals = mapping?.split(",").map((item) => Number(item.trim())) ?? [];
    const normalized = [...new Set(requirementOrdinals)].sort((left, right) => left - right);
    if (
      normalized.length === 0 || normalized.some((item) => !Number.isInteger(item) || item < 1 || item > requirementCount)
      || normalized.some((item, index) => item !== requirementOrdinals[index])
      || !documentId || !ID.test(documentId) || !documentSha || !SHA256.test(documentSha)
      || !filename || !FILENAME.test(filename) || filename === "." || filename === ".."
    ) {
      return { error: `Проверьте файл №${ordinal}, его SHA-256 и номера покрываемых требований.` };
    }
    attachments.push({
      ordinal, requirement_ordinals: normalized, document_id: documentId,
      document_sha256: documentSha, submission_filename: filename,
    });
  }
  const covered = new Set(attachments.flatMap((item) => item.requirement_ordinals));
  if (requirements.some((item) => !covered.has(item.ordinal))) {
    return { error: "Каждая заявленная строка должна быть покрыта хотя бы одним exact файлом." };
  }

  try {
    const fresh = await loadApplicationPackage(decisionId);
    const decision = fresh.evidence.participation.decision;
    if (
      fresh.package !== null || decision?.status !== "APPROVED"
      || decision.decision_sha256 !== decisionSha
    ) {
      return { error: "Participation decision изменилось, отклонено или пакет уже создан." };
    }
    const created = await createApplicationPackage(decisionId, {
      participation_decision_sha256: decisionSha,
      proposed_price_ex_vat: proposedPrice,
      requirements,
      attachments,
    });
    revalidatePath(`/application-package?decision_id=${encodeURIComponent(decisionId)}`);
    return {
      success: "Immutable пакет сохранён и ожидает независимой проверки. Отправка не разрешена.",
      packageSha256: created.package_sha256,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
