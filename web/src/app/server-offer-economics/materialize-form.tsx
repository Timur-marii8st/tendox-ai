"use client";

import { useActionState } from "react";
import Link from "next/link";

import { materializeCase, type MaterializationState } from "./actions";
import type { ServerOfferEconomicsRecord } from "@/lib/procurement-api";

const initial: MaterializationState = {};

export function MaterializeForm({ record }: { record: ServerOfferEconomicsRecord }) {
  const [state, action, pending] = useActionState(materializeCase, initial);
  const pkg = record.package;
  if (!pkg) return null;
  return <form action={action} className="mt-6 rounded-xl border border-blue-200 bg-blue-50 p-5 text-blue-950">
    <input name="case-id" type="hidden" value={pkg.case_id} />
    <input name="case-version" type="hidden" value={pkg.case_version} />
    <input name="offer-id" type="hidden" value={pkg.offer_id} />
    <input name="economics-id" type="hidden" value={pkg.economics_id} />
    <input name="package-sha256" type="hidden" value={pkg.package_sha256} />
    <h2 className="m-0 text-xl font-black">Создать следующую версию кейса</h2>
    <p className="text-sm leading-6">Сервер перенесёт exact КП и три сценария. Из review будет подтверждён только technical PASS; остальные hard gates останутся без оценки, поэтому PARTICIPATE здесь не возникает.</p>
    <button className="rounded-lg bg-blue-800 px-4 py-2 font-bold text-white disabled:opacity-50" disabled={pending || Boolean(state.success)}>{pending ? "Создаём…" : `Создать v${pkg.case_version + 1}`}</button>
    {state.error && <p className="font-bold text-red-800">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-800">{state.success} {state.nextVersion && <Link className="underline" href={`/hard-gate-assessment?case_id=${encodeURIComponent(pkg.case_id)}&version=${state.nextVersion}`}>Открыть hard gates →</Link>}</p>}
  </form>;
}
