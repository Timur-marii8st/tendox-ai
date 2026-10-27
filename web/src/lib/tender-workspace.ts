import type { Eis223SearchResult, EisIndexedLead, EisIndexedSearchResult, PositionEvidenceSet } from "./procurement-api";

export type TenderLaw = "44" | "223";
export type TenderLawFilter = "all" | TenderLaw;
export type TenderSort = "search" | "price_desc";
export type NavigationFact = { value: string; supporting_sources?: { document_id: string; locator: string }[]; provenance: { document_id: string; locator: string } };
export type TenderNavigation = { law: TenderLaw; purchase_number: string; version_number: number; xml_sha256: string;
  delivery_regions: NavigationFact[]; delivery_addresses?: NavigationFact[]; delivery_coverage: "UNKNOWN";
  eis_url: NavigationFact | null; platform_url: NavigationFact | null; platform_name: NavigationFact | null };
export type WorkspaceResult = {
  globalPrice?: { next_cursor: string | null; page_snapshot_sha256: string; snapshot_at: string; matched_count: number; unknown_region_count: number; delivery_region: string; include_unknown_region: boolean };
  navigation?: Record<string, TenderNavigation>;
  query: string; law: TenderLawFilter;
  result44?: EisIndexedSearchResult; result223?: Eis223SearchResult;
  error44?: string; error223?: string; error?: string;
};
export type TenderRow = {
  id: string; law: TenderLaw; title: string; purchaseNumber: string;
  version: number; xmlSha256: string; priceLabel: string; priceValue: string;
  sortAmountRub?: string | null;
  deadline: string | null; deadlineRaw: string | null; blocked: boolean;
  statusLabel: string; reasons: string[];
  evidence: { label: string; value: string }[];
  positions: { name: string; quantity: string; unit: string; locator: string }[];
  positionSet?: PositionEvidenceSet | null;
  documents: { filename: string; url: string | null; locator: string; available: boolean }[];
  deliveryRegions?: NavigationFact[]; platformUrl?: string | null; platformName?: string | null;
  navigation?: TenderNavigation;
  noticeUrl: string | null; raw44?: EisIndexedLead;
  raw223?: Eis223SearchResult["matched"][number];
};

const unknown = "Не подтверждено";

/** Сохраняет все разряды исходного Decimal без числового преобразования. */
export function formatMoneyString(value: string | null, currency = "RUB"): string {
  if (value === null || !/^[+-]?\d+(?:\.\d+)?$/.test(value)) return unknown;
  const [whole, fraction] = value.split(".");
  const amount = whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (fraction === undefined ? "" : `,${fraction}`);
  const suffix = currency === "RUB" || currency === "RUR" ? "₽" : currency === "UNKNOWN" || !currency ? "валюта не подтверждена" : currency;
  return `${amount} ${suffix}`;
}

/** Наивное, некорректное или нормализованное JS время не становится deadline. */
export function awareDeadline(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = match;
  const y = Number(year), m = Number(month), d = Number(day);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59 ||
      Number(offsetHour ?? 0) > 23 || Number(offsetMinute ?? 0) > 59 || !Number.isFinite(Date.parse(value))) return null;
  return value;
}

export function formatTenderDeadline(value: string | null): string {
  const valid = awareDeadline(value);
  return valid ? `${new Date(valid).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} МСК` : "Срок не подтверждён";
}

function status(failed: boolean, hold: boolean, expired: boolean) {
  return expired ? "Срок истёк · FAIL" : failed ? "Подача заблокирована · FAIL"
    : hold ? "Действия приостановлены · UNKNOWN" : "Подача не подтверждена · UNKNOWN";
}

function officialNoticeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password &&
      (url.hostname === "zakupki.gov.ru" || url.hostname.endsWith(".zakupki.gov.ru"))
      ? url.toString() : null;
  } catch { return null; }
}

function row44(lead: EisIndexedLead, now: number): TenderRow {
  const deadline = awareDeadline(lead.deadline);
  const expired = deadline !== null && Date.parse(deadline) <= now;
  const failed = lead.application_status === "FAIL";
  return {
    id: `44:${lead.purchase_number}:${lead.version_number}:${lead.xml_sha256}`,
    law: "44", title: lead.title, purchaseNumber: lead.purchase_number,
    version: lead.version_number, xmlSha256: lead.xml_sha256,
    priceLabel: "НМЦК", priceValue: formatMoneyString(lead.nmck_rub), sortAmountRub: lead.nmck_rub,
    deadline, deadlineRaw: lead.deadline, blocked: failed || expired,
    statusLabel: status(failed, false, expired),
    reasons: [...lead.reasons, ...(expired ? ["Сохранённый срок подачи истёк."] : [])],
    evidence: [
      { label: "Совпадение запроса", value: lead.match_locator },
      { label: "Окно загрузки источника", value: lead.source_window },
      { label: "Исходный файл", value: lead.source_member },
      { label: "XML SHA-256", value: lead.xml_sha256 },
    ],
    positions: lead.lot_items.map(item => ({ name: item.name, quantity: item.quantity ?? unknown,
      unit: item.unit ?? unknown, locator: item.locator })),
    documents: lead.attachments.map(item => {
      const url = officialNoticeUrl(item.url);
      return { filename: item.filename, url, locator: item.locator, available: url !== null };
    }),
    noticeUrl: officialNoticeUrl(lead.notice_url), raw44: lead,
    positionSet: lead.position_set?.law === "44" && lead.position_set.purchase_number === lead.purchase_number &&
      lead.position_set.version_number === lead.version_number && lead.position_set.notice_xml_sha256 === lead.xml_sha256
      ? lead.position_set : null,
  };
}

function lotPrice(lot: Eis223SearchResult["matched"][number]["notice"]["lots"][number], generic: boolean) {
  const kind = lot.source_price_kind ?? (generic ? "UNKNOWN" : "INITIAL_SUM");
  const labels = { INITIAL_SUM: "Начальная сумма лота", MAX_CONTRACT_PRICE: "Максимальная цена договора по лоту",
    TEXT_ONLY: "Цена лота описана текстом", UNKNOWN: "Тип цены лота не подтверждён" };
  const amount = kind === "TEXT_ONLY" || kind === "UNKNOWN" ? null
    : lot.source_price_kind ? lot.source_amount?.value ?? null : lot.initial_sum.value;
  const currency = lot.source_currency_status === "UNKNOWN" ? "UNKNOWN"
    : lot.currency_letter_code?.value ?? lot.currency.value ?? "UNKNOWN";
  return { label: labels[kind], value: kind === "TEXT_ONLY" ? lot.source_price_text?.raw ?? unknown : formatMoneyString(amount, currency),
    sortAmountRub: (currency === "RUB" || currency === "RUR") &&
      [null, undefined, "643"].includes(lot.currency_numeric?.value) &&
      (!lot.source_price_kind || lot.source_currency_status === "CONSISTENT") &&
      lot.source_price_formula_present !== true && lot.source_commodity_price_present !== true ? amount : null };
}

function row223(lead: Eis223SearchResult["matched"][number], now: number): TenderRow {
  const notice = lead.notice;
  const generic = notice.document_type === "purchaseNotice";
  const selected = notice.selected_deadline ?? (generic ? null : notice.deadline);
  const deadline = selected?.status === "AWARE" ? awareDeadline(selected.value) : null;
  const expired = deadline !== null && Date.parse(deadline) <= now;
  const failed = lead.application_status === "FAIL" || lead.cancellation_state?.application_status === "FAIL";
  const hold = Boolean(lead.cancellation_state?.operation_hold || lead.lot_cancellation_state?.operation_hold || lead.source_schema_status === "FAIL");
  const prices = notice.lots.map(lot => lotPrice(lot, generic));
  const price = prices.length === 1 ? prices[0] : { label: `Цены по лотам (${prices.length})`, value: prices.length ? "См. условия каждого лота" : unknown };
  return {
    id: `223:${notice.purchase_number}:${notice.version_number}:${notice.xml_sha256}`,
    law: "223", title: notice.title.value ?? "Название не подтверждено", purchaseNumber: notice.purchase_number,
    version: notice.version_number, xmlSha256: notice.xml_sha256, priceLabel: price.label, priceValue: price.value,
    sortAmountRub: prices.length === 1 ? prices[0].sortAmountRub : null,
    deadline, deadlineRaw: selected?.raw ?? notice.deadline.raw,
    blocked: failed || hold || expired, statusLabel: status(failed, hold, expired),
    reasons: [...new Set([...lead.reasons, ...(lead.cancellation_state?.reason_codes ?? []),
      ...(lead.lot_cancellation_state?.reason_codes ?? []), ...(expired ? ["Сохранённый срок подачи истёк."] : []),
      ...(lead.source_schema_status === "FAIL" ? ["Исходный XML не прошёл проверку схемы."] : [])])],
    evidence: [
      ...lead.term_evidence.map(item => ({ label: `Совпадение: ${item.term}`, value: `${item.source_value} · ${item.locator}` })),
      { label: "Окно загрузки источника", value: lead.source_window },
      { label: "Исходный файл", value: notice.source_member },
      { label: "XML SHA-256", value: notice.xml_sha256 },
      { label: "Архив SHA-256", value: lead.archive_sha256 },
      { label: "Ответ источника SHA-256", value: lead.source_response_sha256 },
      ...prices.map((item, index) => ({ label: `Лот ${notice.lots[index].ordinal.value ?? index + 1}: ${item.label}`, value: item.value })),
    ],
    positions: notice.lots.flatMap(lot => lot.items.map(item => ({ name: item.description.value ?? unknown,
      quantity: item.quantity.value ?? unknown, unit: item.unit_name.value ?? unknown, locator: item.provenance.locator }))),
    documents: notice.attachments.map(item => {
      // Only the validated value is public; raw can contain a rejected or hidden URL.
      const restricted = [notice.hide_purchase_raw, notice.hide_purchase_customer_accredited_raw,
        item.not_placement_raw].some(flag => flag?.value === "true" || flag?.value === "1");
      const url = restricted || !item.url.value ? null : officialNoticeUrl(item.url.value);
      return { filename: item.filename.value ?? "Имя файла не подтверждено", url,
        locator: item.url.provenance.locator, available: url !== null };
    }),
    noticeUrl: null, raw223: lead,
  };
}

/** Объединяет только полученные страницы; порядок каждого закона сохраняется. */
export function rowsFromResult(result: WorkspaceResult): TenderRow[] {
  const now = Date.now();
  const rows = [
    ...(result.law !== "223" ? result.result44?.matched.map(lead => row44(lead, now)) ?? [] : []),
    ...(result.law !== "44" ? result.result223?.matched.map(lead => row223(lead, now)) ?? [] : []),
  ];
  const seen = new Set<string>();
  return rows.filter(row => { if (seen.has(row.id)) return false; seen.add(row.id); return true; }).map(row => {
    const navigation = result.navigation?.[row.id];
    if (!navigation || navigation.law !== row.law || navigation.purchase_number !== row.purchaseNumber ||
        navigation.version_number !== row.version || navigation.xml_sha256 !== row.xmlSha256) return row;
    const factMatches = (fact: NavigationFact | null) => fact === null ||
      (fact.provenance.document_id === row.xmlSha256 && !!fact.provenance.locator);
    if (![...navigation.delivery_regions, ...(navigation.delivery_addresses ?? []), navigation.eis_url, navigation.platform_url, navigation.platform_name].every(factMatches)) return row;
    return { ...row, navigation, deliveryRegions: navigation.delivery_regions,
      noticeUrl: navigation.eis_url?.value ? officialNoticeUrl(navigation.eis_url.value) : row.noticeUrl,
      platformUrl: safePlatformUrl(navigation.platform_url?.value ?? null),
      platformName: navigation.platform_name?.value ?? null };
  });
}


/** Navigation URLs are rendered, never fetched by this module. */
function safePlatformUrl(value: string | null): string | null {
  if (!value || /[\s\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password &&
      (!url.port || url.port === (url.protocol === "https:" ? "443" : "80")) && url.hostname.includes(".") ? url.toString() : null;
  } catch { return null; }
}

export function filterDeliveryRegion(rows: TenderRow[], region: string, includeUnknown: boolean): TenderRow[] {
  const normalize = (value: string) => {
    const aliases: Record<string,string> = { "г": "город", "обл": "область", "респ": "республика" };
    return (value.toLocaleLowerCase("ru-RU").match(/[а-яёa-z0-9]+/g) ?? []).map(token => aliases[token] ?? token).filter(token => token !== "город").sort().join(" ");
  };
  const selected = normalize(region);
  if (!selected) return rows;
  return rows.filter(row => row.deliveryRegions?.length
    ? row.deliveryRegions.some(fact => normalize(fact.value) === selected)
    : includeUnknown);
}


/** Compares source Decimal strings without floating point, rounding, FX or inferred lot totals. */
export function sortTenderRows(rows: TenderRow[], order: TenderSort): TenderRow[] {
  if (order === "search") return rows;
  const parts = (value: string | null | undefined) => {
    if (!value || !/^\+?\d+(?:\.\d+)?$/.test(value)) return null;
    const [whole, fraction = ""] = value.replace(/^\+/, "").split(".");
    return [whole.replace(/^0+(?=\d)/, ""), fraction.replace(/0+$/, "")] as const;
  };
  return [...rows].sort((a, b) => {
    if (a.blocked !== b.blocked) return a.blocked ? 1 : -1;
    const left = parts(a.sortAmountRub), right = parts(b.sortAmountRub);
    if (!left || !right) return left ? -1 : right ? 1 : 0;
    if (left[0].length !== right[0].length) return right[0].length - left[0].length;
    if (left[0] !== right[0]) return left[0] > right[0] ? -1 : 1;
    const size = Math.max(left[1].length, right[1].length);
    const leftFraction = left[1].padEnd(size, "0"), rightFraction = right[1].padEnd(size, "0");
    return leftFraction === rightFraction ? 0 : leftFraction > rightFraction ? -1 : 1;
  });
}
