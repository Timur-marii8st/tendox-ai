"use client";
import { useEffect, useState } from "react";
import { supplierProductRequestKey, type SupplierProductRequest } from "@/lib/eis-supplier-product";
import type { PublicUnitPriceReport } from "@/lib/public-unit-price";
import { loadPublicUnitPrice } from "./public-price-actions";
import { PublicPriceView } from "./public-price-view";
export function PublicUnitPrice({ request, expectedSha }: { request: SupplierProductRequest; expectedSha: string }) {
  const [state, setState] = useState<{ key: string; report?: PublicUnitPriceReport; error?: string }>();
  const key = supplierProductRequestKey(request) + expectedSha;
  useEffect(() => {
    let active = true;
    loadPublicUnitPrice(request, expectedSha).then(value => { if (active) setState({ key, ...value }); })
      .catch(() => { if (active) setState({ key, error: "Источник цены временно недоступен." }); });
    return () => { active = false; };
  }, [request, expectedSha, key]);
  return <div key={key}>
    {(!state || state.key !== key) && <p role="status">Проверяем единицу цены и количество заказчика…</p>}
    {state?.key === key && state.error && <p role="alert">{state.error}</p>}
    {state?.key === key && state.report && <PublicPriceView report={state.report} />}
  </div>;
}
