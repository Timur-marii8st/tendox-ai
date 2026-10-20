"use client";
import { useEffect, useRef, useState } from "react";
import type { SupplierSearchRequest } from "@/lib/eis-supplier-search";
import type { SavedSupplierSerp } from "@/lib/eis-supplier-serp";
import { captchaFrame, captchaView, type CaptchaEngine, type CaptchaView } from "@/lib/supplier-captcha";
import { captchaCommand } from "./captcha-actions";

const names = { BING: "Bing", YANDEX: "Яндекс", GOOGLE: "Google" };
export function CaptchaAssist({ request, result, onVerified }: {
  request: SupplierSearchRequest; result: SavedSupplierSerp; onVerified: () => void;
}) {
  const [session, setSession] = useState<CaptchaView>();
  const [image, setImage] = useState<string>();
  const [text, setText] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const current = useRef<CaptchaView | undefined>(undefined);
  const live = useRef(true);
  const resume = useRef(onVerified);
  const resumed = useRef<string | undefined>(undefined);
  useEffect(() => { resume.current = onVerified; }, [onVerified]);
  const sessionId = session?.session_id;
  const sessionStatus = session?.status;
  const finalizing = session?.finalizing;
  const retryReady = session?.retry_ready;
  useEffect(() => {
    if (!sessionId || sessionStatus !== "VERIFIED" || !retryReady || resumed.current === sessionId) return;
    resumed.current = sessionId;
    const timer = setTimeout(() => { if (live.current) resume.current(); }, (current.current?.retry_after_seconds ?? 0) * 1000 + 1000);
    return () => clearTimeout(timer);
  }, [sessionId, sessionStatus, retryReady]);
  useEffect(() => { live.current = true; return () => {
    live.current = false;
    const s = current.current;
    if (s && ["STARTING", "WAITING"].includes(s.status)) void captchaCommand("cancel", { session_id: s.session_id });
  }; }, []);
  useEffect(() => {
    if (!sessionId || !sessionStatus || (!["STARTING", "WAITING"].includes(sessionStatus) && !finalizing)) return;
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const id = sessionId!;
      const status = await captchaCommand("status", { session_id: id });
      if (stopped) return;
      if (!captchaView(status.result) || status.result.session_id !== id || status.result.run_id !== result.report.run_id) {
        setError(status.error ?? "Состояние браузера не подтверждено.");
      } else {
        current.current = status.result; setSession(status.result);
        if (status.result.status === "WAITING") {
          const frame = await captchaCommand("frame", { session_id: id });
          if (stopped) return;
          if (captchaFrame(frame.result)) setImage(`data:image/jpeg;base64,${frame.result.data}`);
          else if (frame.error) setError(frame.error);
        }
      }
      if (!stopped) timer = setTimeout(poll, 1000);
    }
    void poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [sessionId, sessionStatus, finalizing, result.report.run_id]);
  async function start(engine: CaptchaEngine) {
    setBusy(true); setError(undefined); setImage(undefined);
    const reply = await captchaCommand("start", { request, run_id: result.report.run_id, engine });
    if (captchaView(reply.result) && reply.result.run_id === result.report.run_id && reply.result.engine === engine) {
      current.current = reply.result;
      if (live.current) setSession(reply.result);
      else void captchaCommand("cancel", { session_id: reply.result.session_id });
    } else if (live.current) setError(reply.error ?? "Браузер не открыт.");
    if (live.current) setBusy(false);
  }
  async function command(operation: "input" | "verify" | "cancel", event?: unknown) {
    if (!session || busy) return;
    setBusy(true); setError(undefined);
    const reply = await captchaCommand(operation, { session_id: session.session_id, ...(event ? { event } : {}) });
    if (!live.current) return;
    if (captchaView(reply.result) && reply.result.session_id === session.session_id && reply.result.run_id === result.report.run_id) {
      current.current = reply.result; setSession(reply.result);
      if (operation === "verify") {
        if (reply.result.status === "VERIFIED" && reply.result.retry_ready) {
          setImage(undefined); setText("");
        } else setError(reply.result.status === "VERIFIED" ? "Выдача подтверждена, но условия запуска изменились. Повторный поиск не разрешён; обновите сохранённую попытку." : "Возврат к выдаче не подтверждён. Завершите проверку в окне и нажмите кнопку ещё раз.");
      }
    } else setError(reply.error ?? "Команда не выполнена.");
    setBusy(false);
  }
  const active = !!session && ["STARTING", "WAITING"].includes(session.status);
  const blocked = result.report.batch?.attempts.filter(a => a.status === "BLOCKED" && a.engine in names) ?? [];
  if (!blocked.length && !session) return null;
  return <section className="mt-3 rounded border border-amber-400 p-3" data-captcha-assist>
    <h4 className="font-semibold">Пройти проверку поисковика вручную</h4>
    <p className="text-sm">Открывается браузер на сервере в профиле вашей организации. Нажимайте прямо на изображении. Сессия работает до 10 минут.</p>
    {!active && session?.status !== "VERIFIED" && <div className="mt-2 flex gap-2">{blocked.map(a => <button key={a.engine} type="button" disabled={busy} className="rounded border px-3 py-2" onClick={() => start(a.engine as CaptchaEngine)}>Открыть {names[a.engine as CaptchaEngine]}</button>)}</div>}
    {session && <p role="status">{session.status === "STARTING" ? "Открываем серверный браузер…" : session.status === "WAITING" ? `Окно ${names[session.engine]}. Завершение: ${new Date(session.expires_at).toLocaleTimeString()}.` : session.status === "VERIFIED" ? session.finalizing ? "Сохраняем подтверждённую выдачу…" : session.retry_ready ? "Выдача подтверждена. Продолжаем поиск с сохранённой сессией…" : "Выдача подтверждена. Повторный поиск пока не разрешён." : "Сессия завершена. Проверка выдачи не подтверждена."}</p>}
    {active && image && <div className="mt-2">
      {/* Server screenshot is an authenticated ephemeral data URL. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={image} alt="Живое окно серверного браузера для ручного прохождения CAPTCHA" draggable={false} className="w-full max-w-[1280px] border" onClick={e => {
        if (session?.status !== "WAITING") return;
        const rect = e.currentTarget.getBoundingClientRect();
        void command("input", { kind: "click", x: Math.min(1279, Math.max(0, Math.floor((e.clientX - rect.left) * 1280 / rect.width))), y: Math.min(719, Math.max(0, Math.floor((e.clientY - rect.top) * 720 / rect.height))) });
      }} />
      <div className="mt-2 flex flex-wrap gap-2">
        <input aria-label="Текст проверки" value={text} maxLength={128} onChange={e => setText(e.target.value)} className="rounded border px-2" placeholder="Текст для выбранного поля" />
        <button type="button" disabled={busy || !text} onClick={() => { void command("input", { kind: "type", text }); setText(""); }}>Ввести текст</button>
        {(["Enter", "Tab", "Backspace"] as const).map(key => <button key={key} type="button" disabled={busy} onClick={() => command("input", { kind: "key", key })}>{key}</button>)}
        <button type="button" disabled={busy} onClick={() => command("input", { kind: "wheel", delta_y: -500 })}>↑ Прокрутить</button>
        <button type="button" disabled={busy} onClick={() => command("input", { kind: "wheel", delta_y: 500 })}>↓ Прокрутить</button>
      </div>
    </div>}
    {active && <div className="mt-3 flex gap-3">
      <button type="button" disabled={busy || session.status !== "WAITING"} className="rounded border px-3 py-2" onClick={() => command("verify")}>Я прошёл проверку — продолжить поиск</button>
      <button type="button" disabled={busy} className="rounded border px-3 py-2" onClick={() => command("cancel")}>Закрыть браузер</button>
    </div>}
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
  </section>;
}
