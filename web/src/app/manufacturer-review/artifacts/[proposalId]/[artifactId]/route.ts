import { createHash } from "node:crypto";
import { ApiError, downloadManufacturerArtifact, readManufacturerArtifactMetadata, readManufacturerProposal } from "@/lib/procurement-api";
import { UUID_PATTERN } from "@/lib/manufacturer-review";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ proposalId: string; artifactId: string }> }) {
  const { proposalId, artifactId } = await context.params;
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  if (!UUID_PATTERN.test(proposalId) || !UUID_PATTERN.test(artifactId)) return new Response("Некорректный идентификатор.", { status: 400, headers });
  try {
    const proposal = await readManufacturerProposal(proposalId);
    const citation = proposal.citations.find(item => item.artifact_id === artifactId);
    if (!citation) return new Response("Документ не относится к предложению.", { status: 404, headers });
    const [metadata, raw] = await Promise.all([readManufacturerArtifactMetadata(proposalId, artifactId, citation.artifact_sha256), downloadManufacturerArtifact(proposalId, artifactId)]);
    const calculated = createHash("sha256").update(raw.bytes).digest("hex");
    if (metadata.sha256 !== citation.artifact_sha256 || raw.sha256 !== metadata.sha256 || calculated !== metadata.sha256 || raw.bytes.length !== metadata.byte_size) return new Response("Целостность документа не подтверждена.", { status: 502, headers });
    return new Response(raw.bytes.buffer.slice(raw.bytes.byteOffset, raw.bytes.byteOffset + raw.bytes.byteLength) as ArrayBuffer, { headers: { ...headers, "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="manufacturer-evidence.pdf"', "Content-Length": String(raw.bytes.length), "X-Content-SHA256": calculated } });
  } catch (error) {
    const status = error instanceof ApiError && [403, 404].includes(error.status) ? error.status : 502;
    return new Response(status === 403 ? "Reviewer-доступ к документу запрещён." : status === 404 ? "Документ не найден." : "Документ временно недоступен.", { status, headers });
  }
}
