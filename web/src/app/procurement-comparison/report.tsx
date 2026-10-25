import { rub, type ComparisonReport, type Check } from "../../lib/procurement-comparison";

export const labels = { PASS: "PASS · проверенное условие", FAIL: "FAIL · несоответствие", UNKNOWN: "UNKNOWN · нужны сведения" };

function Evidence({ check }: { check: Check }) {
  return <details><summary>Источники ({check.case_sources.length + check.profile_sources.length})</summary>
    {check.profile_sources.map((source, i) => <p key={`p${i}`}><b>Профиль:</b> {source.provenance.document_id} · {source.provenance.locator}
      <small>{source.kind} · {source.recorded_by} · {source.recorded_at}<br />SHA-256: {source.source_sha256}</small></p>)}
    {check.case_sources.map((source, i) => <p key={`c${i}`}><b>Кейс:</b> {source.document_id} · {source.locator}
      <small>Способ: {source.extractor}</small></p>)}
    {!check.profile_sources.length && !check.case_sources.length && <p>Подтверждающий источник отсутствует.</p>}
  </details>;
}

export function ComparisonReportView({ report }: { report: ComparisonReport }) {
  return <section aria-label="Результат сравнения">
    <h2>Сравнительная таблица</h2>
    <p>Отчёт не сохранён в истории или аудите. Для повторного просмотра запустите сравнение заново.</p>
    <p><b>Профиль v{report.profile_ref.version}</b> · {report.profile_name} · сохранён {report.profile_created_at}</p>
    <p>На момент {report.compared_at}. PASS относится к конкретной проверке. Частичная проверка не означает полный допуск.
      Обязательный FAIL блокирует закупку. Ранжирование прибыльности отсутствует.</p>
    <div className="comparison-scroll" tabIndex={0} aria-label="Таблица с горизонтальной прокруткой"><table>
      <caption>Условия выбранных закупок · RUB, суммы без НДС</caption>
      <thead><tr><th scope="col">Условие</th>{report.rows.map(row => <th scope="col" key={row.case_ref.case_id}>
        {row.subject}<small>Кейс v{row.case_ref.version} · {row.case_ref.case_id}</small>
      </th>)}</tr></thead>
      <tbody>
        <tr><th scope="row">Итог проверки</th>{report.rows.map(row => <td key={row.case_ref.case_id}>
          <strong className={`comparison-${row.overall_status.toLowerCase()}`}>{labels[row.overall_status]}</strong>
          <p>{row.overall_status === "FAIL" ? "Есть обязательное несоответствие." : "Полный допуск не подтверждён."}</p>
        </td>)}</tr>
        <tr><th scope="row">НМЦК без НДС</th>{report.rows.map(row => <td key={row.case_ref.case_id}>{rub(row.nmck_ex_vat)}<small>Начальная цена не доказывает выручку.</small></td>)}</tr>
        {report.rows[0].checks.map(check => <tr key={check.check_id}><th scope="row">{check.label}<small>Обязательная проверка</small></th>
          {report.rows.map(row => {
            const item = row.checks.find(value => value.check_id === check.check_id);
            return <td key={row.case_ref.case_id}>{item ? <>
              <strong className={`comparison-${item.status.toLowerCase()}`}>{labels[item.status]}</strong>
              <p>{item.reason}</p>
              {item.missing.length > 0 && <div className="comparison-missing"><b>Нужно уточнить:</b><ul>{item.missing.map(value => <li key={value}>{value}</li>)}</ul></div>}
              <Evidence check={item} />
            </> : <strong>UNKNOWN · Проверка отсутствует</strong>}</td>;
          })}</tr>)}
        <tr><th scope="row">Сценарии экономики<small>Прогноз с допущениями</small></th>{report.rows.map(row => <td key={row.case_ref.case_id}>
          {row.economics.length === 0 ? <p>UNKNOWN · Прибыль не рассчитана.</p> : row.economics.map(scenario => <details key={scenario.kind}>
            <summary>{scenario.kind} · прогноз прибыли {rub(scenario.profit_ex_vat)}</summary>
            <p>Выручка: {rub(scenario.revenue_ex_vat)}<br />Все расходы: {rub(scenario.costs_ex_vat)}<br />
              НДС: доля {scenario.nds_rate}. Прочие налоги в расходах: {rub(scenario.taxes)}.</p>
            <b>Допущения:</b><ul>{scenario.assumptions.map(value => <li key={value}>{value}</li>)}</ul>
            {scenario.sources.map((source, i) => <small key={i}>Источник: {source.document_id} · {source.locator}</small>)}
          </details>)}
        </td>)}</tr>
        <tr><th scope="row">Точные входы</th>{report.rows.map(row => <td key={row.case_ref.case_id}><details><summary>Версия и SHA-256</summary>
          <small>Case input: {row.case_ref.input_sha256}<br />Полный снимок с оценкой: {row.case_snapshot_sha256}</small>
        </details></td>)}</tr>
      </tbody>
    </table></div>
    <details className="comparison-receipt"><summary>Воспроизводимость и ограничения интеграции</summary>
      <p>Версия профиля: {report.profile_ref.version} · SHA-256: {report.profile_ref.snapshot_sha256}</p>
      <p>Policy: {report.comparison_policy_version}<br />Input SHA-256: {report.input_sha256}<br />Отчёт: {report.comparison_id}</p>
      {report.persistence === "LOCAL_DEMO_EPHEMERAL" ? <p>Локальный отчёт не сохранён в БД; audit отсутствует. Использованы статические синтетические примеры SnapshotV1. Реальный API профиля в этом демо не используется.</p> : <p>Прочитаны сохранённые версии профиля и кейсов. Отчёт не сохранён в БД; audit отсутствует. Свежая проверка ЕИС не выполнялась.</p>}
    </details>
  </section>;
}
