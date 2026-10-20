import { NextRequest } from "next/server";

import { downloadApplicationReviewDocument } from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export async function GET(request: NextRequest): Promise<Response> {
  const packageId = request.nextUrl.searchParams.get("package_id");
  const documentId = request.nextUrl.searchParams.get("document_id");
  if (!packageId || !ID.test(packageId) || !documentId || !ID.test(documentId)) {
    return new Response("Invalid exact document identity", { status: 400 });
  }
  try {
    const document = await downloadApplicationReviewDocument(packageId, documentId);
    return new Response(document.bytes, {
      headers: {
        "Content-Type": document.contentType,
        "Content-Disposition": document.disposition,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new Response("Exact document is unavailable", { status: 404 });
  }
}
