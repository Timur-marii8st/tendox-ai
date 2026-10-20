import { createHash } from "node:crypto";
import { downloadManufacturerRfqText, ManufacturerRfqApiError, readManufacturerRfq } from "@/lib/manufacturer-rfq-api";

export const dynamic = "force-dynamic";
export async function GET(_request: Request, context: { params: Promise<{ draftId: string }> }) {
  const { draftId } = await context.params;
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(draftId)) return new Response("Некорректный идентификатор.", { status: 400, headers });
  try {
    const [saved, raw] = await Promise.all([readManufacturerRfq(draftId), downloadManufacturerRfqText(draftId)]);
    const calculated = createHash("sha256").update(raw.bytes).digest("hex");
    if (raw.sha256 !== saved.draft.text_sha256 || calculated !== saved.draft.text_sha256 || raw.applicability !== saved.current_status || new TextDecoder("utf-8", { fatal: true }).decode(raw.bytes) !== saved.draft.text) return new Response("Целостность или применимость черновика не подтверждена.", { status: 502, headers });
    return new Response(raw.bytes.buffer.slice(raw.bytes.byteOffset, raw.bytes.byteOffset + raw.bytes.byteLength) as ArrayBuffer, { headers: { ...headers, "Content-Type": "text/plain; charset=utf-8", "Content-Disposition": 'attachment; filename="manufacturer-rfq-draft.txt"', "Content-Length": String(raw.bytes.length), "X-Content-SHA256": calculated, "X-Manufacturer-Applicability": raw.applicability } });
  } catch (error) { const status = error instanceof ManufacturerRfqApiError && error.status === 404 ? 404 : 502; return new Response(status === 404 ? "Черновик не найден." : "Черновик временно недоступен.", { status, headers }); }
}
