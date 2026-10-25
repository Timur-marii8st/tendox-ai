import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-product.json";
import { validSupplierProductRequest } from "../src/lib/eis-supplier-product";
import { publicUnitPriceMatches, type PublicUnitPriceReport } from "../src/lib/public-unit-price";
import { PublicPriceView } from "../src/app/tender-discovery/public-price-view";
const raw: unknown = fixture.report.request; assert.ok(validSupplierProductRequest(raw));
const request = raw;
const xml = request.catalog.page.position.selection.notice.notice_xml_sha256;
const sha = fixture.report.source_body_sha256;
const provenance = (document_id: string) => ({ document_id, locator: "/synthetic/source" });
function report(): PublicUnitPriceReport {
  return { policy: "saved-public-unit-price-v1", company_id: "alpha", request,
    checked_at: "2026-10-21T12:00:00Z", position_sha256: "c".repeat(64), source_sha256: sha,
    price: { company_id: "alpha", notice_xml_sha256: xml, source_sha256: sha,
      line_id: String(request.catalog.page.position.selection.source_index),
      source_url: "https://supplier.example.com/product", observed_at: "2026-10-21T12:00:00Z",
      price: { value: "40", provenance: provenance(sha) },
      quantity_per_price: { value: "1", provenance: provenance(sha) },
      unit: { code: "piece", provenance: provenance(sha) }, currency: "RUB", amount_basis: "EX_VAT",
      currency_provenance: provenance(sha), amount_basis_provenance: provenance(sha) },
    required_quantity: { value: "10", provenance: provenance(xml) }, required_unit: "шт",
    required_unit_provenance: provenance(xml), quantity_cost_rub: "400.00", status: "CALCULATED",
    missing: [], profit: "UNKNOWN", technical: "UNKNOWN", quote: "UNKNOWN", source_requests: 0 };
}
test("automatic cost response binds request, HTML, line and source facts", () => {
  assert.ok(publicUnitPriceMatches(report(), request, sha));
  for (const alter of [
    (r: PublicUnitPriceReport) => { r.source_sha256 = "f".repeat(64); },
    (r: PublicUnitPriceReport) => { r.price!.company_id = "beta"; },
    (r: PublicUnitPriceReport) => { r.price!.line_id = "99"; },
    (r: PublicUnitPriceReport) => { r.price!.price.provenance.document_id = "f".repeat(64); },
    (r: PublicUnitPriceReport) => { r.price!.amount_basis_provenance.document_id = "f".repeat(64); },
    (r: PublicUnitPriceReport) => { r.quantity_cost_rub = "NaN"; },
    (r: PublicUnitPriceReport) => { r.missing = ["REQUIRED_QUANTITY_UNKNOWN"]; },
  ]) { const r = report(); alter(r); assert.equal(publicUnitPriceMatches(r, request, sha), false); }
});
test("calculated goods cost does not become lot profit or participation", () => {
  const html = renderToStaticMarkup(<PublicPriceView report={report()} />);
  for (const text of ["400,00 ₽", "без НДС", "не полная стоимость закупки", "Прибыль и маржа: UNKNOWN", "не является действующим КП"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("unknown source has no invented zero cost or score", () => {
  const r: PublicUnitPriceReport = { ...report(), price: null, quantity_cost_rub: null,
    status: "UNKNOWN", missing: ["EXPLICIT_PRICE_BASIS_UNAVAILABLE"] };
  assert.ok(publicUnitPriceMatches(r, request, sha));
  const html = renderToStaticMarkup(<PublicPriceView report={r} />);
  assert.ok(html.includes("Стоимость на объём пока не подтверждена"));
  assert.ok(!html.includes("0 ₽"));
});
test("untrusted unit labels remain text", () => {
  const r = report(); r.required_unit = "<script>unsafe</script>";
  const html = renderToStaticMarkup(<PublicPriceView report={r} />);
  assert.ok(html.includes("&lt;script&gt;unsafe&lt;/script&gt;"));
});
