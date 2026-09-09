import "server-only";

export type RecommendationDecision =
  | "participate"
  | "needs_analysis"
  | "do_not_participate";

export type Provenance = {
  document_id: string;
  locator: string;
  extractor?: string | null;
  confidence?: number | null;
};

export type GateCheck = {
  kind: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  evidence: Provenance[];
};

export type EconomicsScenario = {
  kind: "base" | "realistic" | "conservative";
  assumptions: string[];
  economics: {
    contract_revenue: string;
    nds_rate?: string | null;
    costs: {
      specified_cost_fields?: string[];
      [key: string]: string | string[] | null | undefined;
    };
  };
};

export type ProcurementCase = {
  case_id: string;
  version: number;
  nmck_ex_vat: string;
  nmck_source: Provenance;
  selected_quote?: {
    quote_id: string;
    supplier_id: string;
    amount_ex_vat: string;
    valid_until: string;
    source: Provenance;
  } | null;
  assessment?: { checks: GateCheck[] } | null;
  scenarios?: { scenarios: EconomicsScenario[] } | null;
  tender: {
    tender_id: string;
    customer_name: string;
    subject: string;
    law: string;
    method: string;
    stage: string;
    notice_provenance: Provenance;
    submission?: { closes_at?: string; timezone?: string } | null;
    delivery?: {
      addresses?: Array<{ region?: string; city?: string; address?: string }>;
    } | null;
  };
  rating?: {
    score?: number;
    factors?: Array<{
      name: string;
      points: number;
      explanation: string;
      change_hint?: string | null;
    }>;
  } | null;
};

export type EvaluationRecord = {
  evaluation_id: string;
  audit_event_id: string;
  effective_at: string;
  engine_version: string;
  input_digest: string;
  recommendation: {
    decision: RecommendationDecision;
    reasons: string[];
    realistic_profit?: string | null;
    realistic_margin?: string | null;
    minimum_bid_price?: string | null;
    generated_at: string;
  };
};

export type CaseCardData = {
  case: ProcurementCase;
  evaluation: EvaluationRecord | null;
};

export type DashboardData = {
  cases: CaseCardData[];
  error?: "api" | "configuration";
};

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`API error: ${status}`);
  }
}

export class ConfigurationError extends Error {}

function configuration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_API_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Procurement API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = configuration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return (await response.json()) as T;
}

export async function loadDashboard(): Promise<DashboardData> {
  try {
    const page = await request<{ items: ProcurementCase[] }>("/v1/cases?limit=100");
    const cases = await Promise.all(
      page.items.map(async (item): Promise<CaseCardData> => {
        try {
          const path = `/v1/cases/${encodeURIComponent(item.case_id)}/versions/${item.version}/evaluations/latest`;
          return { case: item, evaluation: await request<EvaluationRecord>(path) };
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            return { case: item, evaluation: null };
          }
          throw error;
        }
      }),
    );
    return { cases };
  } catch (error) {
    return {
      cases: [],
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

function idempotencyKey(): string {
  return crypto.randomUUID();
}

export function createCase(payload: unknown): Promise<ProcurementCase> {
  return request("/v1/cases", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(payload),
  });
}

export function createEvaluation(
  caseId: string,
  version: string,
  effectiveAt: string,
): Promise<EvaluationRecord> {
  const path = `/v1/cases/${encodeURIComponent(caseId)}/versions/${encodeURIComponent(version)}/evaluations`;
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify({ effective_at: effectiveAt }),
  });
}
