import { readProfile, readProfileSelection } from "@/lib/company-profile-api";

export async function GET(request: Request) {
  const id = new URL(request.url).searchParams.get("selection");
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) return Response.json({ error: "selection_required" }, { status: 422 });
  try {
    const selection = await readProfileSelection(id);
    const snapshot = await readProfile(selection.profile_ref.version);
    if (snapshot.snapshot_sha256 !== selection.profile_ref.snapshot_sha256) return Response.json({ error: "profile_reference_conflict" }, { status: 409 });
    return Response.json({ schema_version: "company-profile-handoff-v1", selection, profile_ref: selection.profile_ref, profile_snapshot: snapshot }, { headers: { "Cache-Control": "no-store", "Content-Disposition": `attachment; filename="company-profile-v${snapshot.version}.json"` } });
  } catch {
    return Response.json({ error: "profile_handoff_unavailable" }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }
}
