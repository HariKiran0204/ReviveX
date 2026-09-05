import { apiRequest, qs } from "./api/client";
import type {
  ApprovalItem,
  CaseDetail,
  CommandCenterMetrics,
  DecisionView,
  DemoResult,
  EvaluationLatest,
  BatchEvaluationResponse,
  HealthResponse,
  Paginated,
  CaseListItem,
  PolicyResponse,
  PolicySettings,
  ReadyResponse,
  SystemHealth,
  AuditItem,
  AgentRunItem,
  ToolCallItem,
} from "./api/types";

export { getApiBaseUrl } from "./api/client";
export type { HealthResponse, ReadyResponse, PolicySettings, BatchEvaluationResponse };

export async function fetchHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health");
}

export async function fetchReady(): Promise<ReadyResponse> {
  return apiRequest<ReadyResponse>("/ready");
}

export async function fetchCommandCenter(): Promise<CommandCenterMetrics> {
  return apiRequest<CommandCenterMetrics>("/v1/metrics/command-center");
}

export async function fetchCases(params: {
  page?: number;
  page_size?: number;
  status?: string;
  case_type?: string;
  min_amount?: string;
  max_amount?: string;
  sort?: string;
  direction?: string;
}): Promise<Paginated<CaseListItem>> {
  return apiRequest(`/v1/recovery-cases${qs(params)}`);
}

export async function fetchCase(id: string): Promise<CaseDetail> {
  return apiRequest(`/v1/recovery-cases/${id}`);
}

export async function fetchCaseDecision(id: string): Promise<DecisionView> {
  return apiRequest(`/v1/recovery-cases/${id}/decision`);
}

export async function fetchCaseTimeline(
  id: string,
  since?: string | null,
): Promise<{ items: AuditItem[]; cursor: string | null; case_id: string }> {
  return apiRequest(`/v1/recovery-cases/${id}/timeline${qs({ since })}`);
}

export async function fetchAgentRuns(id: string): Promise<{ items: AgentRunItem[] }> {
  return apiRequest(`/v1/recovery-cases/${id}/agent-runs`);
}

export async function fetchToolCalls(id: string): Promise<{ items: ToolCallItem[] }> {
  return apiRequest(`/v1/recovery-cases/${id}/tool-calls`);
}

export async function fetchApprovals(params: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<Paginated<ApprovalItem>> {
  return apiRequest(`/v1/approvals${qs(params)}`);
}

export async function decideApproval(
  approvalId: string,
  action: "approve" | "reject" | "cancel",
  reason?: string,
): Promise<unknown> {
  return apiRequest(`/v1/approvals/${approvalId}/${action}`, {
    method: "POST",
    body: JSON.stringify({ actor_id: "demo-operator", reason: reason ?? null }),
  });
}

export async function fetchAudit(params: {
  page?: number;
  page_size?: number;
  case_id?: string;
  event_type?: string;
  actor_id?: string;
  since?: string;
  until?: string;
}): Promise<Paginated<AuditItem>> {
  return apiRequest(`/v1/audit-events${qs(params)}`);
}

export async function fetchPolicy(): Promise<PolicyResponse> {
  return apiRequest("/v1/policy");
}

export async function updatePolicy(policy: PolicySettings): Promise<PolicyResponse> {
  return apiRequest("/v1/policy", {
    method: "PATCH",
    body: JSON.stringify({ policy }),
  });
}

export async function fetchEvaluation(): Promise<EvaluationLatest> {
  return apiRequest("/v1/evaluation/latest");
}

export async function fetchBatchEvaluation(params?: {
  cases?: number;
  seed?: number;
  revivex_mode?: string;
}): Promise<BatchEvaluationResponse> {
  return apiRequest(`/v1/evaluation/batch${qs(params || {})}`);
}

export async function fetchSystemHealth(): Promise<SystemHealth> {
  return apiRequest("/v1/system-health");
}

export async function runDemo(kind: string): Promise<DemoResult> {
  return apiRequest("/v1/operator/demo", {
    method: "POST",
    body: JSON.stringify({ kind }),
  });
}
