import "server-only";
import { directoryMatches, type ManufacturerDirectory } from "./manufacturer-directory";

export async function readManufacturerDirectory(runId: string, responseSha: string | null): Promise<ManufacturerDirectory> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(runId)) throw new Error("Invalid saved search");
  const base = process.env.PROCUREMENT_API_URL;
  const token = process.env.PROCUREMENT_API_TOKEN;
  if (!base || !token) throw new Error("Manufacturer API is not configured");
  const response = await fetch(`${base.replace(/\/$/, "")}/v1/manufacturer-directory/${runId}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error("Saved manufacturer evidence is unavailable");
  const value: unknown = await response.json();
  if (!directoryMatches(value, runId, responseSha)) throw new Error("Saved manufacturer evidence is inconsistent");
  return value;
}
