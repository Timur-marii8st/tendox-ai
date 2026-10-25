import type { SupplierProductRequest } from "./eis-supplier-product";
import { validSupplierProductRequest, supplierProductRequestKey } from "./eis-supplier-product";

type Fact = { value: string; provenance: { document_id: string; locator: string } };
export type PublicUnitPriceReport = {
  policy: "saved-public-unit-price-v1"; company_id: string; request: SupplierProductRequest;
  checked_at: string; position_sha256: string; source_sha256: string;
  price: null | { company_id: string; notice_xml_sha256: string; source_sha256: string;
    line_id: string; source_url: string; observed_at: string; price: Fact;
    quantity_per_price: Fact; unit: { code: string; provenance: Fact["provenance"] };
    currency: "RUB"; amount_basis: "EX_VAT" | "GROSS";
    currency_provenance: Fact["provenance"]; amount_basis_provenance: Fact["provenance"] };
  required_quantity: Fact | null; required_unit: string | null;
  required_unit_provenance: Fact["provenance"]; quantity_cost_rub: string | null;
  status: "CALCULATED" | "UNKNOWN"; missing: string[];
  profit: "UNKNOWN"; technical: "UNKNOWN"; quote: "UNKNOWN"; source_requests: 0;
};
export function publicUnitPriceMatches(report: PublicUnitPriceReport, request: SupplierProductRequest, sha: string): boolean {
  const ref = request.catalog.page.position.selection;
  const source = (p: Fact["provenance"] | undefined, digest: string) => !!p && p.document_id === digest && typeof p.locator === "string" && p.locator.length > 0;
  const money = (value: unknown) => typeof value === "string" && /^\d{1,19}(?:\.\d{1,6})?$/.test(value);
  if (!report || report.policy !== "saved-public-unit-price-v1" || typeof report.company_id !== "string" || !report.company_id ||
      !validSupplierProductRequest(report.request) ||
      supplierProductRequestKey(report.request) !== supplierProductRequestKey(request) ||
      report.source_sha256 !== sha || !/^[a-f0-9]{64}$/.test(report.position_sha256) ||
      !Array.isArray(report.missing) || report.missing.some(x => typeof x !== "string") ||
      report.profit !== "UNKNOWN" || report.technical !== "UNKNOWN" || report.quote !== "UNKNOWN" ||
      report.source_requests !== 0 || !source(report.required_unit_provenance, ref.notice.notice_xml_sha256)) return false;
  if (report.required_quantity && (!money(report.required_quantity.value) || !source(report.required_quantity.provenance, ref.notice.notice_xml_sha256))) return false;
  const p = report.price;
  if (p && (p.company_id !== report.company_id || p.notice_xml_sha256 !== ref.notice.notice_xml_sha256 ||
      p.line_id !== String(ref.source_index) || p.source_sha256 !== sha || p.currency !== "RUB" ||
      !["EX_VAT", "GROSS"].includes(p.amount_basis) || !money(p.price?.value) || !money(p.quantity_per_price?.value) ||
      ![p.price?.provenance, p.quantity_per_price?.provenance, p.unit?.provenance,
        p.currency_provenance, p.amount_basis_provenance].every(item => source(item, sha)))) return false;
  if (report.status === "CALCULATED") return !!p && !!report.required_quantity && money(report.quantity_cost_rub) && report.missing.length === 0;
  return report.status === "UNKNOWN" && report.quantity_cost_rub === null && report.missing.length > 0;
}
