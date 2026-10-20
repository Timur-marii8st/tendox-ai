import "server-only";

import type { EisPublicLead } from "./procurement-api";

export type DiscoveryRunSummary = {
  id: string;
  query: string;
  state: "RUNNING" | "COMPLETED" | "CANCELLED";
  completion_status?: "IN_PROGRESS" | "PARTIAL" | "FAILED" | "CANCELLED";
  created_at: string;
};

export type DiscoveryCostInput = {
  goods: string;
  expenses: string;
  vat_rate: string;
  realistic_discount: string;
  conservative_discount: string;
  conservative_cost_growth: string;
  basis: string;
  costs_complete_ack: boolean;
};

export type DiscoveryScenario = {
  kind: "base" | "realistic" | "conservative";
  revenue_net: string;
  costs_net: string;
  profit: string;
  margin: string;
  assumptions: string[];
  break_even_gross: string;
  maximum_discount: string;
  basis: string;
};

export type DiscoveryEstimate = {
  status: "ESTIMATE" | "UNKNOWN" | "BLOCKED";
  recommendation: "needs_analysis" | "do_not_participate";
  scenarios: DiscoveryScenario[];
  reasons: string[];
  basis: string;
};

export type DocumentAnalysis = {
  filename: string;
  url: string;
  sha256: string;
  byte_count: number;
  status: "PASS" | "UNKNOWN" | "FAIL";
  document_role: "UNKNOWN";
  reasons: string[];
  blocks_total: number;
  unmapped_count: number;
  requirement_candidates: Array<{
    property: string;
    operator: string;
    value: string;
    unit: string;
    raw_text: string;
    provenance: { document_id: string; locator: string };
  }>;
  snippets: Array<{
    kind: string;
    text: string;
    provenance: { document_id: string; locator: string };
  }>;
  members: string[];
};

export type DiscoveryCandidate = {
  lead: EisPublicLead;
  detail: null | {
    detail_url: string;
    status: string;
    exact_deadline: string | null;
    customer: null | {
      name: string;
      organization_code: string;
      profile_url: string;
      source_locator: string;
      source_sha256: string;
    };
    fields: Array<{
      name: string;
      label: string;
      value: string;
      source_locator: string;
      evidence_snippet: string;
    }>;
    source_sha256: string;
  };
  customer_profile: null | {
    profile_url: string;
    organization_code: string;
    status: string;
    observed_at: string;
    source_sha256: string | null;
    inn: string | null;
    inn_locator: string | null;
    contracts_url: string | null;
    contracts_locator: string | null;
    reason: string | null;
  };
  customer_contracts: null | {
    search_url: string;
    status: string;
    observed_at: string;
    source_sha256: string | null;
    product_query: string | null;
    coverage: "FIRST_PAGE_ONLY";
    scanned_count: number;
    skipped_count: number;
    contracts: Array<{
      registry_number: string;
      subject: string | null;
      price_rub: string | null;
      signed_on: string | null;
      contract_url: string;
      notice_number: string | null;
      notice_url: string | null;
      notice_locator: string | null;
      relevance_status: "MATCHED_VISIBLE" | "UNKNOWN";
      matched_terms: string[];
      source_locator: string;
      source_sha256: string;
    }>;
    reason: string | null;
  };
  customer_history_requested: boolean;
  documents: DocumentAnalysis[];
  warnings: string[];
  analysis_status: "PENDING" | "COMPLETE" | "PARTIAL";
  application_status: "UNKNOWN" | "FAIL";
  costs: DiscoveryCostInput | null;
  estimate: DiscoveryEstimate | null;
};

export type DiscoveryRun = {
  id: string;
  request: { query: string; max_pages: number; max_candidates: number; max_documents: number; search_page_size: 50 | 100 };
  state: "RUNNING" | "COMPLETED" | "CANCELLED";
  completion_status: "IN_PROGRESS" | "PARTIAL" | "FAILED" | "CANCELLED";
  created_at: string;
  updated_at: string;
  next_retry_at: string | null;
  pages_read: number;
  scanned_count: number;
  unique_scanned_count: number | null;
  identified_count: number;
  duplicate_count: number;
  unparsed_count: number;
  search_stop_reason: "REPEATED_PAGE" | "NO_NEW_IDENTIFIERS" | "IDENTIFIERS_INCOMPLETE" | "LEGACY_STATE_UNVERIFIED" | "PAGE_LIMIT" | "SOURCE_END_HINT" | "SOURCE_ERROR" | null;
  search_pages: {
    page_number: number; page_size: 50 | 100; search_url: string; observed_at: string;
    source_sha256: string | null; scanned_count: number | null; unparsed_count: number;
    unidentified_count: number | null; purchase_numbers: string[];
    fingerprint: string | null; identifiers_complete: boolean;
  }[];
  warnings: string[];
  pending_count: number;
  candidates: DiscoveryCandidate[];
};

export class WorkflowApiError extends Error {
  constructor(readonly status: number) {
    super(`API error: ${status}`);
  }
}

export class WorkflowConfigurationError extends Error {}

function configuration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_API_TOKEN: token } = process.env;
  if (!url || !token) throw new WorkflowConfigurationError("Procurement API is not configured");
  return { baseUrl: url.replace(/\/$/, ""), token };
}

async function request<T>(path: string, init: RequestInit = {}, timeout = 10_000): Promise<T> {
  const { baseUrl, token } = configuration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(timeout),
  });
  if (!response.ok) throw new WorkflowApiError(response.status);
  return (await response.json()) as T;
}

const runPath = (runId: string, suffix = "") => {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(runId)) throw new WorkflowApiError(400);
  return `/v1/tender-discovery/runs/${encodeURIComponent(runId)}${suffix}`;
};

export function listDiscoveryRuns(): Promise<DiscoveryRunSummary[]> {
  return request("/v1/tender-discovery/runs");
}

export function createDiscoveryRun(input: DiscoveryRun["request"]): Promise<DiscoveryRun> {
  return request("/v1/tender-discovery/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getDiscoveryRun(runId: string): Promise<DiscoveryRun> {
  return request(runPath(runId));
}

export function advanceDiscoveryRun(runId: string): Promise<DiscoveryRun> {
  return request(runPath(runId, "/advance"), { method: "POST" }, 70_000);
}

export function cancelDiscoveryRun(runId: string): Promise<DiscoveryRun> {
  return request(runPath(runId, "/cancel"), { method: "POST" });
}

export function analyzeDiscoveryCandidate(
  runId: string,
  purchaseNumber: string,
): Promise<DiscoveryRun> {
  if (!/^[A-Za-z0-9-]{1,80}$/.test(purchaseNumber)) throw new WorkflowApiError(400);
  return request(`${runPath(runId, "/analyze")}/${encodeURIComponent(purchaseNumber)}`, {
    method: "POST",
  });
}

export function requestDiscoveryCustomerHistory(
  runId: string,
  purchaseNumber: string,
): Promise<DiscoveryRun> {
  if (!/^[A-Za-z0-9-]{1,80}$/.test(purchaseNumber)) throw new WorkflowApiError(400);
  return request(`${runPath(runId, "/customer-history")}/${encodeURIComponent(purchaseNumber)}`, {
    method: "POST",
  });
}

export function updateDiscoveryCosts(
  runId: string,
  purchaseNumber: string,
  input: DiscoveryCostInput,
): Promise<DiscoveryRun> {
  if (!/^[A-Za-z0-9-]{1,80}$/.test(purchaseNumber)) throw new WorkflowApiError(400);
  return request(`${runPath(runId, "/costs")}/${encodeURIComponent(purchaseNumber)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export type DiscoveryArtifact = {
  bytes: ArrayBuffer;
  disposition: string;
};

function safeArtifactDisposition(value: string | null, digest: string): string {
  if (value) {
    const match = /^attachment;\s*filename="?([A-Za-z0-9][A-Za-z0-9._ -]{0,150})"?$/i.exec(value);
    if (match && !match[1].includes("..")) return `attachment; filename="${match[1]}"`;
  }
  return `attachment; filename="eis-artifact-${digest.slice(0, 12)}.bin"`;
}

export async function downloadDiscoveryArtifact(
  runId: string,
  digest: string,
): Promise<DiscoveryArtifact> {
  if (!/^[0-9a-f]{64}$/.test(digest)) throw new WorkflowApiError(400);
  const { baseUrl, token } = configuration();
  const response = await fetch(
    `${baseUrl}${runPath(runId, "/artifacts")}/${encodeURIComponent(digest)}`,
    {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(30_000),
    },
  );
  if (!response.ok) throw new WorkflowApiError(response.status);
  const disposition = safeArtifactDisposition(response.headers.get("content-disposition"), digest);
  return { bytes: await response.arrayBuffer(), disposition };
}
