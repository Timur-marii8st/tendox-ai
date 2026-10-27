import type { NoticeProfileReport } from "../../lib/notice-profile-comparison";
import type { MixedComparisonResult } from "../../lib/procurement-api";

const methodLabels: Record<string, string> = {
  epNotificationEF2020: "Электронный аукцион", epNotificationEZK2020: "Электронный запрос котировок", epNotificationEOK2020: "Электронный открытый конкурс",
  purchaseNoticeAESMBO: "Электронный аукцион для МСП", purchaseNoticeZKESMBO: "Электронные котировки для МСП", purchaseNoticeKESMBO: "Электронный конкурс для МСП", purchaseNoticeZPESMBO: "Электронный запрос предложений для МСП", purchaseNotice: "Иной способ закупки",
};

function Facts({ row, kind }: { row: MixedComparisonResult["rows"][number]; kind: "price" | "deadline" | "method" }) {
  if (row.law === "44") {
    const e = row.evidence;
    return <>{kind === "price" ? <>{e.nmck_rub ?? "UNKNOWN"} RUB · НМЦК по извещению, НДС не уточнён</> : kind === "deadline" ? e.deadline ?? "Срок UNKNOWN" : methodLabels[e.document_type] ?? "Способ требует уточнения"}</>;
  }
  const n = row.notice;
  if (kind === "deadline") { const d = n.selected_deadline ?? n.deadline; return <>{d.value ?? `${d.raw ?? "нет данных"} · часовой пояс / применимость UNKNOWN`}</>; }
  if (kind === "method") return <>{n.method_name.value ?? methodLabels[n.document_type] ?? "Способ требует уточнения"}</>;
  return <>{n.lots.map((lot, i) => {
    const generic = n.document_type === "purchaseNotice";
    const amount = lot.source_price_kind === "TEXT_ONLY" ? null : lot.source_price_kind ? lot.source_amount?.value : generic ? null : lot.initial_sum.value;
    const currency = lot.source_currency_status === "UNKNOWN" ? "UNKNOWN" : lot.currency_letter_code?.value ?? lot.currency.value ?? "UNKNOWN";
    return <p key={i}>Лот {lot.ordinal.value ?? i + 1}: {amount ?? "UNKNOWN"} {currency} · {lot.source_price_kind ?? (generic ? "Тип цены UNKNOWN" : "начальная сумма")}</p>;
  })}<p className="mt-1">Суммы лотов не складываются в цену участия; НДС не уточнён.</p></>;
}

export function NoticeProfileReportView({ report }: { report: NoticeProfileReport }) {
  return <section aria-label="Сравнение закупок с профилем компании" className="mt-4 rounded-xl border border-blue-300 bg-white p-4">
    <h3 className="text-lg font-bold">Закупки и ваш профиль · {report.profile_name} · версия {report.profile_ref.version}</h3>
    <p className="mt-2 text-sm">Проверено {new Date(report.compared_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} МСК.
      Сравниваются выбранные сохранённые XML-версии. Частичная проверка не означает допуск к участию.</p>
    <p className="mt-2 text-sm">Прибыль не рассчитана: нужны подтверждённые расходы, КП и сценарии.
      Отчёт пока не сохраняется в истории; его можно распечатать средствами браузера.</p>
    <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[640px] border-collapse text-left text-sm">
      <thead><tr><th className="border p-3">Условие</th>{report.rows.map(row => <th key={`${row.notice_ref.law}:${row.notice_ref.purchase_number}`} className="border p-3">
        {row.notice_ref.law}-ФЗ · № {row.notice_ref.purchase_number}<p className="font-normal">{row.subject}</p>
        <p className="mt-2">{row.overall_status === "FAIL" ? "FAIL · есть блокирующее условие" : "UNKNOWN · нужны сведения"}</p>
      </th>)}</tr></thead>
      <tbody>{([['price', 'Цена в источнике'], ['deadline', 'Окончание подачи по XML'], ['method', 'Способ закупки']] as const).map(([kind, label]) => <tr key={kind}><th className="border p-3 align-top">{label}</th>{report.source.rows.map((row, i) => <td key={i} className="border p-3 align-top"><Facts row={row} kind={kind} /></td>)}</tr>)}
      {report.rows[0]?.checks.map(check => <tr key={check.check_id}><th className="border p-3 align-top">{check.label}</th>
        {report.rows.map(row => { const value = row.checks.find(item => item.check_id === check.check_id); return <td key={`${row.notice_ref.law}:${row.notice_ref.purchase_number}`} className="border p-3 align-top">
          {value ? <><strong className={value.status === "FAIL" ? "text-red-800" : "text-slate-800"}>{value.status}</strong><p className="mt-1">{value.reason}</p>
            {value.missing.length > 0 && <p className="mt-2 text-amber-900">Нужно уточнить: {value.missing.join("; ")}</p>}
            <details className="mt-2 text-xs"><summary>Источники</summary>{[...value.case_sources, ...value.profile_sources.map(source => source.provenance)].map((source, i) => <p key={i} className="break-all">{source.document_id} · {source.locator}</p>)}</details>
          </> : "UNKNOWN · условие не проверено"}
        </td>; })}</tr>)}</tbody>
    </table></div>
    <details className="mt-3 text-xs"><summary>Версии и контрольные хеши</summary><p className="break-all">Профиль: {report.profile_ref.snapshot_sha256}<br />Входы: {report.input_sha256}</p>
      {report.rows.map(row => <p key={`${row.notice_ref.law}:${row.notice_ref.purchase_number}`} className="break-all">{row.notice_ref.purchase_number} · v{row.notice_ref.version_number} · XML {row.notice_ref.notice_xml_sha256}</p>)}
    </details>
  </section>;
}
