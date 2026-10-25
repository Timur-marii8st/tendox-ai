import "server-only";
import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { validSnapshot, type ProfileCapabilities, type ProfileSaveCommand, type ProfileSelection, type ProfileSnapshot, type VersionPage } from "./company-profile";

export const profileCookie = "procurement_personal_session";
export class ProfileApiError extends Error {
  constructor(public status: number, public detail?: unknown) { super(`Profile API ${status}`); }
}
export async function profileRequest<T>(path: string, init: RequestInit = {}, credential?: string): Promise<T> {
  const token = credential ?? (await cookies()).get(profileCookie)?.value;
  if (!token) throw new ProfileApiError(401);
  const base = process.env.PROCUREMENT_API_URL;
  if (!base) throw new ProfileApiError(503);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${base.replace(/\/$/, "")}/v1/company-profile${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(15_000) });
  const body: unknown = await response.json();
  if (!response.ok) throw new ProfileApiError(response.status, (body as { detail?: unknown })?.detail);
  return body as T;
}
export const readCapabilities = (credential?: string) => profileRequest<ProfileCapabilities>("/capabilities", {}, credential);
export async function readProfile(version?: number): Promise<ProfileSnapshot> {
  const snapshot = await profileRequest<unknown>(version ? `/versions/${version}` : "");
  if (!validSnapshot(snapshot) || (version !== undefined && snapshot.version !== version)) throw new ProfileApiError(409);
  return snapshot;
}
export const readProfileHistory = (before?: number) => profileRequest<VersionPage>(`/versions${before ? `?before=${before}` : ""}`);
export const readProfileSelection = (selectionId?: string) => profileRequest<ProfileSelection>(selectionId ? `/selections/${encodeURIComponent(selectionId)}` : "/selection");
export async function saveProfile(command: ProfileSaveCommand, idempotencyKey: string): Promise<ProfileSnapshot> {
  const snapshot = await profileRequest<unknown>("/versions", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(command) });
  if (!validSnapshot(snapshot)) throw new ProfileApiError(409);
  return snapshot;
}
export const selectProfile = (version: number, sha: string, key: string = randomUUID()) => profileRequest<ProfileSelection>("/selections", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify({ version, snapshot_sha256: sha }) });
export async function optionalProfile<T>(read: () => Promise<T>): Promise<T | null> {
  try { return await read(); } catch (error) { if (error instanceof ProfileApiError && error.status === 404) return null; throw error; }
}
