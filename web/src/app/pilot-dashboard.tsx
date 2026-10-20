"use client";

import { useActionState, useEffect, useState } from "react";
import Link from "next/link";

import { evaluateCase, importCase, runSourcing, type FormState } from "@/app/actions";
import type {
  CaseCardData,
  DashboardData,
  GateCheck,
  Provenance,
  RecommendationDecision,
} from "@/lib/procurement-api";

const emptyState: FormState = {};
const colors = {
  green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  yellow: "border-amber-200 bg-amber-50 text-amber-900",
  red: "border-red-200 bg-red-50 text-red-800",
};
type Status = { color: keyof typeof colors; label: string; stale?: boolean };

const gateLabels: Record<string, string> = {
  legal: "Юридические требования",
  participant: "Требования к участнику",
  technical: "Техническое соответствие",
  company_policy: "Политика компании",
  logistics: "Логистика",
  document: "Документы",
};
const lawLabels: Record<string, string> = {
  "44-fz": "44-ФЗ",
  "223-fz": "223-ФЗ",
  commercial: "Коммерческая закупка",
};
const methodLabels: Record<string, string> = {
  electronic_auction: "Электронный аукцион",
  electronic_competition: "Электронный конкурс",
  quotation_request: "Запрос котировок",
  proposal_request: "Запрос предложений",
  single_supplier: "Единственный поставщик",
  electronic_store: "Электронный магазин",
  other_competitive_223: "Иная конкурентная закупка по 223-ФЗ",
  non_competitive_223: "Неконкурентная закупка по 223-ФЗ",
  closed: "Закрытая процедура",
};
const scenarioLabels: Record<string, string> = {
  base: "Базовый",
  realistic: "Реалистичный",
  conservative: "Консервативный",
};
const costLabels: Record<string, string> = {
  goods: "Товар / производство",
  packaging: "Упаковка",
  logistics: "Логистика",
  loading_unloading: "Погрузка и разгрузка",
  storage: "Хранение",
  installation: "Монтаж",
  payroll_travel: "Зарплата и командировки",
  subcontracting: "Субподряд",
  insurance: "Страхование",
  finance: "Стоимость денег",
  bank_guarantee: "Банковская гарантия",
  platform_fees: "Комиссия площадки",
  taxes: "Налоги",
  certification: "Сертификация",
  warranty: "Гарантия",
  risk_reserve: "Резерв рисков",
  penalty_reserve: "Резерв штрафов",
  other: "Прочие расходы",
};

function stamp(value?: string, zone?: string): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return "не указан";
  return `${new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: zone,
  }).format(new Date(value))}${zone ? ` (${zone})` : ""}`;
}

function money(value?: string | null): string {
  if (!value) return "не указано";
  const [significand, exponent] = value.toLowerCase().split("e");
  if (exponent) return `${value} ₽`;
  const [whole, fraction] = significand.split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${fraction ? `,${fraction}` : ""} ₽`;
}

function percent(value?: string | null): string {
  if (!value || !/^-?\d+(\.\d+)?$/.test(value)) return "не указана";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = unsigned.split(".");
  const digits = `${whole}${fraction}`.replace(/^0+(?=\d)/, "") || "0";
  const scale = Math.max(0, fraction.length - 2);
  const padded = digits.padStart(scale + 1, "0");
  const integer = scale ? padded.slice(0, -scale) : padded;
  const decimals = scale ? padded.slice(-scale).replace(/0+$/, "") : "";
  return `${negative ? "−" : ""}${integer}${decimals ? `,${decimals}` : ""}%`;
}

function timeLeft(value: string | undefined, now: number): string {
  const minutes = value ? Math.floor((new Date(value).getTime() - now) / 60_000) : Number.NaN;
  if (!Number.isFinite(minutes) || minutes <= 0) return "срок истёк или не указан";
  const days = Math.floor(minutes / 1_440);
  const hours = Math.floor((minutes % 1_440) / 60);
  const rest = minutes % 60;
  if (days) return `${days} д. ${hours} ч.`;
  if (hours) return `${hours} ч. ${rest} мин.`;
  return `${Math.max(1, rest)} мин.`;
}

function visualStatus(card: CaseCardData, now: number): Status {
  if (!card.evaluation) return { color: "yellow", label: "нет оценки" };
  const values: Record<RecommendationDecision, Status> = {
    participate: { color: "green", label: "участвовать" },
    needs_analysis: { color: "yellow", label: "нужен анализ" },
    do_not_participate: { color: "red", label: "не участвовать" },
  };
  const apiDecision = values[card.evaluation.recommendation.decision];
  if (apiDecision.color !== "green") return apiDecision;

  const deadline = card.case.tender.submission?.closes_at;
  const quoteDeadline = card.case.selected_quote?.valid_until;
  const fresh =
    new Date(card.evaluation.effective_at).getTime() <= now &&
    ["submission_open", "submission_closing"].includes(card.case.tender.stage) &&
    typeof deadline === "string" &&
    new Date(deadline).getTime() > now &&
    typeof quoteDeadline === "string" &&
    new Date(quoteDeadline).getTime() > now;
  return fresh ? apiDecision : { color: "yellow", label: "требуется пересчёт", stale: true };
}

function nextStep(status: Status): string {
  if (status.label === "нет оценки") return "Запустите оценку сохранённого снимка.";
  if (status.stale) return "Пересчитайте кейс с актуальным временем.";
  if (status.color === "red") return "Зафиксируйте отказ и не готовьте внешнее действие.";
  if (status.color === "yellow") return "Дополните данные и проверьте основания.";
  return "Проверьте основания; внешнее действие потребует отдельного подтверждения.";
}

function Source({ value }: { value?: Provenance | null }) {
  if (!value) return <span className="unknown">источник не указан</span>;
  return (
    <span>
      {value.document_id} · {value.locator}
    </span>
  );
}

function GateRow({ check }: { check: GateCheck }) {
  const badge = {
    PASS: "gate-pass",
    FAIL: "gate-fail",
    UNKNOWN: "gate-unknown",
  }[check.status];
  return (
    <li className="gate-row">
      <div>
        <strong>{gateLabels[check.kind] ?? check.kind}</strong>
        <p>{check.reason}</p>
        {check.evidence.length ? (
          check.evidence.map((source) => (
            <small key={`${source.document_id}:${source.locator}`}>
              <Source value={source} />
            </small>
          ))
        ) : (
          <small className="unknown">подтверждение отсутствует</small>
        )}
      </div>
      <span className={`gate-badge ${badge}`}>{check.status}</span>
    </li>
  );
}

function CaseDetails({ card }: { card: CaseCardData }) {
  const { case: item } = card;
  const checks = item.assessment?.checks ?? [];
  const scenarios = item.scenarios?.scenarios ?? [];
  return (
    <details className="case-details">
      <summary>Проверки, экономика и источники</summary>
      <div className="details-grid">
        <section>
          <h4>Обязательные проверки</h4>
          {checks.length ? (
            <ul className="gate-list">
              {checks.map((check) => (
                <GateRow check={check} key={check.kind} />
              ))}
            </ul>
          ) : (
            <p className="unknown">Проверки ещё не добавлены.</p>
          )}
        </section>
        <section>
          <h4>Три сценария</h4>
          {scenarios.length ? (
            <div className="scenario-list">
              {scenarios.map((scenario) => (
                <div className="scenario" key={scenario.kind}>
                  <strong>{scenarioLabels[scenario.kind] ?? scenario.kind}</strong>
                  <span>Выручка: {money(scenario.economics.contract_revenue)}</span>
                  <span>
                    НДС: {percent(scenario.economics.nds_rate)}
                  </span>
                  <small>{scenario.assumptions.join(" · ")}</small>
                  <ul className="cost-lines">
                    {Object.entries(scenario.economics.costs)
                      .filter(
                        ([key, value]) =>
                          key !== "specified_cost_fields" &&
                          typeof value === "string" &&
                          !/^0+(\.0+)?$/.test(value),
                      )
                      .map(([key, value]) => (
                        <li key={key}>
                          <span>{costLabels[key] ?? key}</span>
                          <strong>{money(value as string)}</strong>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <p className="unknown">Сценарии экономики не завершены.</p>
          )}
        </section>
        <section>
          <h4>Факторы рейтинга</h4>
          {item.rating?.factors?.length ? (
            <div className="scenario-list">
              {item.rating.factors.map((factor) => (
                <div className="rating-factor" key={factor.name}>
                  <strong>{factor.name}</strong>
                  <span>{factor.points > 0 ? "+" : ""}{factor.points}</span>
                  <p>{factor.explanation}</p>
                  {factor.change_hint && <small>Что изменить: {factor.change_hint}</small>}
                </div>
              ))}
            </div>
          ) : (
            <p className="unknown">Расшифровка рейтинга не указана.</p>
          )}
        </section>
        <section className="sources">
          <h4>Provenance</h4>
          <p>
            <strong>Извещение:</strong> <Source value={item.tender.notice_provenance} />
          </p>
          <p>
            <strong>НМЦК:</strong> <Source value={item.nmck_source} />
          </p>
          <p>
            <strong>КП:</strong> <Source value={item.selected_quote?.source} />
          </p>
        </section>
      </div>
    </details>
  );
}

function CaseCard({ card, now }: { card: CaseCardData; now: number }) {
  const [state, action, pending] = useActionState(evaluateCase, emptyState);
  const [sourcingState, sourcingAction, sourcingPending] = useActionState(
    runSourcing,
    emptyState,
  );
  const status = visualStatus(card, now);
  const { case: item, evaluation } = card;
  const checks = item.assessment?.checks ?? [];
  const submission = item.tender.submission;
  const geography =
    item.tender.delivery?.addresses
      ?.map((address) => [address.region, address.city].filter(Boolean).join(", "))
      .filter(Boolean)
      .join(" · ") || "не указана";
  const facts = [
    ["НМЦК без НДС", money(item.nmck_ex_vat)],
    ["География", geography],
    [
      "Закон / способ",
      `${lawLabels[item.tender.law] ?? item.tender.law} · ${methodLabels[item.tender.method] ?? item.tender.method}`,
    ],
    ["Срок подачи", stamp(submission?.closes_at, submission?.timezone)],
    ["До срока", timeLeft(submission?.closes_at, now)],
    ["Рейтинг", item.rating?.score !== undefined ? `${item.rating.score}/100` : "не указан"],
    ["Прибыль", money(evaluation?.recommendation.realistic_profit)],
    ["Маржа", percent(evaluation?.recommendation.realistic_margin)],
  ];

  return (
    <article className={`case-card case-${status.color}`}>
      <div className="card-topline">
        <p>Процедура {item.tender.tender_id || "не указана"}</p>
        <span className={`status-pill ${colors[status.color]}`}>{status.label}</span>
      </div>
      <h3>{item.tender.subject || "Предмет не указан"}</h3>
      <p className="customer">{item.tender.customer_name || "Заказчик не указан"}</p>

      <dl className="facts">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      <section className="reasons">
        <h4>Основания решения</h4>
        {evaluation ? (
          <>
            <p className="evaluated-at">
              Оценено на {stamp(evaluation.effective_at)} · движок {evaluation.engine_version}
            </p>
            <ul>
              {evaluation.recommendation.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {evaluation.recommendation.minimum_bid_price && (
              <p className="price-floor">
                Минимальная допустимая цена: {money(evaluation.recommendation.minimum_bid_price)}
              </p>
            )}
          </>
        ) : (
          <p className="unknown">Оценка для этой версии ещё не сохранена.</p>
        )}
        {status.stale && (
          <p className="stale-warning">
            Сохранённая рекомендация больше не подтверждает действующий срок или КП.
          </p>
        )}
      </section>

      <CaseDetails card={card} />

      <div className="next-step">
        <strong>Следующий шаг</strong>
        <p>{nextStep(status)}</p>
        {checks.length === 1 && checks[0].kind === "technical" && checks[0].status === "PASS" && (
          <Link href={`/hard-gate-assessment?case_id=${encodeURIComponent(item.case_id)}&version=${item.version}`}>
            Заполнить остальные hard gates →
          </Link>
        )}
        {status.color === "green" && !status.stale && evaluation && (
          <Link href={`/participation-approval?evaluation_id=${encodeURIComponent(evaluation.evaluation_id)}`}>
            Передать на независимое согласование →
          </Link>
        )}
      </div>
      <section className="sourcing-panel" aria-label="Поиск серверных карточек">
        <h4>Поиск серверов</h4>
        <p className="sourcing-scope">
          Публичные карточки — это кандидаты для проверки, а не подтверждённые КП.
        </p>
        {card.sourcing ? (
          <div className="sourcing-result">
            <p>
              <strong>{card.sourcing.source_name}</strong> · запрос «{card.sourcing.query}» · {stamp(card.sourcing.observed_at)}
            </p>
            {!!card.sourcing.sources.length && (
              <ul className="sourcing-leads" aria-label="Источники поиска">
                {card.sourcing.sources.map((source) => (
                  <li key={`${source.ordinal}-${source.source_url}`}>
                    <a href={source.source_url} rel="noreferrer" target="_blank">
                      {source.source_name}
                    </a>
                    <small>
                      {source.source_kind === "MANUFACTURER_CATALOG"
                        ? "официальный каталог"
                        : "каталог поставщика"}
                      {source.source_sha256 ? ` · ${source.source_sha256}` : ""}
                    </small>
                    <span>{source.status === "COMPLETED" ? "снимок сохранён" : "ошибка источника"}</span>
                  </li>
                ))}
              </ul>
            )}
            {card.sourcing.status === "SOURCE_ERROR" ? (
              <p className="stale-warning">Источник недоступен или изменил формат. Пустая выдача не зафиксирована.</p>
            ) : card.sourcing.shortlist.review_queue.length + card.sourcing.shortlist.rejected.length === 0 ? (
              <p className="unknown">Снимок получен, совпадений по названию нет.</p>
            ) : (
              <ul className="sourcing-leads">
                {[...card.sourcing.shortlist.review_queue, ...card.sourcing.shortlist.rejected].map((entry) => (
                  <li key={entry.lead.lead_id}>
                    <a href={entry.lead.product_url ?? entry.lead.source_url} rel="noreferrer" target="_blank">
                      {entry.lead.product_name}
                    </a>
                    <small>
                      {entry.lead.source_kind === "MANUFACTURER_CATALOG"
                        ? `официальный каталог${entry.lead.manufacturer ? ` · ${entry.lead.manufacturer}` : ""}`
                        : `каталог поставщика · ${entry.lead.supplier}`}
                    </small>
                    <span>{entry.status === "REJECTED" ? "отклонено" : "нужна техническая проверка"}</span>
                    {card.sourcing?.requirement_set_binding_id && card.sourcing.requirement_set_binding_sha256 && (
                      <Link
                        href={{
                          pathname: "/server-offer-proposal",
                          query: {
                            case_id: item.case_id,
                            version: String(item.version),
                            binding_id: card.sourcing.requirement_set_binding_id,
                            binding_sha256: card.sourcing.requirement_set_binding_sha256,
                            run_id: card.sourcing.run_id,
                            lead_id: entry.lead.lead_id,
                          },
                        }}
                      >
                        Добавить exact BOM/КП →
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="unknown">{card.sourcing.technical_scope_reason}</p>
            {card.sourcing.requirement_set_id && (
              <small>
                Reviewed set: {card.sourcing.requirement_set_id} · binding {card.sourcing.requirement_set_binding_sha256}
              </small>
            )}
            {card.sourcing.source_sha256 && (
              <small>Snapshot SHA-256: {card.sourcing.source_sha256}</small>
            )}
          </div>
        ) : (
          <p className="unknown">Поиск для этой версии кейса ещё не запускался.</p>
        )}
        <form action={sourcingAction} className="sourcing-form">
          <input name="case-id" type="hidden" value={item.case_id} />
          <input name="version" type="hidden" value={item.version} />
          <label htmlFor={`sourcing-query-${item.case_id}-${item.version}`}>Модель, 1–5 слов</label>
          <input
            id={`sourcing-query-${item.case_id}-${item.version}`}
            maxLength={80}
            name="query"
            placeholder="DL360 Gen12"
            required
          />
          <button disabled={sourcingPending} type="submit">
            {sourcingPending ? "Ищем…" : "Найти и сохранить"}
          </button>
          {sourcingState.error && <p role="alert">{sourcingState.error}</p>}
          {sourcingState.success && <p role="status">{sourcingState.success}</p>}
        </form>
      </section>
      <form action={action} className="evaluate-form">
        <input name="case-id" type="hidden" value={item.case_id} />
        <input name="version" type="hidden" value={item.version} />
        <button disabled={pending} type="submit">
          {pending ? "Оцениваем…" : "Пересчитать сейчас"}
        </button>
        <span>API использует текущее серверное время с часовым поясом.</span>
        {state.error && <p role="alert">{state.error}</p>}
        {state.success && <p role="status">{state.success}</p>}
      </form>
    </article>
  );
}

export function PilotDashboard({
  dashboard,
  demoMode,
  nowIso,
}: {
  dashboard: DashboardData;
  demoMode: boolean;
  nowIso: string;
}) {
  const [now, setNow] = useState(() => new Date(nowIso).getTime());
  const [state, action, pending] = useActionState(importCase, emptyState);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const statuses = dashboard.cases.map((card) => visualStatus(card, now));
  const count = (label: string) => statuses.filter((status) => status.label === label).length;
  const summary = [
    ["Сохранено", dashboard.cases.length],
    ["Участвовать", count("участвовать")],
    ["Нужен анализ", count("нужен анализ") + count("требуется пересчёт")],
    ["Не участвовать", count("не участвовать")],
    ["Нет оценки", count("нет оценки")],
  ];

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Внутренний пилот · S3</p>
          <h1>Закупки и решения</h1>
        </div>
        <div>
          <p>
            Первый рабочий экран тендерного отдела. Рекомендации загружаются из
            детерминированного API и не рассчитываются в браузере.
          </p>
          <Link className="mt-2 inline-block font-bold text-blue-700 hover:underline" href="/document-search">
            Поиск по документам →
          </Link>
          <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/document-upload">
            Загрузить ТЗ или КП →
          </Link>
          <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/completeness-review">
            Проверка полноты →
          </Link>
          <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/requirement-set-binding">
            Привязать требования →
          </Link>
          <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/supplier-discovery">
            Источники поставщиков →
          </Link>
          <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/tender-discovery">
            Поиск закупок ЕИС →
          </Link>
        </div>
      </header>

      {demoMode && (
        <aside aria-label="Демонстрационный режим" className="demo-banner">
          <strong>ДЕМО-РЕЖИМ</strong>
          <span>Используйте только синтетические или учебные данные.</span>
        </aside>
      )}
      {dashboard.error && (
        <p className="load-error" role="alert">
          {dashboard.error === "api"
            ? "Не удалось загрузить данные API. Проверьте, что FastAPI запущен."
            : "Не настроено серверное подключение к API."}
        </p>
      )}

      <section aria-label="Сводка по загруженной выборке" className="summary-grid">
        {summary.map(([label, value]) => (
          <div className="summary-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </section>
      <p className="scope-note">Сводка относится только к загруженным сохранённым кейсам.</p>

      <section className="cases-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Снимки кейсов</p>
            <h2>Сохранённые процедуры</h2>
          </div>
          <span>{dashboard.cases.length} в выборке</span>
        </div>
        {dashboard.cases.length ? (
          <div className="case-grid">
            {dashboard.cases.map((card) => (
              <CaseCard
                card={card}
                key={`${card.case.case_id}:${card.case.version}`}
                now={now}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <strong>Сохранённых кейсов пока нет</strong>
            <p>Добавьте полный JSON-снимок в форме ниже.</p>
          </div>
        )}
      </section>

      <section className="import-section">
        <div>
          <p className="eyebrow">Ручной импорт</p>
          <h2>Добавить JSON-снимок</h2>
          <p>
            Импорт создаёт неизменяемую версию кейса. Рекомендация появится только
            после отдельного серверного пересчёта.
          </p>
        </div>
        <form action={action}>
          <label htmlFor="case-json">Полный JSON ProcurementCase</label>
          <textarea
            id="case-json"
            name="case-json"
            placeholder={'{"case_id": "…", "version": 1, …}'}
            required
            rows={12}
          />
          <button disabled={pending} type="submit">
            {pending ? "Сохраняем…" : "Сохранить кейс"}
          </button>
          {state.error && <p role="alert">{state.error}</p>}
          {state.success && <p role="status">{state.success}</p>}
        </form>
      </section>
    </div>
  );
}
