import type { Metadata } from "next";
import Link from "next/link";

import { ServerOfferProposalForm } from "./form";

export const metadata: Metadata = {
  title: "Exact BOM и КП — Syurai Procurement",
  description: "Operator proposal exact server configuration and commercial terms",
};

export default async function ServerOfferProposalPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const value = (name: string) => typeof params[name] === "string" ? params[name] as string : "";
  const defaults = {
    case_id: value("case_id"),
    version: value("version"),
    binding_id: value("binding_id"),
    binding_sha256: value("binding_sha256"),
    run_id: value("run_id"),
    lead_id: value("lead_id"),
    document_id: value("document_id"),
    document_sha256: value("document_sha256"),
  };
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1120px,calc(100%-1rem))] py-6 sm:w-[min(1120px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S86 · operator proposal</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Exact BOM и коммерческое предложение</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            Свяжите конкретную найденную модель, reviewed requirement-set binding и
            immutable документ поставщика. Исходные строки и коммерческие условия
            вводятся с точными locators; сервер сохраняет proposal для независимой проверки.
          </p>
          <nav className="mt-4 flex flex-wrap gap-4 text-sm font-bold">
            <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
            <Link className="text-blue-700 hover:underline" href="/document-upload">Загрузить КП</Link>
            <Link className="text-blue-700 hover:underline" href="/requirement-set-binding">Requirement binding</Link>
          </nav>
        </header>
        <ServerOfferProposalForm defaults={defaults} />
      </div>
    </main>
  );
}
