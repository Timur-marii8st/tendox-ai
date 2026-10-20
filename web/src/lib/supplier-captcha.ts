import { validSupplierSearchRequest } from "./eis-supplier-search";

export const captchaEngines = ["BING", "YANDEX", "GOOGLE"] as const;
export type CaptchaEngine = typeof captchaEngines[number];
export type CaptchaView = { session_id: string; run_id: string; engine: CaptchaEngine;
  status: "STARTING" | "WAITING" | "VERIFIED" | "CANCELLED" | "EXPIRED" | "FAILED";
  expires_at: string; reason_code?: string | null; retry_after_seconds: number; retry_ready: boolean; finalizing?: boolean };
export type CaptchaFrame = { data: string; mime_type: "image/jpeg"; width: number; height: number };
export const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
export const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
export function captchaPayload(operation: string, payload: unknown): boolean {
  if (!object(payload)) return false;
  if (operation === "start") return Object.keys(payload).length === 3 &&
    validSupplierSearchRequest(payload.request) && uuid(payload.run_id) &&
    captchaEngines.includes(payload.engine as CaptchaEngine);
  if (!uuid(payload.session_id)) return false;
  if (["status", "frame", "verify", "cancel"].includes(operation)) return Object.keys(payload).length === 1;
  if (operation !== "input" || Object.keys(payload).length !== 2 || !object(payload.event)) return false;
  const e = payload.event;
  const number = (v: unknown, min: number, max: number) => Number.isInteger(v) && Number(v) >= min && Number(v) <= max;
  if (e.kind === "click") return Object.keys(e).length === 3 && number(e.x, 0, 1279) && number(e.y, 0, 719);
  if (e.kind === "wheel") return Object.keys(e).length === 2 && number(e.delta_y, -720, 720);
  if (e.kind === "type") return Object.keys(e).length === 2 && typeof e.text === "string" &&
    e.text.length > 0 && [...e.text].length <= 128 && !/[\x00-\x1f\x7f]/.test(e.text);
  return e.kind === "key" && Object.keys(e).length === 2 && ["Enter", "Tab", "Backspace", "Space", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(String(e.key));
}
export function captchaView(v: unknown): v is CaptchaView {
  return object(v) && uuid(v.session_id) && uuid(v.run_id) && captchaEngines.includes(v.engine as CaptchaEngine) &&
    ["STARTING", "WAITING", "VERIFIED", "CANCELLED", "EXPIRED", "FAILED"].includes(String(v.status)) &&
    typeof v.expires_at === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v.expires_at) && Number.isFinite(Date.parse(v.expires_at)) &&
    Number.isInteger(v.retry_after_seconds) && Number(v.retry_after_seconds) >= 0 && Number(v.retry_after_seconds) <= 60 && typeof v.retry_ready === "boolean" &&
    (v.finalizing === undefined || typeof v.finalizing === "boolean");
}
export function captchaFrame(v: unknown): v is CaptchaFrame {
  return object(v) && v.mime_type === "image/jpeg" && v.width === 1280 && v.height === 720 &&
    typeof v.data === "string" && v.data.length <= 710000 && v.data.startsWith("/9j/") && /^[A-Za-z0-9+/]+={0,2}$/.test(v.data);
}
