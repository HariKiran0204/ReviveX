export type HealthResponse = {
  status: string;
  service: string;
};

export type ReadyChecks = {
  application: string;
  database: string;
  redis: string;
};

export type ReadyResponse = {
  status: "ready" | "not_ready" | string;
  checks: ReadyChecks;
  error?: {
    code: string;
    message: string;
    request_id: string | null;
  } | null;
};

export type HealthSnapshot =
  | { state: "loading" }
  | {
      state: "healthy" | "unhealthy" | "error";
      health: HealthResponse | null;
      ready: ReadyResponse | null;
      message: string;
    };

export type CustomerSummary = {
  id?: string | null;
  full_name: string | null;
  email: string | null;
  external_id?: string | null;
  phone?: string | null;
  lifetime_value?: string | null;
};

export type CaseListItem = {
  id: string;
  merchant_id: string;
  customer: CustomerSummary;
  amount_at_risk: string | null;
  amount_recovered: string | null;
  currency: string;
  case_type: string;
  failure_reason: string | null;
  status: string;
  recovery_probability: string | null;
  recommended_action: string | null;
  expected_recovery: string | null;
  created_at: string | null;
  opened_at: string | null;
  closed_at: string | null;
};

export type Paginated<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  merchant_id?: string;
};

export type CommandCenterMetrics = {
  merchant: { id: string; name: string; slug: string } | null;
  partial: boolean;
  revenue_at_risk: string | null;
  revenue_recovered: string | null;
  expected_recovery: string | null;
  recovery_rate: number | null;
  active_cases: number;
  pending_approvals: number;
  failed_actions: number;
  policy_blocks: number;
  currency: string;
  labels: Record<string, string>;
};

export type ApprovalItem = {
  id: string;
  case_id: string;
  action_id: string | null;
  status: string;
  requested_by: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string | null;
  case?: {
    id: string;
    status: string;
    amount_at_risk: string | null;
    currency: string;
  } | null;
  customer?: { full_name: string | null; email: string | null } | null;
  proposed_action?: string | null;
  amount?: string | null;
  risk?: string | null;
  expected_value?: string | null;
  reason?: string | null;
};

export type AuditItem = {
  id: string;
  timestamp: string | null;
  actor_type: string;
  actor_id: string | null;
  event_type: string;
  action: string | null;
  previous_state: string | null;
  new_state: string | null;
  summary: string;
  correlation_id: string | null;
  idempotency_key: string | null;
  case_id: string | null;
};

export type PolicySettings = {
  max_retry_attempts: number;
  max_discount_percent: string;
  max_daily_discount_budget: string;
  high_value_approval_threshold: string;
  medium_value_approval_threshold: string;
  max_communications_per_day: number;
  quiet_hours_start: number;
  quiet_hours_end: number;
  automatic_recovery_enabled: boolean;
  approval_ttl_minutes: number;
  blocked_action_types: string[];
  policy_version?: string;
};

export type PolicyResponse = {
  merchant: { id: string; name: string; slug: string };
  source: string;
  policy: PolicySettings;
  legal_actions: string[];
};

export type BatchSeedSummary = {
  seed: number;
  revenue_at_risk: string;
  baseline_recovered: string;
  revivex_recovered: string;
  incremental_revenue: string;
  recovery_uplift_percent: string;
  baseline_recovery_rate: string;
  revivex_recovery_rate: string;
  baseline_cases_recovered: number;
  revivex_cases_recovered: number;
};

export type BatchEvaluationResponse = {
  n_cases: number;
  seed: number;
  revivex_mode: string;
  ml_prediction_count: number;
  heuristic_fallback_count: number;
  revenue_at_risk: string;
  baseline_recovered: string;
  revivex_recovered: string;
  incremental_revenue: string;
  recovery_uplift_percent: string;
  baseline_recovery_rate: string;
  revivex_recovery_rate: string;
  baseline_cases_recovered: number;
  revivex_cases_recovered: number;
  baseline_net_recovery: string;
  revivex_net_recovery: string;
  multi_seed_results?: BatchSeedSummary[];
};

export type EvaluationLatest = {
  available: boolean;
  synthetic: boolean;
  label: string;
  model_version: string | null;
  dataset_version: string | null;
  algorithm: string | null;
  quality_passed: boolean | null;
  is_production: boolean;
  trained_at: string | null;
  roc_auc: number | null;
  pr_auc: number | null;
  brier: number | null;
  ece: number | null;
  calibration: Record<string, unknown>;
  held_out_metrics: Record<string, unknown>;
  business_sense: Record<string, unknown> | null;
  baseline_vs_optimizer: BatchEvaluationResponse | null;
};

export type SystemHealthCheck = {
  name: string;
  status: string;
  detail: string;
  required?: boolean;
};

export type SystemHealth = {
  status: string;
  checks: SystemHealthCheck[];
  synthetic: boolean;
};

export type DecisionView = {
  case_id: string;
  source: string;
  source_label: string;
  diagnosis: {
    root_cause?: string;
    confidence?: number;
    evidence?: string[];
    recoverability?: string;
  } | null;
  confidence: number | null;
  evidence: string[];
  candidate_actions: unknown[];
  model_probabilities: Array<{
    action: string;
    probability: string;
    source: string;
    model_version: string;
  }>;
  selected_action: string | null;
  expected_values: Record<string, string>;
  policy_result: string | null;
  explanation: string | null;
};

export type CaseDetail = {
  case: CaseListItem;
  customer: CustomerSummary;
  payment: {
    id: string;
    status: string;
    amount: string | null;
    currency: string;
    failure_reason: string | null;
    failure_code: string | null;
    payment_method: string | null;
    provider: string;
    provider_payment_id: string | null;
    provider_order_id: string | null;
    captured_at: string | null;
    failed_at: string | null;
  } | null;
  verification: {
    verified_payment_id: string | null;
    last_mismatch_reason: string | null;
    amount_recovered: string | null;
    amount_at_risk: string | null;
  };
  selected_action: string | null;
  policy_verdict: string | null;
  approval: ApprovalItem | null;
  approvals: ApprovalItem[];
  actions: Array<{
    id: string;
    action_type: string;
    status: string;
    risk_level: string;
    amount: string | null;
    currency: string;
    idempotency_key: string;
    error_code: string | null;
    error_message: string | null;
    executed_at: string | null;
    created_at: string | null;
  }>;
  policy_evaluations: Array<{
    id: string;
    action: string;
    allowed: boolean;
    requires_approval: boolean;
    risk_level: string;
    reason: string | null;
    policy_version: string;
    evaluated_at: string | null;
  }>;
  predictions: Array<{
    action: string;
    probability: string;
    model_version: string;
    source: string;
  }>;
  decision: {
    selected_action: string;
    selected_expected_value: string | null;
    policy_verdict: string | null;
    explanation: string | null;
    candidate_actions: unknown;
    expected_values: Record<string, string>;
  } | null;
};

export type AgentRunItem = {
  id: string;
  agent_name: string;
  agent_version: string;
  status: string;
  source: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  latency_ms: number | null;
};

export type ToolCallItem = {
  id: string;
  tool_name: string;
  tool_version: string;
  status: string;
  idempotency_key: string | null;
  correlation_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string | null;
};

export type DemoResult = {
  kind: string;
  seed?: number;
  cases: Array<{
    id: string;
    status: string;
    amount_at_risk: string;
    amount_recovered: string;
    case_type: string;
  }>;
  acknowledgements: Array<{ event_id: string; status: string; duplicate: boolean }>;
};
