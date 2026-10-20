import type { Metadata } from "next";
import Link from "next/link";

import { EconomicsForm } from "./form";
import { MaterializeForm } from "./materialize-form";
import { ApiError, ConfigurationError, loadServerOfferEconomics, type ServerOfferEconomicsRecord } from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Экономика server offer — Syurai Procurement" };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
function failure(error: unknown) { if (error instanceof ConfigurationError) return "Operator API не настроен."; if (error instanceof ApiError && error.status === 404) return "Exact case или PASS offer не найден."; return "Economics evidence недоступен."; }

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams; const value = (name: string) => typeof params[name] === "string" ? params[name] as string : "";
  const caseId = value("case_id"); const offerId = value("offer_id"); const version = Number(value("version"));
  const valid = ID.test(caseId) && ID.test(offerId) && Number.isInteger(version) && version >= 1;
  let record: ServerOfferEconomicsRecord | null = null; let error: string | null = null;
  if (valid) try { record = await loadServerOfferEconomics(caseId, version, offerId); } catch (caught) { error = failure(caught); }
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1440px,calc(100%-1rem))] py-8">
    <header className="border-b border-slate-200 pb-6"><p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S89 · controlled case materialization</p><h1 className="mt-2 text-3xl font-black sm:text-5xl">Три сценария экономики</h1><p className="max-w-3xl text-sm leading-6 text-slate-600">Только PASS server-offer review может стать источником goods и НДС. Base, realistic и conservative требуют всех статей и явных допущений.</p><Link className="text-sm font-bold text-blue-700" href="/">Дела</Link></header>
    {!valid && <form action="/server-offer-economics" className="mt-6 grid gap-3 rounded-xl bg-white p-5 sm:grid-cols-4" method="get"><input name="case_id" placeholder="Case ID" required /><input name="version" placeholder="Version" required /><input name="offer_id" placeholder="Offer ID" required /><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white">Открыть</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 font-bold text-red-900">{error}</p>}
    {record && <><section className="mt-6 rounded-xl border border-slate-200 bg-white p-5"><h2 className="m-0 text-xl font-black">Exact evidence</h2><p className="text-sm">Case {record.evidence.case.case_id} v{record.evidence.case.version} · НМЦК {record.evidence.case.nmck_ex_vat} RUB</p><p className="text-sm">Offer {record.evidence.offer_review.evidence.proposal.offer_id} · review <strong>{record.evidence.offer_review.decision?.status}</strong></p></section>{record.package ? <><section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-emerald-950"><h2 className="m-0 text-xl font-black">Economics COMPLETE · recommendation UNKNOWN</h2><p className="break-all font-mono text-xs">{record.package.package_sha256}</p>{record.package.scenario_set.scenarios.map((scenario) => <p className="text-sm" key={scenario.kind}><strong>{scenario.kind}</strong>: revenue {scenario.economics.contract_revenue}; assumptions {scenario.assumptions.join("; ")}</p>)}</section><MaterializeForm record={record} /></> : <EconomicsForm record={record} />}</>}
  </div></main>;
}
