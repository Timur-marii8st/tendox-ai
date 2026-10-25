import { awareDeadline } from "./tender-workspace";
import type { MixedNoticeRef } from "./procurement-api";

export const expenseFields = {
  packaging: "Упаковка", logistics: "Вся доставка до заказчика", loading_unloading: "Погрузка и разгрузка",
  storage: "Хранение", installation: "Монтаж", payroll_travel: "Работа и командировки", subcontracting: "Субподряд",
  insurance: "Страхование", finance: "Финансирование", bank_guarantee: "Банк и гарантии", platform_fees: "Комиссия площадки",
  taxes: "Налоги, кроме выходного НДС", certification: "Сертификация", warranty: "Гарантия",
  risk_reserve: "Резерв риска", penalty_reserve: "Резерв штрафов", other: "Прочие расходы",
} as const;
export type BetaQuoteRef = { notice: MixedNoticeRef; lot_index: number | null };
export type BetaQuoteInput = {
  supplier: string; document: string; locator: string; amount_ex_vat: string; quote_vat_rate: string;
  issued_at: string; valid_until: string; covers_full_scope: boolean;
  availability_terms: string; delivery_terms: string; payment_terms: string;
  expenses: Record<string, string>; expense_basis: string; tax_model: string; output_vat_rate: string;
  realistic_discount: string; conservative_discount: string; conservative_cost_growth: string;
};
export type BetaScenario = { kind: "base" | "realistic" | "conservative"; revenue_net: string; costs_net: string;
  profit: string; margin: string; assumptions: string[]; break_even_gross: string };
export type BetaQuoteReport = {
  ref: BetaQuoteRef; record_id: string | null; input: BetaQuoteInput | null;
  calculation: { status: "CALCULATED" | "UNKNOWN" | "BLOCKED"; checked_at: string; scenarios: BetaScenario[];
    reasons: string[]; participation: "UNKNOWN" } | null;
  source_reasons: string[]; source_status: "CHECKED" | "NO_QUOTE";
};
export type BetaShortlist = {
  checked_at: string; profile: { version: number; snapshot_sha256: string; facts: Record<string, { knowledge: string; value: unknown }> } | null;
  rows: { report: BetaQuoteReport; profile_status: "FAIL" | "UNKNOWN"; reasons: string[]; financial_position: number | null }[];
  financial_order: string[]; eligibility: "UNKNOWN";
};
export const betaRefKey = (ref: BetaQuoteRef) => `${ref.notice.law}:${ref.notice.purchase_number}:${ref.notice.version_number}:${ref.notice.notice_xml_sha256}:${ref.lot_index ?? 0}`;
export function betaReportMatches(report: BetaQuoteReport, ref: BetaQuoteRef): boolean {
  return betaRefKey(report.ref) === betaRefKey(ref) && (!report.calculation || report.calculation.participation === "UNKNOWN");
}


const reasonLabels: Record<string, string> = {
  PROCEDURE_BLOCKED_OR_EXPIRED: "Закупка заблокирована или срок подачи истёк.",
  DEADLINE_UNKNOWN: "Срок подачи не подтверждён.", QUOTE_INCOMPLETE_OR_NOT_VALID: "КП неполное, ещё не действует или истекло.",
  EXPENSES_INCOMPLETE: "Заполнены не все статьи расходов. Пустое поле не равно нулю.", SOURCE_REVENUE_UNKNOWN: "Начальная цена в рублях не подтверждена.",
  SELECTED_PROFILE_MISSING: "Выберите сохранённую версию профиля компании.",
  PROFILE_DELIVERY_REGION_FAIL: "Место поставки выходит за заявленные регионы профиля.",
  PROFILE_DELIVERY_REGION_UNKNOWN: "Соответствие всей географии профилю требует проверки.",
  SELECTED_DELIVERY_REGION_NOT_CONFIRMED: "Выбранный регион поставки не подтверждён.",
  CONSERVATIVE_NOT_PROFITABLE: "Консервативный сценарий не даёт положительной прибыли.",
  TECHNICAL_LEGAL_AND_FULL_PROFILE_REVIEW_REQUIRED: "Технические, юридические и остальные ограничения профиля ещё требуют проверки.",
};
export function betaReason(code: string): string {
  if (reasonLabels[code]) return reasonLabels[code];
  const labels: Record<string,string> = { MIN_CONTRACT_AMOUNT: "минимальная сумма контракта", MAX_CONTRACT_AMOUNT: "максимальная сумма контракта", MIN_MARGIN: "минимальная маржа", MIN_EXPECTED_PROFIT: "минимальная прибыль" };
  const match = /^PROFILE_(.+)_(UNKNOWN|FAIL)$/.exec(code);
  if (match && labels[match[1]]) return `${labels[match[1]]}: ${match[2] === "FAIL" ? "ограничение профиля нарушено" : "в профиле не подтверждено"}.`;
  return code;
}


export function betaCalculationLabel(status: "CALCULATED" | "UNKNOWN" | "BLOCKED"): string {
  return { CALCULATED: "Рассчитано по введённому КП", UNKNOWN: "Не хватает подтверждённых данных", BLOCKED: "Расчёт заблокирован" }[status];
}


/** A previous calculation cannot keep expired or blocked input active in the UI. */
export function financialQuoteCurrent(report: BetaQuoteReport, deadline: string | null, blocked: boolean, now = Date.now()): boolean {
  if (blocked || !Number.isFinite(now) || report.calculation?.status !== "CALCULATED" ||
      report.calculation.participation !== "UNKNOWN" || report.input?.covers_full_scope !== true) return false;
  const issued = awareDeadline(report.input.issued_at);
  const until = awareDeadline(report.input.valid_until);
  const end = awareDeadline(deadline);
  return !!issued && !!until && !!end && Date.parse(issued) <= now && now < Date.parse(until) && now < Date.parse(end);
}
