import { WorkflowApiError, WorkflowConfigurationError, downloadDiscoveryArtifact } from "@/lib/eis-workflow-api";

export const dynamic = "force-dynamic";

const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const DIGEST = /^[0-9a-f]{64}$/;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ runId: string; digest: string }> },
): Promise<Response> {
  const { runId, digest } = await params;
  if (!RUN_ID.test(runId) || !DIGEST.test(digest)) {
    return new Response("Invalid exact artifact identity", { status: 400 });
  }
  try {
    const artifact = await downloadDiscoveryArtifact(runId, digest);
    return new Response(artifact.bytes, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": artifact.disposition,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof WorkflowConfigurationError) {
      return new Response("Artifact service is not configured", { status: 503 });
    }
    if (error instanceof WorkflowApiError) {
      return new Response("Exact artifact is unavailable", {
        status: error.status === 400 ? 400 : error.status === 404 ? 404 : 502,
      });
    }
    return new Response("Artifact is temporarily unavailable", { status: 503 });
  }
}
