"use server";
import { readIndexedPublicUnitPrice } from "@/lib/procurement-api";
import { validSupplierProductRequest, type SupplierProductRequest } from "@/lib/eis-supplier-product";
import { publicUnitPriceMatches, type PublicUnitPriceReport } from "@/lib/public-unit-price";
export async function loadPublicUnitPrice(request: SupplierProductRequest, sha: string): Promise<{ report?: PublicUnitPriceReport; error?: string }> {
  if (!validSupplierProductRequest(request) || !/^[a-f0-9]{64}$/.test(sha)) return { error: "Выберите сохранённую карточку товара заново." };
  try {
    const report = await readIndexedPublicUnitPrice(request);
    return publicUnitPriceMatches(report, request, sha) ? { report } : { error: "Источник цены изменился. Откройте карточку заново." };
  } catch { return { error: "Не удалось прочитать источник цены. Проверьте доступ и актуальность карточки." }; }
}
