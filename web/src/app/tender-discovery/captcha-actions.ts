"use server";
import { captchaPayload } from "@/lib/supplier-captcha";

export async function captchaCommand(operation: string, payload: unknown): Promise<{ result?: unknown; error?: string }> {
  if (!captchaPayload(operation, payload)) return { error: "Некорректная команда браузеру." };
  const { PROCUREMENT_API_URL: url, PROCUREMENT_API_TOKEN: token } = process.env;
  if (!url || !token) return { error: "Доступ к браузеру не настроен." };
  try {
    const response = await fetch(`${url.replace(/\/$/, "")}/v1/tender-discovery/supplier-captcha/${operation}`, {
      method: "POST", cache: "no-store", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) {
      await response.body?.cancel();
      return { error: response.status === 409 ? "Сессия занята, ещё не готова или выбранная попытка изменилась. Обновите сохранённую выдачу." :
        response.status === 404 ? "Сессия завершилась или недоступна." : "Серверный браузер временно недоступен." };
    }
    if (!response.body || response.headers.get("content-type")?.split(";", 1)[0] !== "application/json" ||
        !response.headers.get("Cache-Control")?.includes("no-store")) {
      await response.body?.cancel(); return { error: "Ответ браузера не подтверждён." };
    }
    const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.byteLength;
        if (size > 1048576) { await reader.cancel(); return { error: "Кадр браузера слишком большой." }; }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return { result: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) };
  } catch { return { error: "Связь с серверным браузером прервалась. Сессия ограничена десятью минутами." }; }
}
