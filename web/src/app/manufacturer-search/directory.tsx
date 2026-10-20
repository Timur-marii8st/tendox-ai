import Link from "next/link";
import { readManufacturerDirectory } from "@/lib/manufacturer-directory-api";

export async function ReviewedManufacturers({ runId, responseSha }: { runId: string; responseSha: string | null }) {
  let directory;
  try { directory = await readManufacturerDirectory(runId, responseSha); }
  catch { return <p className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-900" role="alert">Сводка проверок недоступна. Подтверждённые изготовители сейчас не показаны.</p>; }
  return <section className="mt-6 rounded-xl border bg-white p-5">
    <h2 className="text-xl font-black">Проверки изготовителей этого поиска</h2>
    <p className="text-sm">Охват сохранённых проверок: {directory.coverage}. Итог для показанных записей: {directory.overall_status}.</p>
    <p className="text-xs text-slate-600">Проверено {new Date(directory.evaluated_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })}. Сводка охватывает только записи этого ответа реестра. Техническое соответствие, продавец и КП остаются UNKNOWN.</p>
    {directory.coverage === "INCOMPLETE" && <p className="rounded-lg bg-amber-50 p-3 text-sm">Сводка неполна: источник не завершён или превышен предел проверок. Полнота неизвестна; подтверждённые группы не формируются.</p>}
    {directory.groups.map((group, index) => <article className="mt-3 rounded-lg border p-3" key={index}>
      <h3 className="font-bold">{group.legal_name} · {group.status}</h3>
      <p className="text-sm">{group.key.country_code} · {group.key.identifier_scheme}: {group.key.registration_id}</p>
      <p className="text-sm">{group.product_names.join("; ")}</p>
      {group.status === "UNKNOWN" && <p className="text-sm text-amber-900">Реквизиты совпали, но юридические наименования противоречат друг другу.</p>}
      <p className="text-xs text-slate-600">Объединение по реквизитам не означает взаимозаменяемость товаров.</p>
    </article>)}
    {directory.groups.length === 0 && <p className="text-sm">Групп подтверждённых изготовителей нет.</p>}
    <div className="mt-4 space-y-3">{directory.records.map(record => <article className="rounded-lg border p-3" key={record.record_id}>
      <h3 className="font-bold">{record.product_name} · {record.status}</h3>
      <p className="text-xs">Документ реестра: {record.source_status}. Проверка изготовителя: {record.review_status}.</p>
      {record.reason_codes.includes("IDENTITY_CONFLICT") && <p className="text-sm text-amber-900">Для одной записи подтверждены разные юридические лица.</p>}
      {record.reason_codes.includes("LEGAL_NAME_CONFLICT") && <p className="text-sm text-amber-900">Юридические наименования противоречат друг другу.</p>}
      {record.source_status === "FAIL" && <p className="text-sm text-red-900">Документ реестра просрочен.</p>}
      {record.review_evidence.length === 0 && <p className="text-sm">{directory.coverage === "INCOMPLETE" ? "Проверки этой записи не включены в неполную сводку." : "Независимая проверка ещё не завершена."}</p>}
      {record.review_evidence.map(proof => <Link className="mt-2 block text-xs text-blue-700 underline" key={proof.proposal_id} href={`/manufacturer-review?proposal=${proof.proposal_id}`}>{proof.identity.legal_name} · {proof.current_status} · открыть доказательства и решение</Link>)}
      {record.status === "PASS" && directory.groups.some(g => g.status === "PASS" && g.record_ids.includes(record.record_id)) && record.review_evidence.filter(proof => proof.current_status === "PASS").map(proof => <Link className="mt-3 block text-sm font-bold text-blue-700 underline" key={`rfq-${proof.proposal_id}`} href={`/manufacturer-rfq?proposal=${proof.proposal_id}`}>Подготовить черновик запроса КП</Link>)}
    </article>)}</div>
  </section>;
}
