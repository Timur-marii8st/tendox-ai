"use server";
import { createIndexedRequirementProposal, readIndexedRequirementProposal, createIndexedRequirementDecision, readIndexedRequirementComparison } from "@/lib/procurement-api";
import { validProposalRequest, validDecisionRequest, validReviewId, proposalMatches, type ProposalRequest, type DecisionRequest, type RequirementProposal, type SavedRequirementProposal, type SavedRequirementDecision, type RequirementComparison, type RequirementReviewState } from "@/lib/eis-requirement-review";
import { readIndexedRequirementPreview } from "@/lib/procurement-api";
import { validRequirementPreviewRequest, type RequirementPreviewRequest, type RequirementPreviewState } from "@/lib/eis-requirement-preview";
import { prepareIndexedSupplierPage, readIndexedSupplierPage } from "@/lib/procurement-api";
import { validSupplierPageRequest, type SupplierPageRequest, type SupplierPageState } from "@/lib/eis-supplier-page";
import { prepareIndexedSupplierProduct, readIndexedSupplierProduct } from "@/lib/procurement-api";
import { validSupplierProductRequest, type SupplierProductRequest, type SupplierProductState } from "@/lib/eis-supplier-product";
import { prepareIndexedSupplierCatalog, readIndexedSupplierCatalog } from "@/lib/procurement-api";
import { validSupplierCatalogRequest, type SupplierCatalogRequest, type SupplierCatalogState } from "@/lib/eis-supplier-catalog";
import { prepareIndexedSupplierSerp, readIndexedSupplierSerp } from "@/lib/procurement-api";
import type { SupplierSerpState } from "@/lib/eis-supplier-serp";
import { requestIndexedPositionAssociation, listIndexedPositionAssociations, readIndexedPositionAssociationDetail } from "@/lib/procurement-api";
import { validAssociationRequest, validAssociationListRequest, validAssociationDetailRequest,
  type AssociationRequest, type AssociationState, type AssociationListRequest,
  type AssociationListState, type AssociationDetailRequest } from "@/lib/eis-position-association";
import { prepareIndexedSupplierSearch, readIndexedSupplierSearch } from "@/lib/procurement-api";
import { validSupplierSearchRequest, type SupplierSearchRequest, type SupplierSearchState } from "@/lib/eis-supplier-search";

import {
  ApiError, ConfigurationError, discoverEisExport, inspectEisAttachment,
  listLiveEisDocuments, searchIndexedEis, searchLiveEis,
  type EisDiscoveryResult, type EisDocumentPreview, type EisPublicDocumentsResult,
  type EisPublicSearchResult, type EisIndexedSearchResult,
  type EisLiveVerification, verifyLiveEisNumber,
  requestIndexedDocuments, readIndexedDocuments, readIndexedDocumentAnalysis,
  type NoticeDocumentRef, type DocumentCollectionStatus,
  selectIndexedDocuments, type DocumentSelectionResult,
  readIndexedEvidence, type EisEvidenceBridge,
  estimateIndexedNotice, type EisPreliminaryEstimate,
  requestEisRefresh, readEisRefresh, type EisRefreshStatus,
  compareIndexedNotices, type EisComparisonResult,
  searchIndexedEis223, type Eis223SearchResult,
  readIndexed223Documents, type Document223Status,
  requestIndexed223Documents,
  compareIndexed223Notices, type Comparison223Result,
  compareMixedNotices, type MixedNoticeRef, type MixedComparisonResult,
  estimateSourceNotice, type SourceEstimateRequest, type SourceEstimateResult,
  readEis223RegionalCoverage, type Eis223RegionalCoverage,
  readHistoricalProtocols,
  readHistoricalAnalogs,
  readCharacteristicPair,
} from "@/lib/procurement-api";
import { validAnalogRequest, type AnalogRequest, type AnalogReadState } from "@/lib/eis-analogs";
import { validCharacteristicRequest, type CharacteristicPairRequest, type CharacteristicReadState } from "@/lib/eis-characteristics";
import { validProtocolRef, type HistoricalProtocolReport } from "@/lib/eis-protocols";
import type { DocumentAnalysis } from "@/lib/eis-workflow-api";
import { prepareIndexedDocumentReview, readIndexedDocumentReview } from "@/lib/procurement-api";
import { validReviewCursor, validReviewRequest, type ReviewCursor, type ReviewRequest, type ReviewReadState } from "@/lib/eis-document-review";
import {
  WorkflowApiError, WorkflowConfigurationError, advanceDiscoveryRun, analyzeDiscoveryCandidate,
  cancelDiscoveryRun,
  createDiscoveryRun, getDiscoveryRun, listDiscoveryRuns, requestDiscoveryCustomerHistory,
  updateDiscoveryCosts,
  type DiscoveryCostInput, type DiscoveryRun, type DiscoveryRunSummary,
} from "@/lib/eis-workflow-api";

export type DiscoveryState = { result?: EisDiscoveryResult; error?: string };
export type AttachmentState = { result?: EisDocumentPreview; error?: string };
export type LiveSearchState = { result?: EisPublicSearchResult; error?: string };
export type IndexedSearchState = {
  result?: EisIndexedSearchResult; error?: string;
  refresh?: EisRefreshStatus; refreshError?: string;
};
export type LiveDocumentsState = { result?: EisPublicDocumentsResult; error?: string };

function reviewError(error: unknown): string {
  if (error instanceof ConfigurationError) return "Доступ к API не настроен.";
  if (error instanceof ApiError && [401, 403].includes(error.status)) return "Нет прав на это действие в вашей организации.";
  if (error instanceof ApiError && [404, 409, 422].includes(error.status)) return "Текст не прочитан: проверьте актуальную карточку, полученный DOCX и целостность источника. Повторите поиск.";
  return "Анализ документа занят или временно недоступен. Повторите запрос.";
}
export async function prepareDocumentReview(payload: ReviewRequest): Promise<ReviewReadState> {
  if (!validReviewRequest(payload)) return { error: "Выберите точную карточку и полученный документ с SHA-256." };
  try { return { result: await prepareIndexedDocumentReview(payload) }; }
  catch (error) { return { error: reviewError(error) }; }
}
export async function loadDocumentReview(payload: ReviewRequest, cursor: ReviewCursor): Promise<ReviewReadState> {
  if (!validReviewRequest(payload) || !validReviewCursor(cursor)) return { error: "Некорректный документ или страница текста." };
  try { return { result: await readIndexedDocumentReview(payload, cursor) }; }
  catch (error) { return { error: reviewError(error) }; }
}

export async function loadCharacteristicPair(payload: CharacteristicPairRequest): Promise<CharacteristicReadState> {
  if (!validCharacteristicRequest(payload)) return { error: "Выберите две точные карточки и позиции 1–25." };
  try { return { result: await readCharacteristicPair(payload) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && [401, 403].includes(error.status)) return { error: "Нет доступа к данным вашей организации." };
    if (error instanceof ApiError && [404, 409, 422].includes(error.status)) {
      return { error: "Характеристики не прочитаны: проверьте версии, позиции и целостность источников." };
    }
    return { error: "Сравнение характеристик сейчас недоступно. Повторите запрос." };
  }
}

export async function loadHistoricalAnalogs(payload: AnalogRequest): Promise<AnalogReadState> {
  if (!validAnalogRequest(payload)) return { error: "Выберите точную карточку, позицию 1–25, запрос и период 1–730 дней." };
  try { return { result: await readHistoricalAnalogs(payload) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && [401, 403].includes(error.status)) return { error: "Нет доступа к истории вашей организации." };
    if (error instanceof ApiError && [404, 409, 422].includes(error.status)) {
      return { error: "Выборка не прочитана: проверьте версию карточки, позицию, источники и лимиты разбора. Повторите поиск." };
    }
    return { error: "Историческая выборка сейчас недоступна. Повторите запрос." };
  }
}

export async function loadHistoricalProtocols(ref: NoticeDocumentRef): Promise<{
  result?: HistoricalProtocolReport; error?: string;
}> {
  if (!validProtocolRef(ref)) return { error: "Выберите карточку с точным номером, версией и XML SHA." };
  try { return { result: await readHistoricalProtocols(ref) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && [401, 403].includes(error.status)) return { error: "Нет доступа к протоколам вашей организации." };
    if (error instanceof ApiError && [404, 409, 422].includes(error.status)) {
      return { error: "Протоколы не прочитаны: проверьте версию карточки, её источники и лимиты разбора. Повторите поиск." };
    }
    return { error: "Сохранённые протоколы сейчас недоступны. Повторите запрос." };
  }
}

export type Indexed223State = { result?: Eis223SearchResult; error?: string };
export type Eis223RegionalCoverageState = {
  result?: Eis223RegionalCoverage;
  error?: string;
};

export async function loadEis223RegionalCoverage(): Promise<Eis223RegionalCoverageState> {
  try { return { result: await readEis223RegionalCoverage() }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 503) {
      return { error: "Сведения об охвате 223-ФЗ пока недоступны." };
    }
    return { error: "Не удалось обновить сведения об охвате 223-ФЗ." };
  }
}
export async function estimateSource(payload: SourceEstimateRequest): Promise<{ result?: SourceEstimateResult; error?: string }> {
  try { return { result: await estimateSourceNotice(payload) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 403) return { error: "Ввод расчёта доступен оператору." };
    if (error instanceof ApiError && error.status === 404) return { error: "Выбранная версия не найдена. Повторите поиск." };
    if (error instanceof ApiError && error.status === 409) return { error: "Источники версии требуют проверки. Повторите поиск." };
    if (error instanceof ApiError && error.status === 422) return { error: "Проверьте лот, точные суммы, доли и основание затрат. Консервативное снижение должно быть не меньше реалистичного." };
    return { error: "Предварительный расчёт не завершён. Повторите запрос." };
  }
}
export async function compareMixed(notices: MixedNoticeRef[]): Promise<{ result?: MixedComparisonResult; error?: string }> {
  if (notices.length < 2 || notices.length > 3 ||
    new Set(notices.map(n => `${n.law}:${n.purchase_number}`)).size !== notices.length ||
    notices.some(n => (n.law !== "44" && n.law !== "223") ||
      !(n.law === "44" ? /^[0-9]{19,23}$/ : /^[0-9]{11}$/).test(n.purchase_number) ||
      !Number.isInteger(n.version_number) || n.version_number < 1 || !/^[0-9a-f]{64}$/.test(n.notice_xml_sha256))) {
    return { error: "Выберите 2–3 разные карточки с точным законом и версией." };
  }
  try { return { result: await compareMixedNotices(notices) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 404) return { error: "Одна из выбранных версий не найдена в вашей организации. Повторите поиск." };
    if (error instanceof ApiError && error.status === 409) return { error: "Источник выбранной версии требует проверки. Повторите поиск." };
    return { error: "Общее сравнение не завершено. Повторите запрос." };
  }
}
export async function compareIndexed223(notices: NoticeDocumentRef[]): Promise<{ result?: Comparison223Result; error?: string }> {
  if (notices.length < 2 || notices.length > 3 || new Set(notices.map(n => n.purchase_number)).size !== notices.length ||
    notices.some(n => !/^[0-9]{11}$/.test(n.purchase_number) || !Number.isInteger(n.version_number) ||
      n.version_number < 1 || !/^[0-9a-f]{64}$/.test(n.notice_xml_sha256))) {
    return { error: "Выберите 2–3 разные закупки 223-ФЗ." };
  }
  try { return { result: await compareIndexed223Notices(notices) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 404) return { error: "Одна из версий не найдена в вашей организации. Повторите поиск." };
    if (error instanceof ApiError && error.status === 409) return { error: "Источники выбранной версии противоречат друг другу. Повторите поиск." };
    return { error: "Не удалось сравнить сохранённые карточки 223-ФЗ." };
  }
}
export async function loadIndexed223Documents(ref: NoticeDocumentRef, collect = false): Promise<{ result?: Document223Status; error?: string }> {
  if (!/^[0-9]{11}$/.test(ref.purchase_number) || !Number.isInteger(ref.version_number) ||
      ref.version_number < 1 || !/^[0-9a-f]{64}$/.test(ref.notice_xml_sha256)) {
    return { error: "Некорректная версия карточки 223-ФЗ." };
  }
  try { return { result: await (collect ? requestIndexed223Documents(ref) : readIndexed223Documents(ref)) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 429) return { error: "Очередь документов заполнена или достигнут лимит запросов. Повторите позже." };
    if (error instanceof ApiError && error.status === 409) return { error: "Сбор не запущен: версия устарела, срок истёк или состав документов требует проверки." };
    return { error: "Не удалось прочитать сохранённые документы этой версии 223-ФЗ." };
  }
}
export async function searchIndexed223(_: Indexed223State, form: FormData): Promise<Indexed223State> {
  const query = form.get("query");
  if (typeof query !== "string" || !query.trim() || query.length > 120) {
    return { error: "Укажите товарный запрос до 120 символов." };
  }
  try { return { result: await searchIndexedEis223(query.trim()) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 422) return { error: "Укажите название товара с характеристиками." };
    return { error: "Не удалось прочитать индекс 223-ФЗ." };
  }
}

export async function loadIndexedSearchPage(query: string, scope: "ALL_CACHED" | "NOT_EXPIRED_OR_UNKNOWN", cursor: string): Promise<IndexedSearchState & { restartRequired?: boolean }> {
  if (!query.trim() || query.length > 120 || !/^[A-Za-z0-9_-]{1,2048}$/.test(cursor) ||
      (scope !== "ALL_CACHED" && scope !== "NOT_EXPIRED_OR_UNKNOWN")) return { error: "Некорректное продолжение поиска." };
  try { return { result: await searchIndexedEis(query.trim(), scope, cursor) }; }
  catch (error) { return searchPageError(error); }
}

export async function loadIndexed223SearchPage(query: string, cursor: string): Promise<Indexed223State & { restartRequired?: boolean }> {
  if (!query.trim() || query.length > 120 || !/^[A-Za-z0-9_-]{1,2048}$/.test(cursor)) return { error: "Некорректное продолжение поиска." };
  try { return { result: await searchIndexedEis223(query.trim(), cursor) }; }
  catch (error) { return searchPageError(error); }
}

function searchPageError(error: unknown): { error: string; restartRequired?: boolean } {
  if (error instanceof ApiError && (error.status === 409 || error.status === 410)) return {
    error: error.status === 410 ? "Время просмотра снимка истекло. Повторите поиск."
      : "Состав результатов или блокировки изменились. Повторите поиск для согласованной выдачи.", restartRequired: true,
  };
  if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
  return { error: "Продолжение поиска не получено. Можно повторить загрузку." };
}

export async function verifyLiveNumber(number: string): Promise<{
  result?: EisLiveVerification; error?: string;
}> {
  if (!/^[0-9]{19,23}$/.test(number)) return { error: "Неверный реестровый номер." };
  try { return { result: await verifyLiveEisNumber(number) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Проверка XML ЕИС не завершена (HTTP ${error.status}).` };
    return { error: "Не удалось получить официальный XML по номеру." };
  }
}

function documentCollectionError(error: unknown): string {
  if (error instanceof ConfigurationError) return "Доступ к API не настроен.";
  if (error instanceof ApiError && error.status === 409) return "Карточка изменилась. Повторите поиск и выберите новую версию.";
  if (error instanceof ApiError && error.status === 422) return "Комплект не принят: проверьте версию карточки и лимиты документов.";
  if (error instanceof ApiError && error.status === 404) return "Документ или карточка не найдены в вашей организации.";
  return "Не удалось прочитать очередь документов.";
}

export async function prepareIndexedDocuments(ref: NoticeDocumentRef): Promise<{
  result?: DocumentCollectionStatus; error?: string;
}> {
  try { return { result: await requestIndexedDocuments(ref) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function loadIndexedDocuments(ref: NoticeDocumentRef): Promise<{
  result?: DocumentCollectionStatus; error?: string;
}> {
  try { return { result: await readIndexedDocuments(ref) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function loadIndexedAnalysis(ref: NoticeDocumentRef, uid: string): Promise<{
  result?: DocumentAnalysis; error?: string;
}> {
  try { return { result: await readIndexedDocumentAnalysis(ref, uid) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function loadIndexedEvidence(ref: NoticeDocumentRef): Promise<{
  result?: EisEvidenceBridge; error?: string;
}> {
  try { return { result: await readIndexedEvidence(ref) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function compareIndexed(notices: NoticeDocumentRef[]): Promise<{
  result?: EisComparisonResult; error?: string;
}> {
  if (notices.length < 2 || notices.length > 3 ||
      new Set(notices.map((ref) => ref.purchase_number)).size !== notices.length) {
    return { error: "Выберите от 2 до 3 разных закупок." };
  }
  try { return { result: await compareIndexedNotices(notices) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function estimateIndexedEconomics(ref: NoticeDocumentRef, form: FormData): Promise<{
  result?: EisPreliminaryEstimate; error?: string;
}> {
  const goods = form.get("goods");
  const expenses = form.get("expenses");
  const vatRate = form.get("vat_rate");
  const basis = form.get("basis");
  if ([goods, expenses, vatRate, basis].some((value) => typeof value !== "string" || !value.trim())) {
    return { error: "Укажите стоимость товара, прочие расходы, НДС и источник оценки." };
  }
  try {
    return { result: await estimateIndexedNotice(ref, {
      goods: goods as string, expenses: expenses as string, vat_rate: vatRate as string,
      basis: basis as string, costs_complete_ack: form.get("costs_complete_ack") === "on",
    }) };
  } catch (error) {
    if (error instanceof ApiError && error.status === 422) {
      return { error: "Проверьте суммы, ставку НДС и точность данных; десятичные значения вводятся строками." };
    }
    return { error: documentCollectionError(error) };
  }
}

export async function prepareTopIndexedDocuments(query: string): Promise<{
  result?: DocumentSelectionResult; error?: string;
}> {
  try { return { result: await selectIndexedDocuments(query) }; }
  catch (error) { return { error: documentCollectionError(error) }; }
}

export async function searchIndexed(
  _: IndexedSearchState, form: FormData,
): Promise<IndexedSearchState> {
  const query = form.get("query");
  if (typeof query !== "string" || !query.trim() || query.length > 120) {
    return { error: "Укажите товарный запрос до 120 символов." };
  }
  const searchScope = form.get("search_scope") ?? "NOT_EXPIRED_OR_UNKNOWN";
  if (searchScope !== "ALL_CACHED" && searchScope !== "NOT_EXPIRED_OR_UNKNOWN") {
    return { error: "Выберите поиск по сроку или по всей сохранённой истории." };
  }
  try {
    const result = await searchIndexedEis(query.trim(), searchScope);
    if (form.get("refresh") !== "on") return { result };
    const regions = String(form.get("regions") ?? "").split(",").map((code) => code.trim()).filter(Boolean);
    if (!regions.length || regions.length > 3 || regions.some((code) => !/^[0-9]{2}$/.test(code))) {
      return { result, refreshError: "Для обновления укажите от 1 до 3 кодов регионов через запятую." };
    }
    try { return { result, refresh: await requestEisRefresh(query.trim(), regions) }; }
    catch (error) { return { result, refreshError: refreshError(error) }; }
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError && error.status === 503) return { error: "Индекс ЕИС пока не подключён к базе данных." };
    if (error instanceof ApiError && error.status === 422) return { error: "Укажите название товара вместе с характеристиками, например «бумага А4 80»." };
    if (error instanceof ApiError) return { error: `Поиск по индексу не завершён (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать индекс ЕИС." };
  }
}

function refreshError(error: unknown): string {
  if (error instanceof ConfigurationError) return "Доступ к API не настроен.";
  if (error instanceof ApiError && error.status === 429) return "Очередь обновления занята. Повторите через минуту.";
  if (error instanceof ApiError && error.status === 422) return "Проверьте региональные коды ЕИС: до трёх разных кодов от 01 до 99.";
  if (error instanceof ApiError && error.status === 404) return "Запрос обновления не найден в вашей организации.";
  return "Обновление ЕИС не поставлено в очередь или статус недоступен.";
}

export async function loadEisRefresh(requestId: string): Promise<{ result?: EisRefreshStatus; error?: string }> {
  try { return { result: await readEisRefresh(requestId) }; }
  catch (error) { return { error: refreshError(error) }; }
}

export async function searchLive(_: LiveSearchState, form: FormData): Promise<LiveSearchState> {
  const query = form.get("query");
  if (typeof query !== "string" || !query.trim() || query.length > 120) {
    return { error: "Укажите товарный запрос до 120 символов." };
  }
  try {
    return { result: await searchLiveEis(query.trim()) };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Поиск ЕИС не завершён (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать публичную выдачу ЕИС." };
  }
}

export async function listLiveDocuments(
  _: LiveDocumentsState, form: FormData,
): Promise<LiveDocumentsState> {
  const url = form.get("url");
  if (typeof url !== "string") return { error: "Ссылка на документы отсутствует." };
  try {
    return { result: await listLiveEisDocuments(url) };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Документы ЕИС не прочитаны (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать страницу документов ЕИС." };
  }
}

export async function searchExport(_: DiscoveryState, form: FormData): Promise<DiscoveryState> {
  const file = form.get("file");
  const query = form.get("query");
  if (!(file instanceof File) || !file.size || file.size > 20 * 1024 * 1024 ||
      !/\.(xml|zip)$/i.test(file.name) || typeof query !== "string" ||
      !query.trim() || query.length > 120) {
    return { error: "Укажите товар и загрузите XML или ZIP до 20 МиБ." };
  }
  try {
    return { result: await discoverEisExport(file, query.trim()) };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Выгрузка не прочитана (HTTP ${error.status}).` };
    return { error: "Не удалось проанализировать выгрузку ЕИС." };
  }
}

export async function inspectAttachment(_: AttachmentState, form: FormData): Promise<AttachmentState> {
  const url = form.get("url");
  const filename = form.get("filename");
  if (typeof url !== "string" || typeof filename !== "string") {
    return { error: "Ссылка на документ отсутствует." };
  }
  try {
    return { result: await inspectEisAttachment({ url, filename, locator: "attachment/url" }) };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Документ ЕИС недоступен или отклонён (HTTP ${error.status}).` };
    return { error: "Не удалось скачать и прочитать документ." };
  }
}

export type WorkflowResult<T> = { result?: T; error?: string; notFound?: boolean };

function workflowError(error: unknown): WorkflowResult<never> {
  if (error instanceof WorkflowConfigurationError) return { error: "Доступ к API не настроен." };
  if (error instanceof WorkflowApiError) {
    return {
      error: error.status === 404
        ? "Сессия не найдена или недоступна в текущей организации."
        : `Операция сессии не завершена (HTTP ${error.status}).`,
      notFound: error.status === 404,
    };
  }
  return { error: "Не удалось связаться с сервисом анализа ЕИС." };
}

export async function loadDiscoveryRuns(): Promise<WorkflowResult<DiscoveryRunSummary[]>> {
  try { return { result: await listDiscoveryRuns() }; } catch (error) { return workflowError(error); }
}

export async function loadDiscoveryRun(runId: string): Promise<WorkflowResult<DiscoveryRun>> {
  try { return { result: await getDiscoveryRun(runId) }; } catch (error) { return workflowError(error); }
}

export async function startDiscoveryRun(input: {
  query: string; max_pages: number; max_candidates: number; max_documents: number;
  search_page_size: number;
}): Promise<WorkflowResult<DiscoveryRun>> {
  const query = input.query.trim();
  if (!query || query.length > 120 || !Number.isInteger(input.max_pages) ||
      input.max_pages < 1 || input.max_pages > 20 || !Number.isInteger(input.max_candidates) ||
      input.max_candidates < 1 || input.max_candidates > 10 || !Number.isInteger(input.max_documents) ||
      input.max_documents < 1 || input.max_documents > 12 ||
      (input.search_page_size !== 50 && input.search_page_size !== 100)) {
    return { error: "Проверьте запрос и границы поиска." };
  }
  try { return { result: await createDiscoveryRun({ ...input, query, search_page_size: input.search_page_size }) }; }
  catch (error) { return workflowError(error); }
}

export async function advanceDiscovery(runId: string): Promise<WorkflowResult<DiscoveryRun>> {
  try { return { result: await advanceDiscoveryRun(runId) }; }
  catch (error) { return workflowError(error); }
}

export async function cancelDiscovery(runId: string): Promise<WorkflowResult<DiscoveryRun>> {
  try { return { result: await cancelDiscoveryRun(runId) }; }
  catch (error) { return workflowError(error); }
}

export async function analyzeCandidate(
  runId: string,
  purchaseNumber: string,
): Promise<WorkflowResult<DiscoveryRun>> {
  try { return { result: await analyzeDiscoveryCandidate(runId, purchaseNumber) }; }
  catch (error) { return workflowError(error); }
}

export async function requestCustomerHistory(
  runId: string,
  purchaseNumber: string,
): Promise<WorkflowResult<DiscoveryRun>> {
  try { return { result: await requestDiscoveryCustomerHistory(runId, purchaseNumber) }; }
  catch (error) { return workflowError(error); }
}

export async function saveDiscoveryCosts(
  runId: string,
  purchaseNumber: string,
  input: DiscoveryCostInput,
): Promise<WorkflowResult<DiscoveryRun>> {
  const decimal = /^\d+(?:\.\d+)?$/;
  const fraction = /^(?:0(?:\.\d+)?|1(?:\.0+)?)$/;
  if (!decimal.test(input.goods) || !decimal.test(input.expenses) ||
      !fraction.test(input.vat_rate) || !fraction.test(input.realistic_discount) ||
      !fraction.test(input.conservative_discount) ||
      !fraction.test(input.conservative_cost_growth) || !input.basis.trim()) {
    return { error: "Заполните суммы и доли десятичными строками, а также укажите источник цен." };
  }
  try { return { result: await updateDiscoveryCosts(runId, purchaseNumber, { ...input, basis: input.basis.trim() }) }; }
  catch (error) { return workflowError(error); }
}

export async function prepareSupplierSearch(request: SupplierSearchRequest, refresh = false): Promise<SupplierSearchState> {
  if (!validSupplierSearchRequest(request) || typeof refresh !== "boolean") return { error: "Позиция поиска некорректна." };
  try { return { result: await prepareIndexedSupplierSearch(request, refresh) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 409
      ? "Источник изменился, поиск уже выполняется или ещё действует интервал обновления. Откройте сохранённый поиск либо повторите позже."
      : `Поиск поставщиков не завершён (HTTP ${error.status}).` };
    return { error: "Не удалось завершить поиск. Откройте сохранённую попытку или повторите позже." };
  }
}
export async function loadSupplierSearch(request: SupplierSearchRequest): Promise<SupplierSearchState> {
  if (!validSupplierSearchRequest(request)) return { error: "Позиция поиска некорректна." };
  try { return { result: await readIndexedSupplierSearch(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённого поиска этой позиции пока нет. Нажмите «Найти поставщиков»."
      : `Сохранённый поиск недоступен (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённый поиск." };
  }
}

export async function savePositionAssociation(request: AssociationRequest): Promise<AssociationState> {
  if (!validAssociationRequest(request)) return { error: "Выберите одну позицию и до 10 непересекающихся фрагментов, всего до 16000 символов." };
  try { return { result: await requestIndexedPositionAssociation(request, true) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Связь не сохранена: проверьте версию карточки, документ и выбранные фрагменты (HTTP ${error.status}).` };
    return { error: "Не удалось сохранить связь фрагментов. Повторите позже." };
  }
}
export async function loadPositionAssociation(request: AssociationRequest): Promise<AssociationState> {
  if (!validAssociationRequest(request)) return { error: "Выбор позиции и фрагментов некорректен." };
  try { return { result: await requestIndexedPositionAssociation(request, false) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404 ? "Для этого точного выбора связь ещё не сохранена."
      : `Связь недоступна: проверьте актуальность источников (HTTP ${error.status}).` };
    return { error: "Не удалось открыть сохранённую связь." };
  }
}
export async function listPositionAssociations(request: AssociationListRequest): Promise<AssociationListState> {
  if (!validAssociationListRequest(request)) return { error: "Выберите точную позицию и документ. Размер страницы: 1–20 связей." };
  try { return { result: await listIndexedPositionAssociations(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: `Список связей недоступен: проверьте актуальность источников (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённые связи." };
  }
}
export async function loadPositionAssociationDetail(request: AssociationDetailRequest): Promise<AssociationState> {
  if (!validAssociationDetailRequest(request)) return { error: "Выберите сохранённую связь этой позиции и документа." };
  try { return { result: await readIndexedPositionAssociationDetail(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404 ? "Связь не найдена для этой позиции и документа."
      : `Связь недоступна: проверьте актуальность источников (HTTP ${error.status}).` };
    return { error: "Не удалось восстановить сохранённую связь." };
  }
}

export async function prepareSupplierSerp(request: SupplierSearchRequest, refresh = false): Promise<SupplierSerpState> {
  if (!validSupplierSearchRequest(request) || typeof refresh !== "boolean") return { error: "Позиция поиска некорректна." };
  try { return { result: await prepareIndexedSupplierSerp(request, refresh) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 409
      ? "Источник изменился, поиск уже выполняется или ещё действует интервал обновления. Откройте сохранённый поиск либо повторите позже."
      : `Поиск поставщиков не завершён (HTTP ${error.status}).` };
    return { error: "Не удалось завершить поиск. Откройте сохранённую попытку или повторите позже." };
  }
}
export async function loadSupplierSerp(request: SupplierSearchRequest): Promise<SupplierSerpState> {
  if (!validSupplierSearchRequest(request)) return { error: "Позиция поиска некорректна." };
  try { return { result: await readIndexedSupplierSerp(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённого поиска этой позиции пока нет. Нажмите «Искать в интернете»."
      : `Сохранённый поиск недоступен (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённый поиск." };
  }
}


export async function prepareSupplierPage(request: SupplierPageRequest, refresh = false): Promise<SupplierPageState> {
  if (!validSupplierPageRequest(request) || typeof refresh !== "boolean") return { error: "Выбор сайта некорректен." };
  try { return { result: await prepareIndexedSupplierPage(request, refresh) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 409
      ? "Источник изменился, поиск уже выполняется или ещё действует интервал обновления. Откройте сохранённый поиск либо повторите позже."
      : `Чтение сайта не завершено (HTTP ${error.status}).` };
    return { error: "Не удалось завершить поиск. Откройте сохранённую попытку или повторите позже." };
  }
}
export async function loadSupplierPage(request: SupplierPageRequest): Promise<SupplierPageState> {
  if (!validSupplierPageRequest(request)) return { error: "Выбор сайта некорректен." };
  try { return { result: await readIndexedSupplierPage(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённого поиска этой позиции пока нет. Нажмите «Проверить сайт и цены»."
      : `Сохранённый поиск недоступен (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённый поиск." };
  }
}


export async function prepareSupplierCatalog(request: SupplierCatalogRequest, refresh = false): Promise<SupplierCatalogState> {
  if (!validSupplierCatalogRequest(request) || typeof refresh !== "boolean") return { error: "Выбор товарной карточки некорректен." };
  try { return { result: await prepareIndexedSupplierCatalog(request, refresh) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 409
      ? "Источник изменился, поиск уже выполняется или ещё действует интервал обновления. Откройте сохранённый поиск либо повторите позже."
      : error.status === 422 ? "На этом сайте нет поддержанной формы поиска или выбранная карточка недоступна. Сохранённый поиск можно открыть отдельно." : `Чтение каталога не завершено (HTTP ${error.status}).` };
    return { error: "Не удалось завершить поиск. Откройте сохранённую попытку или повторите позже." };
  }
}
export async function loadSupplierCatalog(request: SupplierCatalogRequest): Promise<SupplierCatalogState> {
  if (!validSupplierCatalogRequest(request)) return { error: "Выбор товарной карточки некорректен." };
  try { return { result: await readIndexedSupplierCatalog(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённого поиска этой позиции пока нет. Нажмите «Найти товары на этом сайте» или «Проверить товар и цену»."
      : `Сохранённый поиск недоступен (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённый поиск." };
  }
}


export async function prepareSupplierProduct(request: SupplierProductRequest): Promise<SupplierProductState> {
  if (!validSupplierProductRequest(request)) return { error: "Выбор товарной карточки некорректен." };
  try { return { result: await prepareIndexedSupplierProduct(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 409
      ? "Позиция изменилась, требует проверки или разбор уже выполняется. Откройте актуальную позицию либо повторите позже."
      : error.status === 422 ? "Сохранённый товар или его источник не прошёл проверку целостности." : `Сопоставление не завершено (HTTP ${error.status}).` };
    return { error: "Не удалось завершить поиск. Откройте сохранённую попытку или повторите позже." };
  }
}
export async function loadSupplierProduct(request: SupplierProductRequest): Promise<SupplierProductState> {
  if (!validSupplierProductRequest(request)) return { error: "Выбор товарной карточки некорректен." };
  try { return { result: await readIndexedSupplierProduct(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённого поиска этой позиции пока нет. Нажмите «Сопоставить условия и характеристики»."
      : `Сохранённый поиск недоступен (HTTP ${error.status}).` };
    return { error: "Не удалось прочитать сохранённый поиск." };
  }
}

export async function loadRequirementPreview(request: RequirementPreviewRequest): Promise<RequirementPreviewState> {
  if (!validRequirementPreviewRequest(request)) return { error: "Выбор документа и товара некорректен." };
  try { return { result: await readIndexedRequirementPreview(request) }; }
  catch (error) {
    if (error instanceof ConfigurationError) return { error: "Доступ к API не настроен." };
    if (error instanceof ApiError) return { error: error.status === 404
      ? "Сохранённый разбор документа или товара не найден. Сначала откройте и разберите полученный DOCX."
      : error.status === 409 ? "Источник изменился или требует проверки. Откройте актуальную карточку."
      : error.status === 422 ? "Таблица не подходит для этого просмотра, неполна или неоднозначна. Проверьте номер таблицы и исходный документ."
      : `Не удалось открыть таблицу (HTTP ${error.status}).` };
    return { error: "Не удалось открыть таблицу характеристик." };
  }
}

function requirementReviewError(error: unknown): string {
  if (error instanceof ConfigurationError) return "Доступ к API не настроен.";
  if (error instanceof ApiError) return error.status === 403 ? "Нужна роль независимого проверяющего. Автор предложения не может одобрить его сам."
    : error.status === 404 ? "Предложение или независимое решение ещё не найдено."
    : error.status === 409 ? "Источник или решение изменилось. Откройте актуальные данные; прежнее подтверждение не переносится."
    : error.status === 413 ? "Предложение слишком большое. Сократите пояснение."
    : `Проверка недоступна (HTTP ${error.status}).`;
  return "Не удалось выполнить проверку выбранной таблицы.";
}
export async function prepareRequirementProposal(request: ProposalRequest): Promise<RequirementReviewState<SavedRequirementProposal>> {
  if (!validProposalRequest(request)) return {error:"Предложение некорректно."};
  try { return {result:await createIndexedRequirementProposal(request)}; } catch (error) { return {error:requirementReviewError(error)}; }
}
export async function loadRequirementProposal(id: string): Promise<RequirementReviewState<SavedRequirementProposal>> {
  if (!validReviewId(id)) return {error:"ID предложения некорректен."};
  try { return {result:await readIndexedRequirementProposal(id)}; } catch (error) { return {error:requirementReviewError(error)}; }
}
export async function reviewRequirementProposal(request: DecisionRequest, proposal: RequirementProposal): Promise<RequirementReviewState<SavedRequirementDecision>> {
  if (!validDecisionRequest(request) || !proposalMatches(proposal)) return {error:"Решение некорректно."};
  try { return {result:await createIndexedRequirementDecision(request,proposal)}; } catch (error) { return {error:requirementReviewError(error)}; }
}
export async function loadRequirementComparison(proposal: RequirementProposal): Promise<RequirementReviewState<RequirementComparison>> {
  if (!proposalMatches(proposal)) return {error:"Предложение некорректно."};
  try { return {result:await readIndexedRequirementComparison(proposal)}; } catch (error) { return {error:requirementReviewError(error)}; }
}

