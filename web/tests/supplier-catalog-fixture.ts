import assert from "node:assert/strict";
import fixture from "./fixtures/eis-supplier-catalog.json";
import { supplierCatalogMatches, validSupplierCatalogRequest, type SavedSupplierCatalog, type SupplierCatalogRequest } from "../src/lib/eis-supplier-catalog";
const rawRequest: unknown = fixture.report.request; assert.ok(validSupplierCatalogRequest(rawRequest)); const request: SupplierCatalogRequest = rawRequest;
export function searchFixture(): SavedSupplierCatalog {
  const product: unknown = structuredClone(fixture); assert.ok(supplierCatalogMatches(product, request));
  const spec = { source_url: "https://bumaga-s.ru/", query: "Бумага для офисной техники", raw_action: "/categories/search", field: "q" as const,
    search_url: "https://bumaga-s.ru/categories/search?q=" + encodeURIComponent("Бумага для офисной техники"), html_sha256: "a".repeat(64), locator: "form[1]" };
  const observation = { ...product.report.observation!, source_url: spec.search_url, final_url: spec.search_url,
    hops: [{ url: spec.search_url, http_status: 200, location: null }], extraction_status: "EMPTY" as const, page_kind: "UNKNOWN" as const, products: [], html_sha256: "f".repeat(64), byte_count: 1000 };
  return { ...product, report: { ...product.report, request: { ...request, search_run_id: null, product_index: null }, stage: "SEARCH", search_spec: spec,
    selected_link: null, parent_search_report_sha256: null, observation, source_body_sha256: observation.html_sha256, source_body_byte_count: observation.byte_count,
    links: { revision: "bumaga-s-v1", source_url: spec.search_url, html_sha256: observation.html_sha256,
      status: "FOUND", links: [product.report.selected_link!], scanned_count: 20, returned_count: 1, truncated: true, coverage: "UNKNOWN" } } };
}
