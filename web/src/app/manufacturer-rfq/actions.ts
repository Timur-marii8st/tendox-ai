"use server";
import { redirect } from "next/navigation";
import { createManufacturerRfq, ManufacturerRfqApiError } from "@/lib/manufacturer-rfq-api";
import { validManufacturerRfqCommand, type ManufacturerRfqCommand } from "@/lib/manufacturer-rfq";

export type RfqState = { error?: string };
const one = (form: FormData, name: string) => { const values = form.getAll(name); return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null; };
export async function createRfq(_: RfqState, form: FormData): Promise<RfqState> {
  const requirementsRaw = one(form, "requirements");
  const requirements = requirementsRaw?.split(/\r?\n/).map(value => value.trim()).filter(Boolean) ?? [];
  const due = one(form, "reply_due_at");
  const command: ManufacturerRfqCommand = { command_id: one(form, "command_id") ?? "", run_id: one(form, "run_id") ?? "", record_id: one(form, "record_id") ?? "", proposal_id: one(form, "proposal_id") ?? "", decision_id: one(form, "decision_id") ?? "", quantity: one(form, "quantity") ?? "", unit_raw: one(form, "unit_raw") ?? "", quantity_basis_raw: one(form, "quantity_basis_raw") ?? "", requirements, delivery_address_raw: one(form, "delivery_address_raw") ?? "", desired_delivery_raw: one(form, "desired_delivery_raw") ?? "", reply_due_at: due ? `${due}:00+03:00` : "" };
  if (!validManufacturerRfqCommand(command)) return { error: "Проверьте количество, единицу и основание, 1–20 требований, адрес, сроки и будущую дату ответа по МСК." };
  let draftId: string;
  try { draftId = (await createManufacturerRfq(command)).draft.draft_id; }
  catch (error) { return { error: error instanceof ManufacturerRfqApiError ? `Черновик отклонён API (${error.status}). Проверка производителя могла утратить актуальность.` : "Черновик временно недоступен." }; }
  redirect(`/manufacturer-rfq?draft=${encodeURIComponent(draftId)}`);
}
