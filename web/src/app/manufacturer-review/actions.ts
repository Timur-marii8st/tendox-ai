"use server";

import { redirect } from "next/navigation";
import { ApiError, createManufacturerProposal, decideManufacturerProposal, readManufacturerProposal, uploadManufacturerArtifact } from "@/lib/procurement-api";
import { validDecisionCommand, validProposalCommand, type CitationClaim, type DecisionCommand, type ProposalCommand, type ReviewStatus } from "@/lib/manufacturer-review";

export type State = { error?: string; artifact?: { artifact_id: string; sha256: string } };
const one = (form: FormData, name: string) => { const values = form.getAll(name); return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null; };
const uuid = (value: string | null) => value !== null && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const message = (error: unknown, fallback: string) => error instanceof ApiError ? `${fallback} (API ${error.status}).` : `${fallback}.`;

export async function upload(_: State, form: FormData): Promise<State> {
  const files = form.getAll("file"), file = files.length === 1 ? files[0] : null, commandId = one(form, "upload_command_id"), title = one(form, "source_title"), url = one(form, "source_url");
  if (!(file instanceof File) || !uuid(commandId) || !title || !url || file.size < 1 || file.size > 2 * 1024 * 1024 || file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) return { error: "Нужен ровно один непустой PDF до 2 МиБ, название, HTTPS-адрес источника и корректная команда страницы." };
  try {
    const artifact = await uploadManufacturerArtifact({ command_id: commandId!, source_title: title, source_url: url, original_filename: file.name, content_base64: Buffer.from(await file.arrayBuffer()).toString("base64") });
    return { artifact: { artifact_id: artifact.artifact_id, sha256: artifact.sha256 } };
  } catch (error) { return { error: message(error, "Документ не сохранён") }; }
}

export async function propose(_: State, form: FormData): Promise<State> {
  const claims = form.getAll("claims").filter((value): value is string => typeof value === "string") as CitationClaim[];
  const command: ProposalCommand = { command_id: one(form, "proposal_command_id") ?? "", run_id: one(form, "run_id") ?? "", record_id: one(form, "record_id") ?? "", claimed_identity: { legal_name: one(form, "legal_name") ?? "", country_code: one(form, "country_code") ?? "", identifier_scheme: one(form, "identifier_scheme") ?? "", registration_id: one(form, "registration_id") ?? "" }, citations: [{ artifact_id: one(form, "artifact_id") ?? "", artifact_sha256: one(form, "artifact_sha256") ?? "", page: Number(one(form, "page")), locator: one(form, "locator") ?? "", quote: one(form, "quote") ?? "", claims: [...claims].sort() }] };
  if (!validProposalCommand(command)) return { error: "Проверьте юридическое лицо, документ, страницу, цитату и выберите подтверждаемые поля." };
  let proposalId: string;
  try { proposalId = (await createManufacturerProposal(command)).proposal.proposal_id; }
  catch (error) { return { error: message(error, "Предложение не сохранено") }; }
  redirect(`/manufacturer-review?proposal=${encodeURIComponent(proposalId)}`);
}

export async function decide(_: State, form: FormData): Promise<State> {
  const proposalId = one(form, "proposal_id"), rawIndexes = form.getAll("citation_indexes");
  if (!uuid(proposalId)) return { error: "Не найдено предложение." };
  if (!rawIndexes.every(value => typeof value === "string" && /^(0|1|2)$/.test(value))) return { error: "Некорректный выбор цитат." };
  const indexes = rawIndexes.map(value => Number(value));
  const expiry = one(form, "effective_until");
  const checked = (name: string): boolean | null => { const values = form.getAll(name); return values.length === 0 ? false : values.length === 1 && values[0] === "true" ? true : null; };
  const official = checked("official_origin_confirmed"), identity = checked("identity_fields_confirmed"), product = checked("exact_product_link_confirmed");
  if (official === null || identity === null || product === null) return { error: "Некорректное или повторное значение подтверждения." };
  const command: DecisionCommand = { command_id: one(form, "decision_command_id") ?? "", identity_status: (one(form, "identity_status") ?? "") as ReviewStatus, role_status: (one(form, "role_status") ?? "") as ReviewStatus, official_origin_confirmed: official, identity_fields_confirmed: identity, exact_product_link_confirmed: product, effective_until: expiry ? `${expiry}:00+03:00` : null, rationale: one(form, "rationale") ?? "", citation_indexes: indexes };
  try {
    const proposal = await readManufacturerProposal(proposalId!);
    if (!validDecisionCommand(command, proposal)) return { error: "PASS требует будущий срок, нужные подтверждения и выбранные цитаты для каждого заявленного факта." };
    await decideManufacturerProposal(proposalId!, command, proposal);
  } catch (error) { return { error: message(error, "Решение отклонено; проверьте evidence и независимость reviewer") }; }
  redirect(`/manufacturer-review?proposal=${encodeURIComponent(proposalId!)}`);
}
