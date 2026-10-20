"use server";

import {
  ApiError,
  ConfigurationError,
  materializeReviewedRequirementSet,
  previewRequirementSetMaterialization,
  type ExecutableRequirementSelection,
  type RequirementSetMaterializationPreview,
} from "@/lib/procurement-api";

export type PreviewState = {
  error?: string;
  preview?: RequirementSetMaterializationPreview;
};

export type MaterializationState = {
  error?: string;
  setId?: string;
  proposalSha256?: string;
  entryCount?: number;
  executableCount?: number;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const PROPERTY = /^[a-z][a-z0-9_]{1,99}$/;

function errorText(error: unknown): string {
  if (error instanceof ConfigurationError) return "Серверный доступ к API не настроен.";
  if (error instanceof ApiError) {
    if (error.status === 404) return "Документ не найден в текущей компании.";
    if (error.status === 409) return "Такой immutable proposal уже существует.";
    if (error.status === 422) {
      return "Документ, digest, число строк или выбранная нормализация не прошли проверку.";
    }
    if (error.status === 403) return "Для операции требуется роль OPERATOR.";
  }
  return "Операция не завершилась. Проверьте API и повторите запрос.";
}

function sourceFields(form: FormData) {
  const documentId = form.get("document-id");
  const sha256 = form.get("source-sha256");
  const rawCount = form.get("expected-entry-count");
  if (
    typeof documentId !== "string" ||
    !ID.test(documentId) ||
    typeof sha256 !== "string" ||
    !SHA256.test(sha256) ||
    typeof rawCount !== "string" ||
    !/^\d{1,3}$/.test(rawCount)
  ) {
    return null;
  }
  const expectedEntryCount = Number(rawCount);
  if (expectedEntryCount < 1 || expectedEntryCount > 500) return null;
  return { documentId, sha256, expectedEntryCount };
}

export async function previewRequirementSet(
  _: PreviewState,
  form: FormData,
): Promise<PreviewState> {
  const source = sourceFields(form);
  if (!source) return { error: "Проверьте document ID, SHA-256 и ожидаемое число строк." };
  try {
    return {
      preview: await previewRequirementSetMaterialization(
        source.documentId,
        source.sha256,
        source.expectedEntryCount,
      ),
    };
  } catch (error) {
    return { error: errorText(error) };
  }
}

export async function commitRequirementSet(
  _: MaterializationState,
  form: FormData,
): Promise<MaterializationState> {
  const source = sourceFields(form);
  const previewSha256 = form.get("preview-sha256");
  const declaredScope = form.get("declared-scope");
  if (
    !source ||
    typeof previewSha256 !== "string" ||
    !SHA256.test(previewSha256) ||
    typeof declaredScope !== "string" ||
    !declaredScope.trim() ||
    declaredScope.length > 4_000
  ) {
    return { error: "Exact preview или границы proposal заполнены неверно." };
  }

  const selectedOrdinals = form
    .getAll("selected-ordinal")
    .filter((value): value is string => typeof value === "string");
  const selections: ExecutableRequirementSelection[] = [];
  const seen = new Set<number>();
  for (const rawOrdinal of selectedOrdinals) {
    if (!/^\d{1,3}$/.test(rawOrdinal)) return { error: "Номер выбранной строки повреждён." };
    const ordinal = Number(rawOrdinal);
    if (ordinal < 1 || ordinal > source.expectedEntryCount || seen.has(ordinal)) {
      return { error: "Выбранные строки повторяются или выходят за границы preview." };
    }
    seen.add(ordinal);
    const property = form.get(`property-${ordinal}`);
    const unit = form.get(`unit-${ordinal}`);
    const mandatory = form.get(`mandatory-${ordinal}`);
    const reviewNote = form.get(`review-note-${ordinal}`);
    if (
      typeof property !== "string" ||
      !PROPERTY.test(property.trim()) ||
      (typeof unit !== "string" && unit !== null) ||
      (mandatory !== "true" && mandatory !== "false") ||
      typeof reviewNote !== "string" ||
      !reviewNote.trim() ||
      reviewNote.length > 2_000
    ) {
      return { error: `Проверьте нормализацию выбранной строки №${ordinal}.` };
    }
    selections.push({
      ordinal,
      property: property.trim(),
      unit: typeof unit === "string" && unit.trim() ? unit.trim() : null,
      mandatory: mandatory === "true",
      review_note: reviewNote.trim(),
    });
  }

  try {
    const record = await materializeReviewedRequirementSet(source.documentId, {
      source_document_sha256: source.sha256,
      expected_entry_count: source.expectedEntryCount,
      preview_sha256: previewSha256,
      declared_scope: declaredScope.trim(),
      selections,
    });
    return {
      setId: record.proposal.set_id,
      proposalSha256: record.proposal.proposal_sha256,
      entryCount: record.proposal.entries.length,
      executableCount: record.proposal.entries.filter(
        (entry) => entry.disposition === "EXECUTABLE",
      ).length,
    };
  } catch (error) {
    return { error: errorText(error) };
  }
}
