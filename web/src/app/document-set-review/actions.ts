"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  createDocumentSetReviewDecision,
  loadDocumentSetReviewEvidence,
  type DocumentSetCrossAssessment,
  type DocumentSetFinding,
  type DocumentSetInventoryAssessment,
  type DocumentSetMemberAssessment,
  type DocumentSetMemberAttestation,
} from "@/lib/procurement-api";

export type DocumentSetReviewFormState = { error?: string; success?: string };

const SHA256 = /^[0-9a-f]{64}$/;
const MANIFEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const MEMBER_FIELD = /^member-(\d{1,2})-(review-id|review-evidence|decision-sha|assessment|rationale)$/;
const MEMBER_ASSESSMENTS = new Set<DocumentSetMemberAssessment>([
  "REVIEWED_IN_SCOPE",
  "UNRESOLVED",
]);
const INVENTORY_ASSESSMENTS = new Set<DocumentSetInventoryAssessment>([
  "CONFIRMED_FOR_DECLARED_SCOPE",
  "UNRESOLVED",
]);
const CROSS_ASSESSMENTS = new Set<DocumentSetCrossAssessment>([
  "CHECKED_NO_OPEN_ISSUES",
  "OPEN_ISSUES",
  "UNRESOLVED",
]);
const CONFIRMED_FINDING_KINDS = new Set<DocumentSetFinding["kind"]>([
  "CONFIRMED_MATERIAL_OMISSION",
  "CONFIRMED_MISSING_DOCUMENT",
]);
const SOURCE_REFERENCE = /^(10|[1-9]):(0|[1-9]\d{0,5})$/;
const SINGLETON_FIELDS = new Set([
  "manifest-id",
  "manifest-evidence-sha256",
  "inventory-assessment",
  "inventory-rationale",
  "cross-assessment",
  "cross-rationale",
  "reason",
  "finding-kind",
  "finding-source",
  "finding-rationale",
]);
const MAX_MEMBERS = 10;
const MAX_RATIONALE = 2_000;
const MAX_CROSS_RATIONALE = 4_000;

export async function submitDocumentSetReview(
  _: DocumentSetReviewFormState,
  form: FormData,
): Promise<DocumentSetReviewFormState> {
  const parsed = parse(form);
  if (!("manifestId" in parsed)) return parsed;

  try {
    const evidence = await loadDocumentSetReviewEvidence(parsed.manifestId);
    const validationError = validateFreshEvidence(parsed.manifestId, parsed.payload, evidence);
    if (validationError) return { error: validationError };
    const constituentFailure = evidence.constituents.some((item) => item.review.decision?.status === "FAIL");
    const confirmedFinding = parsed.payload.reviewer_findings.some((item) => CONFIRMED_FINDING_KINDS.has(item.kind));
    const status = constituentFailure || confirmedFinding
      ? "FAIL"
      : evidence.constituents.every((item) => item.review.decision?.status === "PASS")
      && parsed.payload.attestations.every((item) => item.assessment === "REVIEWED_IN_SCOPE")
      && parsed.payload.inventory_assessment === "CONFIRMED_FOR_DECLARED_SCOPE"
      && parsed.payload.cross_document_assessment === "CHECKED_NO_OPEN_ISSUES"
      && evidence.server_findings.length === 0
      ? "PASS"
      : "UNKNOWN";
    await createDocumentSetReviewDecision(parsed.manifestId, { ...parsed.payload, status });
    // Keep the selected evidence route explicit; this UI has no queue or latest fallback.
    revalidatePath(`/document-set-review?manifest_id=${encodeURIComponent(parsed.manifestId)}`);
    return { success: "Терминальное решение сохранено для выбранного exact manifest." };
  } catch (error) {
    return { error: safeError(error) };
  }
}

function parse(
  form: FormData,
):
  | {
      manifestId: string;
      payload: Parameters<typeof createDocumentSetReviewDecision>[1];
    }
  | DocumentSetReviewFormState {
  const members = new Map<number, Partial<Record<"review-id" | "review-evidence" | "decision-sha" | "assessment" | "rationale", string>>>();
  const singletonCounts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (SINGLETON_FIELDS.has(name)) {
      singletonCounts.set(name, (singletonCounts.get(name) ?? 0) + 1);
      if (typeof value !== "string") return { error: "Форма содержит недопустимое поле." };
      continue;
    }
    const match = MEMBER_FIELD.exec(name);
    if (!match || typeof value !== "string") return { error: "Форма содержит недопустимое поле." };
    const ordinal = Number(match[1]);
    const kind = match[2] as "review-id" | "review-evidence" | "decision-sha" | "assessment" | "rationale";
    const current = members.get(ordinal) ?? {};
    if (current[kind] !== undefined) return { error: "Форма содержит повторяющееся поле участника." };
    current[kind] = value;
    members.set(ordinal, current);
  }
  if ([...SINGLETON_FIELDS].some((name) => singletonCounts.get(name) !== 1)) {
    return { error: "Форма решения неполна или содержит повторяющиеся поля." };
  }

  const manifestId = singleton(form, "manifest-id");
  const manifestEvidence = singleton(form, "manifest-evidence-sha256");
  const inventoryAssessment = singleton(form, "inventory-assessment");
  const inventoryRationale = singleton(form, "inventory-rationale");
  const crossAssessment = singleton(form, "cross-assessment");
  const crossRationale = singleton(form, "cross-rationale");
  const reason = singleton(form, "reason");
  const findingKind = singleton(form, "finding-kind");
  const findingSource = singleton(form, "finding-source");
  const findingRationale = singleton(form, "finding-rationale");
  if (!manifestId || !MANIFEST_ID.test(manifestId) || !manifestEvidence || !SHA256.test(manifestEvidence)) {
    return { error: "Manifest ID или его evidence digest некорректны." };
  }
  if (!INVENTORY_ASSESSMENTS.has(inventoryAssessment as DocumentSetInventoryAssessment)
    || !CROSS_ASSESSMENTS.has(crossAssessment as DocumentSetCrossAssessment)
    || !text(inventoryRationale, MAX_RATIONALE)
    || !text(crossRationale, MAX_CROSS_RATIONALE)
    || !text(reason, MAX_CROSS_RATIONALE)) {
    return { error: "Заполните корректные assessments и основания в допустимых пределах." };
  }
  if (members.size < 2 || members.size > MAX_MEMBERS) {
    return { error: "Нужно подтвердить всех 2–10 участников manifest." };
  }

  const attestations: DocumentSetMemberAttestation[] = [];
  for (let ordinal = 1; ordinal <= members.size; ordinal += 1) {
    const item = members.get(ordinal);
    if (!item || !item["review-id"] || !item["review-evidence"] || !item["decision-sha"]
      || !item.assessment || !item.rationale || !SHA256.test(item["review-evidence"])
      || !SHA256.test(item["decision-sha"]) || !MEMBER_ASSESSMENTS.has(item.assessment as DocumentSetMemberAssessment)
      || !text(item.rationale, MAX_RATIONALE)) {
      return { error: "Каждый участник должен иметь точную decision reference, assessment и основание." };
    }
    attestations.push({
      reference: {
        member_ordinal: ordinal,
        review_id: item["review-id"].trim(),
        review_evidence_sha256: item["review-evidence"],
        decision_sha256: item["decision-sha"],
      },
      assessment: item.assessment as DocumentSetMemberAssessment,
      rationale: item.rationale.trim(),
    });
  }
  const reviewerFindings = parseReviewerFinding(findingKind, findingSource, findingRationale);
  if (reviewerFindings === null) {
    return { error: "FAIL finding должен содержать допустимый confirmed kind, source block из evidence и основание." };
  }
  if (inventoryAssessment === "CONFIRMED_FOR_DECLARED_SCOPE" && reviewerFindings.some(
    (item) => item.kind === "CONFIRMED_MISSING_DOCUMENT",
  )) {
    return { error: "CONFIRMED_FOR_DECLARED_SCOPE несовместим с confirmed missing document." };
  }
  return {
    manifestId,
    payload: {
      manifest_evidence_sha256: manifestEvidence,
      attestations,
      inventory_assessment: inventoryAssessment as DocumentSetInventoryAssessment,
      inventory_rationale: inventoryRationale.trim(),
      cross_document_assessment: crossAssessment as DocumentSetCrossAssessment,
      cross_document_rationale: crossRationale.trim(),
      reviewer_findings: reviewerFindings,
      status: "UNKNOWN",
      reason: reason.trim(),
    },
  };
}

function parseReviewerFinding(
  kind: string | null,
  source: string | null,
  rationale: string | null,
): DocumentSetFinding[] | null {
  if (!kind && !source && !rationale) return [];
  if (!kind || !source || !text(rationale, MAX_RATIONALE)
    || !CONFIRMED_FINDING_KINDS.has(kind as DocumentSetFinding["kind"])) return null;
  const reference = SOURCE_REFERENCE.exec(source);
  if (!reference) return null;
  const memberOrdinal = Number(reference[1]);
  const extractionBlockIndex = Number(reference[2]);
  return [{
    finding_id: `reviewer-${kind}-${memberOrdinal}-${extractionBlockIndex}`,
    kind: kind as DocumentSetFinding["kind"],
    evidence: [{ kind: "SOURCE_BLOCK", member_ordinal: memberOrdinal, extraction_block_index: extractionBlockIndex }],
    rationale: rationale.trim(),
    origin: "REVIEWER",
  }];
}

function validateFreshEvidence(
  manifestId: string,
  payload: Parameters<typeof createDocumentSetReviewDecision>[1],
  evidence: Awaited<ReturnType<typeof loadDocumentSetReviewEvidence>>,
): string | null {
  if (evidence.manifest.manifest_id !== manifestId || evidence.manifest.evidence_sha256 !== payload.manifest_evidence_sha256) {
    return "Manifest evidence изменился; перезагрузите exact review.";
  }
  if (payload.attestations.length !== evidence.constituents.length) {
    return "Нужно подтвердить каждого участника текущего manifest.";
  }
  for (const [index, constituent] of evidence.constituents.entries()) {
    const submitted = payload.attestations[index]?.reference;
    const member = constituent.member;
    if (!submitted || !constituent.decision_sha256
      || submitted.member_ordinal !== member.ordinal
      || submitted.review_id !== member.completeness_review_id
      || submitted.review_evidence_sha256 !== member.completeness_review_evidence_sha256
      || submitted.decision_sha256 !== constituent.decision_sha256) {
      return "Submitted attestation не совпадает с текущим exact constituent evidence.";
    }
  }
  for (const finding of payload.reviewer_findings) {
    const reference = finding.evidence.length === 1 ? finding.evidence[0] : null;
    if (!CONFIRMED_FINDING_KINDS.has(finding.kind)
      || finding.origin !== "REVIEWER"
      || !reference
      || reference.kind !== "SOURCE_BLOCK"
      || finding.finding_id !== `reviewer-${finding.kind}-${reference.member_ordinal}-${reference.extraction_block_index}`
      || !text(finding.rationale, MAX_RATIONALE)) {
      return "Reviewer finding должен быть одним допустимым confirmed source-block finding.";
    }
    const constituent = evidence.constituents.find((item) => item.member.ordinal === reference.member_ordinal);
    if (!constituent || reference.extraction_block_index >= constituent.review.snapshot.extraction.blocks.length) {
      return "Reviewer finding ссылается не на source block текущего exact evidence.";
    }
  }
  const findings = [...evidence.server_findings, ...payload.reviewer_findings];
  if (payload.cross_document_assessment === "OPEN_ISSUES" && findings.length === 0) {
    return "OPEN_ISSUES требует fresh server finding или typed reviewer finding.";
  }
  if (payload.cross_document_assessment === "CHECKED_NO_OPEN_ISSUES" && findings.length > 0) {
    return "CHECKED_NO_OPEN_ISSUES несовместим с fresh server/reviewer findings.";
  }
  return null;
}

function singleton(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0] : null;
}

function text(value: string | null | undefined, maxLength: number): value is string {
  return typeof value === "string" && Boolean(value.trim()) && value.trim().length <= maxLength;
}

function safeError(error: unknown): string {
  if (error instanceof ApiError) {
    return {
      401: "Не удалось подтвердить доступ reviewer к API.",
      403: "Нужна роль COMPLETENESS_REVIEWER.",
      404: "Manifest недоступен в текущем tenant.",
      409: "Evidence изменился или терминальное решение уже существует.",
      422: "API отклонил решение: проверьте exact evidence и assessments.",
    }[error.status] ?? "Сервис временно недоступен.";
  }
  if (error instanceof ConfigurationError) return "Server-only reviewer token не настроен.";
  return "Сервис временно недоступен.";
}
