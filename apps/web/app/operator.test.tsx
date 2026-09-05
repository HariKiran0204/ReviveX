import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import CommandCenterPage from "@/app/page";
import CasesPage from "@/app/cases/page";
import ApprovalsPage from "@/app/approvals/page";
import AuditPage from "@/app/audit/page";
import EvaluationPage from "@/app/evaluation/page";
import { CaseDetailScreen } from "@/app/cases/[id]/CaseDetailScreen";
import { validatePolicySettings } from "@/lib/policy";
import type { CaseDetail, CommandCenterMetrics, DecisionView } from "@/lib/api/types";

vi.mock("@/lib/api", () => ({
  fetchCommandCenter: vi.fn(),
  fetchCases: vi.fn(),
  fetchCase: vi.fn(),
  fetchCaseDecision: vi.fn(),
  fetchCaseTimeline: vi.fn(),
  fetchAgentRuns: vi.fn(),
  fetchToolCalls: vi.fn(),
  fetchApprovals: vi.fn(),
  decideApproval: vi.fn(),
  fetchAudit: vi.fn(),
  fetchEvaluation: vi.fn(),
  fetchPolicy: vi.fn(),
  updatePolicy: vi.fn(),
  fetchSystemHealth: vi.fn(),
  runDemo: vi.fn(),
  fetchHealth: vi.fn(),
  fetchReady: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import {
  decideApproval,
  fetchApprovals,
  fetchAudit,
  fetchCase,
  fetchCaseDecision,
  fetchCaseTimeline,
  fetchAgentRuns,
  fetchToolCalls,
  fetchCases,
  fetchCommandCenter,
  fetchEvaluation,
} from "@/lib/api";

const metrics: CommandCenterMetrics = {
  merchant: { id: "m1", name: "Demo", slug: "recoverai-demo" },
  partial: false,
  revenue_at_risk: "1000.00",
  revenue_recovered: "250.00",
  expected_recovery: "400.00",
  recovery_rate: 0.5,
  active_cases: 3,
  pending_approvals: 1,
  failed_actions: 0,
  policy_blocks: 2,
  currency: "INR",
  labels: {},
};

describe("operator UI", () => {
  afterEach(() => {
    cleanup();
  });
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders command center real-data metrics", async () => {
    vi.mocked(fetchCommandCenter).mockResolvedValue(metrics);
    render(<CommandCenterPage />);
    await waitFor(() => {
      expect(screen.getByText("Revenue recovered")).toBeInTheDocument();
    });
    expect(screen.getByText(/250/)).toBeInTheDocument();
    expect(screen.getByText("Pending approvals")).toBeInTheDocument();
  });

  it("renders an empty cases state", async () => {
    vi.mocked(fetchCases).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 25,
      total: 0,
    });
    render(<CasesPage />);
    await waitFor(() => {
      expect(screen.getByText("No recovery cases")).toBeInTheDocument();
    });
  });

  it("renders an API error state on cases", async () => {
    vi.mocked(fetchCases).mockRejectedValue(new Error("API unavailable"));
    render(<CasesPage />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("API unavailable");
    });
  });

  it("renders case detail from API payloads", async () => {
    const detail: CaseDetail = {
      case: {
        id: "c1",
        merchant_id: "m1",
        customer: { full_name: "Ada", email: "ada@test", external_id: "x" },
        amount_at_risk: "4000.00",
        amount_recovered: "0.00",
        currency: "INR",
        case_type: "FAILED_PAYMENT",
        failure_reason: "TEMPORARY_BANK_ERROR",
        status: "AWAITING_APPROVAL",
        recovery_probability: "0.42",
        recommended_action: "RETRY_NOW",
        expected_recovery: "3200.00",
        created_at: "2026-09-04T00:00:00Z",
        opened_at: "2026-09-04T00:00:00Z",
        closed_at: null,
      },
      customer: { full_name: "Ada", email: "ada@test" },
      payment: {
        id: "p1",
        status: "FAILED",
        amount: "4000.00",
        currency: "INR",
        failure_reason: "TEMPORARY_BANK_ERROR",
        failure_code: null,
        payment_method: "card",
        provider: "simulator",
        provider_payment_id: "pay_1",
        provider_order_id: "ord_1",
        captured_at: null,
        failed_at: "2026-09-04T00:00:00Z",
      },
      verification: {
        verified_payment_id: null,
        last_mismatch_reason: null,
        amount_recovered: "0.00",
        amount_at_risk: "4000.00",
      },
      selected_action: "RETRY_NOW",
      policy_verdict: "APPROVAL_REQUIRED",
      approval: {
        id: "a1",
        case_id: "c1",
        action_id: "act1",
        status: "PENDING",
        requested_by: "demo-operator",
        decided_by: null,
        decision_reason: null,
        expires_at: "2026-09-04T01:00:00Z",
        decided_at: null,
        created_at: "2026-09-04T00:00:00Z",
      },
      approvals: [],
      actions: [],
      policy_evaluations: [],
      predictions: [],
      decision: null,
    };
    const decision: DecisionView = {
      case_id: "c1",
      source: "DETERMINISTIC_FALLBACK",
      source_label: "DETERMINISTIC FALLBACK",
      diagnosis: { root_cause: "temporary bank error", confidence: 0.7, evidence: ["code"] },
      confidence: 0.7,
      evidence: ["code"],
      candidate_actions: [],
      model_probabilities: [],
      selected_action: "RETRY_NOW",
      expected_values: {},
      policy_result: "APPROVAL_REQUIRED",
      explanation: "High value requires approval",
    };
    vi.mocked(fetchCase).mockResolvedValue(detail);
    vi.mocked(fetchCaseDecision).mockResolvedValue(decision);
    vi.mocked(fetchCaseTimeline).mockResolvedValue({
      case_id: "c1",
      cursor: null,
      items: [
        {
          id: "e1",
          timestamp: "2026-09-04T00:00:00Z",
          actor_type: "SYSTEM",
          actor_id: null,
          event_type: "RECOVERY_CASE_CREATED",
          action: null,
          previous_state: null,
          new_state: "DETECTED",
          summary: "Case created",
          correlation_id: "corr",
          idempotency_key: null,
          case_id: "c1",
        },
      ],
    });
    vi.mocked(fetchAgentRuns).mockResolvedValue({ items: [] });
    vi.mocked(fetchToolCalls).mockResolvedValue({ items: [] });

    render(<CaseDetailScreen caseId="c1" />);
    await waitFor(() => {
      expect(screen.getByText("Ada")).toBeInTheDocument();
    });
    expect(screen.getByText("DETERMINISTIC FALLBACK")).toBeInTheDocument();
    expect(screen.getByText("Approval required")).toBeInTheDocument();
  });

  it("submits an approval action through the API", async () => {
    vi.mocked(fetchApprovals).mockResolvedValue({
      items: [
        {
          id: "a1",
          case_id: "c1",
          action_id: "act1",
          status: "PENDING",
          requested_by: null,
          decided_by: null,
          decision_reason: null,
          expires_at: null,
          decided_at: null,
          created_at: null,
          proposed_action: "RETRY_NOW",
          amount: "40000.00",
          customer: { full_name: "Ada", email: "a@test" },
        },
      ],
      page: 1,
      page_size: 50,
      total: 1,
    });
    vi.mocked(decideApproval).mockResolvedValue({});
    render(<ApprovalsPage />);
    await waitFor(() => {
      expect(screen.getByText("RETRY_NOW")).toBeInTheDocument();
    });
    fireEvent.click(screen.getAllByText("Approve")[0]!);
    fireEvent.click(screen.getByText("Submit"));
    await waitFor(() => {
      expect(decideApproval).toHaveBeenCalledWith("a1", "approve");
    });
  });

  it("renders audit events", async () => {
    vi.mocked(fetchAudit).mockResolvedValue({
      items: [
        {
          id: "e1",
          timestamp: "2026-09-04T00:00:00Z",
          actor_type: "SYSTEM",
          actor_id: "worker",
          event_type: "RECOVERY_CASE_CREATED",
          action: null,
          previous_state: null,
          new_state: "DETECTED",
          summary: "Detected failed payment",
          correlation_id: "abc",
          idempotency_key: "key-1",
          case_id: "c1",
        },
      ],
      page: 1,
      page_size: 50,
      total: 1,
    });
    render(<AuditPage />);
    await waitFor(() => {
      expect(screen.getByText("RECOVERY_CASE_CREATED")).toBeInTheDocument();
    });
    expect(screen.getByText("Detected failed payment")).toBeInTheDocument();
    expect(screen.getByText("key-1")).toBeInTheDocument();
  });

  it("validates policy settings", () => {
    const base = {
      max_retry_attempts: 3,
      max_discount_percent: "10",
      max_daily_discount_budget: "5000",
      high_value_approval_threshold: "25000",
      medium_value_approval_threshold: "5000",
      max_communications_per_day: 3,
      quiet_hours_start: 21,
      quiet_hours_end: 8,
      automatic_recovery_enabled: true,
      approval_ttl_minutes: 60,
      blocked_action_types: [],
    };
    expect(validatePolicySettings(base)).toBeNull();
    expect(validatePolicySettings({ ...base, max_discount_percent: "150" })).toMatch(/discount/);
  });

  it("renders evaluation metrics with a synthetic label", async () => {
    vi.mocked(fetchEvaluation).mockResolvedValue({
      available: true,
      synthetic: true,
      label: "Held-out synthetic/simulation metrics. Not production Razorpay results.",
      model_version: "recovery-v1",
      dataset_version: "ds-1",
      algorithm: "logistic_regression",
      quality_passed: true,
      is_production: true,
      trained_at: "2026-09-04T00:00:00Z",
      roc_auc: 0.81,
      pr_auc: 0.7,
      brier: 0.12,
      ece: 0.04,
      calibration: {},
      held_out_metrics: {},
      business_sense: null,
      baseline_vs_optimizer: null,
    });
    render(<EvaluationPage />);
    await waitFor(() => {
      expect(screen.getByText("recovery-v1")).toBeInTheDocument();
    });
    expect(screen.getByText(/Not production Razorpay results/)).toBeInTheDocument();
    expect(screen.getByText("0.8100")).toBeInTheDocument();
  });
});
