import { NextRequest } from "next/server";
import { ApiError, ConfigurationError, downloadApplicationHandoff } from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export async function GET(request: NextRequest): Promise<Response> {
  const packageId = request.nextUrl.searchParams.get("package_id");
  if (!packageId || !ID.test(packageId)) {
    return new Response("Invalid exact package identity", { status: 400 });
  }
  try {
    const bytes = await downloadApplicationHandoff(packageId);
    return new Response(bytes, {
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": "attachment; filename=application-handoff.zip",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return new Response("Handoff unavailable; verify current approval, admission and originals", {
        status: error.status === 409 || error.status === 422 ? error.status : 404,
      });
    }
    if (error instanceof ConfigurationError) {
      return new Response("Executor token is not configured", { status: 503 });
    }
    return new Response("Handoff temporarily unavailable", { status: 503 });
  }
}
