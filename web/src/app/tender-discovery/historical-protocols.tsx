"use client";

import { useState, useTransition } from "react";
import { loadProtocolForCard, type HistoricalProtocolReport, type ProtocolNoticeRef } from "../../lib/eis-protocols";
import { loadHistoricalProtocols } from "./actions";
import { HistoricalProtocolReportView } from "./historical-protocol-report";

export function HistoricalProtocols({ notice }: { notice: ProtocolNoticeRef }) {
  // This inner component is remounted on every exact reference change. An old
  // response cannot attach its state to a newly selected notice version.
  return <ProtocolReader key={`${notice.purchase_number}:${notice.version_number}:${notice.notice_xml_sha256}`} notice={notice} />;
}

function ProtocolReader({ notice }: { notice: ProtocolNoticeRef }) {
  const [report, setReport] = useState<HistoricalProtocolReport>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  return <section aria-label={`Исторические протоколы закупки ${notice.purchase_number}`}
    className="mt-3 rounded-lg border border-slate-300 bg-slate-50 p-3">
    <h4 className="font-bold">Исторические протоколы</h4>
    <p className="mt-1 text-xs">Чтение сохранённых документов. Число конкурентов и выгодность требуют отдельного анализа.</p>
    <button type="button" disabled={pending} className="mt-2 rounded border border-slate-400 bg-white px-3 py-2 disabled:opacity-50"
      onClick={() => start(async () => {
        setReport(undefined); setError(undefined);
        const response = await loadProtocolForCard(notice, loadHistoricalProtocols);
        setReport(response.result); setError(response.error);
      })}>{pending ? "Читаю протоколы…" : "Показать сохранённые протоколы"}</button>
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
    {report && <HistoricalProtocolReportView report={report} />}
  </section>;
}
