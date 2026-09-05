import type { PolicySettings } from "./api/types";

export function validatePolicySettings(policy: PolicySettings): string | null {
  if (policy.max_retry_attempts < 0 || policy.max_retry_attempts > 50) {
    return "Max retries must be between 0 and 50";
  }
  const discount = Number(policy.max_discount_percent);
  if (Number.isNaN(discount) || discount < 0 || discount > 100) {
    return "Max discount must be 0–100";
  }
  if (Number(policy.medium_value_approval_threshold) > Number(policy.high_value_approval_threshold)) {
    return "Medium threshold cannot exceed high threshold";
  }
  if (policy.max_communications_per_day < 0) {
    return "Communication limit cannot be negative";
  }
  return null;
}
