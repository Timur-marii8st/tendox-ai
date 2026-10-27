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
export type DiscountMode = "MANUAL" | "REGIONAL";
export type HistorySource = { document_id: string; locator: string };
export type HistoryFact<T> = { value: T | null; source: HistorySource; supporting_sources: HistorySource[] };
export type RegionalObservation = {
  purchase_number: string; law: "44" | "223";
  initial: HistoryFact<string>; final: HistoryFact<string>; quantity: HistoryFact<string>;
  region: HistoryFact<string>; product_key: HistoryFact<string>; procedure: HistoryFact<string>;
  unit: HistoryFact<string>; concluded_at: HistoryFact<string>;
  concluded_date: HistoryFact<string> | null; qualification_reasons: string[];
  price_basis: "RUB_NOMINAL_DECLARED_SIGNED_TOTALS";
  price_scope?: "WHOLE_NOTICE" | "WHOLE_CUSTOMER_CONTRACT";
  customer?: HistoryFact<string> | null;
  notice_lot_volume_link: HistoryFact<boolean>; rub_nominal_totals: HistoryFact<boolean>;
  concluded_contract: HistoryFact<boolean>; current_result: HistoryFact<boolean>;
};
export type RegionalDiscountReport = {
  policy: "regional-discount-v2"; checked_at: string;
  cohort: { target_id: string; law: "44" | "223"; region: string | null; product_key: string | null;
    procedure: string | null; unit: string | null; quantity: string | null;
    period_start: string; period_end: string; source: HistorySource };
  status: "PASS" | "UNKNOWN"; sample_size: number; required_sample: 5;
  realistic_discount: string | null; conservative_discount: string | null;
  reasons: string[]; coverage: "UNKNOWN";
  evaluated: { observation: RegionalObservation; status: "PASS" | "UNKNOWN"; reasons: string[]; discount: string | null }[];
};
export type BetaHistoryReport = { ref: BetaQuoteRef; history: RegionalDiscountReport; source_reasons: string[] };
export type BetaQuoteInput = {
  supplier: string; document: string; locator: string; amount_ex_vat: string; quote_vat_rate: string;
  issued_at: string; valid_until: string; covers_full_scope: boolean;
  availability_terms: string; delivery_terms: string; payment_terms: string;
  expenses: Record<string, string>; expense_basis: string; tax_model: string; output_vat_rate: string;
  realistic_discount: string; conservative_discount: string; conservative_cost_growth: string;
  discount_mode?: DiscountMode;
};
export type BetaScenario = { kind: "base" | "realistic" | "conservative"; revenue_net: string; costs_net: string;
  profit: string; margin: string; assumptions: string[]; break_even_gross: string };
export type BetaQuoteReport = {
  ref: BetaQuoteRef; record_id: string | null; input: BetaQuoteInput | null;
  calculation: { status: "CALCULATED" | "UNKNOWN" | "BLOCKED"; checked_at: string; scenarios: BetaScenario[];
    reasons: string[]; participation: "UNKNOWN"; regional_discount?: RegionalDiscountReport | null;
    discount_basis?: "MANUAL" | "REGIONAL_HISTORY" } | null;
  unit_quantity?: { value: string | null; provenance: { document_id: string; locator: string } } | null;
  quantity_unit?: { value: string | null; provenance: { document_id: string; locator: string } } | null;
  source_reasons: string[]; source_status: "CHECKED" | "NO_QUOTE";
};
export type BetaShortlist = {
  checked_at: string; profile: { version: number; snapshot_sha256: string; facts: Record<string, { knowledge: string; value: unknown }> } | null;
  rows: { report: BetaQuoteReport; profile_status: "FAIL" | "UNKNOWN"; reasons: string[]; financial_position: number | null; unit_profit?: string | null }[];
  ranking?: "TOTAL_PROFIT" | "UNIT_PROFIT";
  unit_orders?: { unit: string; record_ids: string[] }[];
  financial_order: string[]; eligibility: "UNKNOWN";
};
export const betaRefKey = (ref: BetaQuoteRef) => `${ref.notice.law}:${ref.notice.purchase_number}:${ref.notice.version_number}:${ref.notice.notice_xml_sha256}:${ref.lot_index ?? 0}`;
export function betaRefMatches(value: unknown, ref: BetaQuoteRef): boolean {
  if (!object(value) || !object(value.notice)) return false;
  return value.lot_index === ref.lot_index && value.notice.law === ref.notice.law &&
    value.notice.purchase_number === ref.notice.purchase_number && value.notice.version_number === ref.notice.version_number &&
    value.notice.notice_xml_sha256 === ref.notice.notice_xml_sha256;
}
export function betaReportMatches(report: BetaQuoteReport, ref: BetaQuoteRef): boolean {
  return !!report && betaRefMatches(report.ref, ref) && (!report.calculation || report.calculation.participation === "UNKNOWN");
}

/** Old saved payloads retain manual semantics; only a new form defaults to history. */
export function quoteDiscountMode(input: BetaQuoteInput | null | undefined): DiscountMode {
  return input ? input.discount_mode ?? "MANUAL" : "REGIONAL";
}

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const boundedText = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 8192;
const nullableText = (value: unknown) => value === null || boundedText(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(boundedText);
const source = (value: unknown): boolean => object(value) && boundedText(value.document_id) && boundedText(value.locator);
const fraction = (value: unknown): value is string => typeof value === "string" && /^0(?:\.\d{1,12})?$/.test(value);
export const historyDecimal = (value: unknown): value is string => typeof value === "string" && /^[+-]?\d{1,30}(?:\.\d{1,12})?$/.test(value);
export function historyFraction(value: unknown): string {
  return fraction(value) ? value : "UNKNOWN";
}
export function historyScopeLabel(observation: Pick<RegionalObservation, "price_scope">): string {
  return observation.price_scope === "WHOLE_CUSTOMER_CONTRACT"
    ? "Полный контракт заказчика в совместной закупке"
    : "Полный объём извещения";
}
export function historyDateOnly(value: unknown): value is string {
  // Use the calendar validator without assigning a timestamp to the source fact.
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !!awareDeadline(`${value}T00:00:00Z`);
}
function fact(value: unknown, valid: (value: unknown) => boolean): boolean {
  return object(value) && (value.value === null || valid(value.value)) && source(value.source) &&
    Array.isArray(value.supporting_sources) && value.supporting_sources.length <= 16 && value.supporting_sources.every(source);
}
/** Fail closed on malformed rates, false sample sufficiency or a different source/lot. */
export function betaHistoryMatches(value: unknown, ref: BetaQuoteRef): value is BetaHistoryReport {
  if (!object(value) || !betaRefMatches(value.ref, ref) || !strings(value.source_reasons) || !object(value.history)) return false;
  const h = value.history;
  if (!object(h.cohort) || h.cohort.target_id !== `${ref.notice.law}:${ref.notice.purchase_number}:${ref.lot_index ?? 0}` ||
      h.cohort.law !== ref.notice.law || !source(h.cohort.source) ||
      ![h.cohort.region, h.cohort.product_key, h.cohort.procedure, h.cohort.unit].every(nullableText) ||
      !(h.cohort.quantity === null || historyDecimal(h.cohort.quantity)) ||
      !boundedText(h.checked_at) || !awareDeadline(h.checked_at) ||
      !boundedText(h.cohort.period_start) || !awareDeadline(h.cohort.period_start) ||
      !boundedText(h.cohort.period_end) || !awareDeadline(h.cohort.period_end) ||
      Date.parse(h.cohort.period_start) >= Date.parse(h.cohort.period_end) ||
      Date.parse(h.cohort.period_end) > Date.parse(h.checked_at) ||
      h.policy !== "regional-discount-v2" || h.coverage !== "UNKNOWN" || h.required_sample !== 5 || !Number.isInteger(h.sample_size) ||
      typeof h.sample_size !== "number" || h.sample_size < 0 || h.sample_size > 20 || !strings(h.reasons) ||
      !Array.isArray(h.evaluated) || h.evaluated.length > 20) return false;
  for (const entry of h.evaluated) {
    if (!object(entry) || !object(entry.observation) || !strings(entry.reasons) ||
        !["PASS", "UNKNOWN"].includes(String(entry.status)) ||
        (entry.status === "PASS" ? !fraction(entry.discount) || entry.reasons.length !== 0 : entry.discount !== null)) return false;
    const o = entry.observation;
    if (o.price_scope !== undefined && o.price_scope !== "WHOLE_NOTICE" && o.price_scope !== "WHOLE_CUSTOMER_CONTRACT") return false;
    if (o.customer !== undefined && o.customer !== null && !fact(o.customer, v => typeof v === "string" && /^\d{11}$/.test(v))) return false;
    if (o.price_scope === "WHOLE_CUSTOMER_CONTRACT" && entry.status === "PASS" &&
        (!object(o.customer) || typeof o.customer.value !== "string" || !/^\d{11}$/.test(o.customer.value))) return false;
    if (o.price_basis !== "RUB_NOMINAL_DECLARED_SIGNED_TOTALS" || !strings(o.qualification_reasons) ||
        typeof o.purchase_number !== "string" || !/^\d{11,23}$/.test(o.purchase_number) || !["44", "223"].includes(String(o.law)) ||
        ![o.initial, o.final, o.quantity].every(f => fact(f, historyDecimal)) ||
        ![o.region, o.product_key, o.procedure, o.unit].every(f => fact(f, boundedText)) ||
        !fact(o.concluded_at, v => boundedText(v) && !!awareDeadline(v)) ||
        !(o.concluded_date === null || fact(o.concluded_date, historyDateOnly)) ||
        ![o.notice_lot_volume_link, o.rub_nominal_totals, o.concluded_contract, o.current_result].every(f => fact(f, v => typeof v === "boolean"))) return false;
  }
  return h.sample_size === h.evaluated.filter(e => e.status === "PASS").length &&
    (h.status === "PASS" ? h.sample_size >= 5 && h.reasons.length === 0 && fraction(h.realistic_discount) && fraction(h.conservative_discount)
      : h.status === "UNKNOWN" && h.realistic_discount === null && h.conservative_discount === null);
}


const reasonLabels: Record<string, string> = {
  PROCEDURE_BLOCKED_OR_EXPIRED: "Закупка заблокирована или срок подачи истёк.",
  DEADLINE_UNKNOWN: "Срок подачи не подтверждён.", QUOTE_INCOMPLETE_OR_NOT_VALID: "КП неполное, ещё не действует или истекло.",
  EXPENSES_INCOMPLETE: "Заполнены не все статьи расходов. Пустое поле не равно нулю.", SOURCE_REVENUE_UNKNOWN: "Начальная цена в рублях не подтверждена.",
  SELECTED_PROFILE_MISSING: "Выберите сохранённую версию профиля компании.",
  PROFILE_DELIVERY_REGION_FAIL: "Место поставки выходит за заявленные регионы профиля.",
  PROFILE_DELIVERY_REGION_UNKNOWN: "Соответствие всей географии профилю требует проверки.",
  SELECTED_DELIVERY_REGION_NOT_CONFIRMED: "Выбранный регион поставки не подтверждён.",
  UNIT_PROFIT_BASIS_UNKNOWN: "Прибыль на единицу неизвестна: нужен лот с одной исходной позицией, положительным количеством и указанной единицей. Расходы смешанного лота не распределяются автоматически.",
  CONSERVATIVE_NOT_PROFITABLE: "Консервативный сценарий не даёт положительной прибыли.",
  REGIONAL_HISTORY_UNKNOWN: "Региональное снижение не подтверждено. Расчёт в этом режиме остаётся UNKNOWN; ручной режим можно выбрать явно.",
  REGIONAL_HISTORY_REVENUE_SOURCE_MISMATCH: "История не связана с источником начальной цены выбранного лота.",
  INSUFFICIENT_VERIFIED_COMPARABLE_RESULTS: "Недостаточно проверенных сопоставимых контрактов: нужны минимум 5 независимых закупок.",
  TARGET_COHORT_INCOMPLETE: "Для выбранного лота не подтверждены все признаки сопоставимости.",
  DUPLICATE_PROCUREMENT: "Несколько результатов одной закупки: неоднозначные записи исключены.",
  TARGET_IS_NOT_HISTORY: "Выбранная закупка не может входить в собственную историю.",
  LAW_MISMATCH: "Наблюдение относится к другому закону.",
  REGION_MISSING_OR_MISMATCH: "Регион поставки неизвестен или отличается.",
  PRODUCT_KEY_MISSING_OR_MISMATCH: "Товарная группа неизвестна или отличается.",
  PROCEDURE_MISSING_OR_MISMATCH: "Способ закупки неизвестен или отличается.",
  UNIT_MISSING_OR_MISMATCH: "Единица измерения неизвестна или отличается.",
  NOTICE_LOT_VOLUME_LINK_NOT_CONFIRMED: "Связь контракта с извещением, лотом и объёмом не подтверждена.",
  RUB_NOMINAL_TOTALS_NOT_CONFIRMED: "Сопоставимость полных номинальных рублёвых сумм не подтверждена.",
  CONCLUDED_CONTRACT_NOT_CONFIRMED: "Подписание контракта не подтверждено.",
  CURRENT_RESULT_NOT_CONFIRMED: "Актуальность контрактного результата не подтверждена.",
  CONCLUSION_OUTSIDE_PERIOD_OR_UNKNOWN: "Дата заключения неизвестна или вне выбранного периода.",
  VOLUME_OUTSIDE_HALF_TO_DOUBLE_OR_UNKNOWN: "Объём неизвестен или выходит за диапазон от половины до двойного объёма выбранного лота.",
  PRICES_NOT_POSITIVE_COMPARABLE_TOTALS: "Не подтверждены положительные сопоставимые суммы; подписанная сумма не должна превышать начальную.",
  DISCOUNT_UNREPRESENTABLE: "Снижение нельзя безопасно использовать с принятой точностью расчёта.",
  SOURCE_CURRENT_HISTORY_UNCONFIRMED: "Полнота актуальной истории источника, включая отмены, не подтверждена. Региональное снижение остаётся UNKNOWN.",
  SOURCE_CURRENT_CARD_MISMATCH: "Актуальная официальная карточка не совпадает с исходными документами. Результат не подтверждён.",
  CUSTOMER_SCOPE_IDENTITY_NOT_CONFIRMED: "Заказчик, которому принадлежит сравниваемый контракт в совместной закупке, не подтверждён.",
  CUSTOMER_IDENTITY_REQUIRED: "Для совместной закупки нужен подтверждённый заказчик: общая цена закупки не заменяет цену его контракта.",
  CUSTOMER_IDENTITY_UNCONFIRMED: "Не найдено однозначное соответствие заказчика между контрактом и извещением.",
  CUSTOMER_NUMBER_INVALID: "Регистрационный номер заказчика в ЕИС указан некорректно.",
  CUSTOMER_INITIAL_UNCONFIRMED: "Начальная сумма полного контракта этого заказчика не подтверждена.",
  CUSTOMER_GLOBAL_INITIAL_UNCONFIRMED: "Общая начальная сумма совместной закупки не подтверждена, поэтому распределение между заказчиками нельзя проверить.",
  CUSTOMER_NATIVE_RUB_NOT_CONFIRMED: "Исходные рублёвые суммы совместной закупки не подтверждены.",
  CUSTOMER_CURRENCY_SCOPE_UNSUPPORTED: "В данных заказчика указана неподдерживаемая валюта. Пересчёт валюты для сравнения не выполняется.",
  CUSTOMER_FORMULA_PRICE_NOT_SUPPORTED: "Цена контракта заказчика задана формулой и не подтверждает фиксированную начальную сумму.",
  CUSTOMER_SELECTED_ITEMS_UNAVAILABLE_OR_LIMIT: "Полный состав позиций заказчика отсутствует или превышает предел проверки.",
  CUSTOMER_PARTITION_LIMIT: "Распределение совместной закупки превышает предел проверки; полный объём заказчика не подтверждён.",
  CUSTOMER_PARTITION_IDENTITY_INVALID: "В распределении совместной закупки не подтверждены регистрационные номера всех заказчиков.",
  CUSTOMER_PARTITION_DUPLICATE_BUYER: "Заказчик повторяется в распределении совместной закупки; его полный объём неоднозначен.",
  CUSTOMER_PARTITION_SID_INVALID_OR_DUPLICATE: "Идентификаторы исходных позиций отсутствуют или повторяются; распределение не подтверждено.",
  CUSTOMER_PARTITION_NON_PRODUCT: "Распределение содержит позиции, для которых сопоставимый товарный объём не поддержан.",
  CUSTOMER_PARTITION_ITEM_NUMERIC_UNCONFIRMED: "В исходной позиции не подтверждены положительные числовые цена, количество или сумма.",
  CUSTOMER_PARTITION_ITEM_TOTAL_CONFLICT: "Цена, количество и объявленная сумма исходной позиции противоречат друг другу.",
  CUSTOMER_PARTITION_ALLOCATION_MISSING: "Для одной или нескольких позиций отсутствует распределение количества по заказчикам.",
  CUSTOMER_PARTITION_ALLOCATION_BUYER_INVALID: "Количество отнесено к неизвестному или повторно указанному заказчику.",
  CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED: "Количество для заказчика задано неоднозначно или не подтверждено числом.",
  CUSTOMER_PARTITION_QUANTITY_CONFLICT: "Сумма количеств по заказчикам не совпадает с общим количеством позиции.",
  CUSTOMER_PARTITION_GLOBAL_TOTAL_CONFLICT: "Суммы по заказчикам или позициям не совпадают с общей начальной ценой закупки.",
  CUSTOMER_PARTITION_BUYER_TOTAL_CONFLICT: "Стоимость распределённых позиций не совпадает с начальной суммой контракта одного из заказчиков.",
  CARD_CONTENT_TYPE_UNCONFIRMED: "Тип ответа официальной карточки не подтверждён; источник требует проверки.",
  CARD_RESPONSE_DATE_UNCONFIRMED: "Время ответа официальной карточки не подтверждено; актуальность источника неизвестна.",
  CARD_RESPONSE_DATE_OUTSIDE_CAPTURE: "Время ответа карточки не соответствует времени её проверки; актуальность источника неизвестна.",
  CARD_CACHED_RESPONSE: "Официальная карточка получена из кеша; её актуальное состояние не подтверждено.",
  CARD_CACHE_AGE_UNCONFIRMED: "Возраст сохранённого ответа карточки не подтверждён; актуальность источника неизвестна.",
  CARD_CACHE_WARNING_PRESENT: "Источник сообщил предупреждение об актуальности сохранённого ответа карточки.",
  CARD_CAPTURE_TIME_INVALID: "Время получения официальной карточки указано неоднозначно.",
  CARD_CHALLENGE_PAGE: "Вместо официальной карточки получена страница ограничения доступа или проверки посетителя.",
  CARD_CONTENT_SIZE_INVALID: "Ответ официальной карточки пуст или превышает предел проверки.",
  CARD_CONTENT_TYPE_UNSUPPORTED: "Источник вернул неподдерживаемый формат вместо официальной карточки.",
  CARD_CURRENCY_UNCONFIRMED: "Рублёвая валюта цены в официальной карточке не подтверждена.",
  CARD_DATE_INVALID: "Дата в официальной карточке не распознана однозначно.",
  CARD_FIELDS_CONTRADICT: "Поля официальной карточки противоречат друг другу.",
  CARD_FIELD_MISSING_OR_DUPLICATE: "В официальной карточке отсутствует обязательное поле или найдено несколько его значений.",
  CARD_HEADERS_AMBIGUOUS: "Сведения об ответе официального источника неоднозначны.",
  CARD_HTML_COMPLEXITY_LIMIT: "Структура официальной карточки превышает предел проверки.",
  CARD_HTML_INVALID: "Содержимое официальной карточки не удалось надёжно прочитать.",
  CARD_HTTP_STATUS_INVALID: "Официальный источник не подтвердил успешное получение карточки.",
  CARD_NUMBER_INVALID: "Номер закупки или контракта в официальной карточке некорректен.",
  CARD_PRICE_INVALID: "Цена в официальной карточке не подтверждена точным положительным числом.",
  CARD_REDIRECT_CHAIN_UNCONFIRMED: "Переходы к официальной карточке не подтверждены полностью.",
  CARD_REDIRECT_UNSUPPORTED: "Источник перенаправил запрос по неподтверждённому маршруту.",
  CARD_URL_MISMATCH: "Адрес официальной карточки не соответствует ожидаемой закупке или контракту.",
  SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED: "Извещение и контракт прочитаны с разрывом более 10 минут: их общий актуальный срез не подтверждён.",
  REGIONAL_HISTORY_223_NOT_SUPPORTED: "История сопоставимых контрактов по 223-ФЗ пока не поддержана. Региональное снижение остаётся UNKNOWN; ручной режим можно выбрать явно.",
  HISTORY_REGION_CATALOG_UNAVAILABLE: "Официальный справочник регионов недоступен. Регион поставки и региональное снижение не подтверждены.",
  CONTRACT_ANNULMENT_IN_SOURCE: "В источнике есть аннулирование контракта.",
  CONTRACT_INVALID_IN_SOURCE: "Источник содержит признак недействительности контракта либо не позволяет однозначно исключить его.",
  CONTRACT_UNDEFINED_VOLUME_NOT_SUPPORTED: "Контракт с неопределённым или неподтверждённым фиксированным объёмом не поддержан этой проверкой.",
  CONTRACT_COMPANION_NOT_SUPPORTED: "Сопутствующий документ контракта не поддержан проверкой.",
  CONTRACT_VERSION_UNKNOWN: "Версия контракта неизвестна.",
  CONTRACT_VERSION_CONFLICT: "Источники противоречат друг другу в версии контракта.",
  CONTRACT_VERSION_GAP: "В истории версий контракта есть пропуски.",
  CONTRACT_COMMERCIAL_SCOPE_CHANGED: "В последующих версиях изменились коммерческие условия или состав контракта.",
  NOTICE_SOURCE_DOCUMENT_UNSUPPORTED: "Документ извещения не поддержан проверкой истории.",
  NOTICE_CANCELLATION_EVENT_PRESENT: "В источнике есть событие отмены извещения.",
  NOTICE_NUMBER_CONFLICT: "Номер извещения не совпадает с ожидаемым.",
  NOTICE_VERSION_CONFLICT: "Источники противоречат друг другу в версии извещения.",
  NOTICE_VERSION_GAP: "В истории версий извещения есть пропуски.",
  CONTRACT_SIGN_DATE_UNKNOWN: "Дата подписания контракта неизвестна.",
  NOTICE_PUBLICATION_UNKNOWN: "Дата публикации извещения неизвестна.",
  NOTICE_VERSION_AT_SIGN_DATE_AMBIGUOUS: "Нельзя однозначно выбрать редакцию извещения на дату подписания.",
  APPLICABLE_NOTICE_VERSION_UNKNOWN: "Применимая редакция извещения не подтверждена.",
  WHOLE_SOURCE_OBJECT_SCOPE_NOT_BOUND: "Полный состав позиций контракта не связан с извещением.",
  SOURCE_OBJECT_QUANTITY_UNIT_OR_PRODUCT_CHANGED: "Изменились товар, количество или единица позиции.",
  WHOLE_NOMINAL_TOTAL_UNKNOWN: "Полная номинальная сумма не подтверждена.",
  WHOLE_NOMINAL_TOTAL_SCOPE_MISMATCH: "Полная номинальная сумма не соответствует составу позиций.",
  CONTRACT_NOTICE_DELIVERY_REGION_NOT_BOUND: "Регион поставки контракта не связан с регионом извещения.",
  WHOLE_HOMOGENEOUS_MARKET_SCOPE_UNKNOWN: "Единая сопоставимая товарная группа всего контракта не подтверждена.",
  CONTRACT_PUBLICATION_UNKNOWN_OR_FUTURE: "Дата публикации контракта неизвестна или находится в будущем.",
  WHOLE_SCOPE_ITEMS_UNAVAILABLE_OR_LIMIT: "Полный состав позиций недоступен или превышает предел проверки.",
  DRUG_SCOPE_NOT_SUPPORTED: "Лекарственные позиции не поддержаны этой проверкой сопоставимости.",
  REPLACED_SOURCE_PRODUCT: "В источнике указана замена товара.",
  FIXED_PRODUCT_VOLUME_NOT_CONFIRMED: "Фиксированный объём позиции не подтверждён.",
  NOTICE_NATIVE_RUB_NOT_CONFIRMED: "Исходная рублёвая валюта извещения не подтверждена.",
  NOTICE_FORMULA_PRICE_NOT_SUPPORTED: "Извещение содержит формулу цены либо не подтверждает её отсутствие. Такая цена не поддержана проверкой снижения.",
  NOTICE_QUANTITY_DEFINITION_UNKNOWN: "Правило определения количества в извещении неизвестно.",
  FIXED_CONTRACT_PRICE_NOT_CONFIRMED: "Фиксированная подписанная сумма контракта не подтверждена.",
  CONTRACT_NATIVE_RUB_NOT_CONFIRMED: "Исходная рублёвая валюта контракта не подтверждена.",
  FORMULA_OR_RIGHT_TO_CONCLUDE_PRICE: "Цена задана формулой или относится к праву заключить контракт.",
  REPLACEMENT_CONTRACT_NOT_ORIGINAL_AWARD: "Контракт заключён взамен другого и не подтверждает первоначальный результат закупки.",
  DELIVERY_SCOPE_NOT_EXTRACTED: "Полная география поставки не извлечена.",
  DELIVERY_SCOPE_UNSUPPORTED: "Способ описания места поставки не поддержан.",
  DELIVERY_ADDRESS_UNKNOWN: "Адрес поставки неизвестен.",
  TECHNICAL_LEGAL_AND_FULL_PROFILE_REVIEW_REQUIRED: "Технические, юридические и остальные ограничения профиля ещё требуют проверки.",
};
export function betaReason(code: string): string {
  if (reasonLabels[code]) return reasonLabels[code];
  const labels: Record<string,string> = { MIN_CONTRACT_AMOUNT: "минимальная сумма контракта", MAX_CONTRACT_AMOUNT: "максимальная сумма контракта", MIN_MARGIN: "минимальная маржа", MIN_EXPECTED_PROFIT: "минимальная прибыль" };
  const match = /^PROFILE_(.+)_(UNKNOWN|FAIL)$/.exec(code);
  if (match && labels[match[1]]) return `${labels[match[1]]}: ${match[2] === "FAIL" ? "ограничение профиля нарушено" : "в профиле не подтверждено"}.`;
  return "Источник не подтвердил данные, необходимые для этой проверки. Результат остаётся неопределённым.";
}


export function betaCalculationLabel(status: "CALCULATED" | "UNKNOWN" | "BLOCKED"): string {
  return { CALCULATED: "Рассчитано по введённому КП", UNKNOWN: "Не хватает подтверждённых данных", BLOCKED: "Расчёт заблокирован" }[status];
}


/** A previous calculation cannot keep expired or blocked input active in the UI. */
export function financialQuoteCurrent(report: BetaQuoteReport, deadline: string | null, blocked: boolean, now = Date.now()): boolean {
  if (blocked || !Number.isFinite(now) || report.calculation?.status !== "CALCULATED" ||
      report.calculation.participation !== "UNKNOWN" || report.input?.covers_full_scope !== true) return false;
  if ((quoteDiscountMode(report.input) === "REGIONAL" || report.calculation.discount_basis === "REGIONAL_HISTORY") &&
      (report.calculation.discount_basis !== "REGIONAL_HISTORY" || report.calculation.regional_discount?.status !== "PASS" ||
      !betaHistoryMatches({ ref: report.ref, history: report.calculation.regional_discount, source_reasons: [] }, report.ref))) return false;
  const issued = awareDeadline(report.input.issued_at);
  const until = awareDeadline(report.input.valid_until);
  const end = awareDeadline(deadline);
  return !!issued && !!until && !!end && Date.parse(issued) <= now && now < Date.parse(until) && now < Date.parse(end);
}
