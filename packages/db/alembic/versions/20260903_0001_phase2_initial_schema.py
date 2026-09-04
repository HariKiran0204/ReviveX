"""Phase 2 initial schema

Revision ID: 20260903_0001
Revises:
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE customers (
	external_id VARCHAR(255), 
	email VARCHAR(320), 
	phone VARCHAR(32), 
	full_name VARCHAR(255), 
	lifetime_value NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_customers PRIMARY KEY (id), 
	CONSTRAINT ck_customers_customers_lifetime_value_non_negative CHECK (lifetime_value >= 0)
)""")
    op.execute("""CREATE TABLE idempotency_keys (
	key VARCHAR(255) NOT NULL, 
	operation VARCHAR(128) NOT NULL, 
	request_hash VARCHAR(128) NOT NULL, 
	response_reference VARCHAR(255), 
	status VARCHAR(32) NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_idempotency_keys PRIMARY KEY (id), 
	CONSTRAINT uq_idempotency_keys_merchant_key UNIQUE (merchant_id, key)
)""")
    op.execute("""CREATE TABLE merchant_memberships (
	merchant_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_merchant_memberships PRIMARY KEY (id), 
	CONSTRAINT uq_merchant_memberships_merchant_user UNIQUE (merchant_id, user_id)
)""")
    op.execute("""CREATE TABLE merchants (
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(100) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	settings JSONB, 
	description TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_merchants PRIMARY KEY (id), 
	CONSTRAINT uq_merchants_slug UNIQUE (slug)
)""")
    op.execute("""CREATE TABLE users (
	email VARCHAR(320) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_email UNIQUE (email)
)""")
    op.execute("""CREATE TABLE webhook_events (
	provider VARCHAR(64) NOT NULL, 
	event_id VARCHAR(255) NOT NULL, 
	event_type VARCHAR(128) NOT NULL, 
	signature_valid BOOLEAN, 
	status VARCHAR(32) NOT NULL, 
	payload JSONB NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	correlation_id VARCHAR(128), 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_webhook_events PRIMARY KEY (id), 
	CONSTRAINT uq_webhook_events_provider_event_id UNIQUE (provider, event_id)
)""")
    op.execute("""CREATE TABLE carts (
	customer_id UUID NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	subtotal NUMERIC(18, 2) NOT NULL, 
	discount NUMERIC(18, 2) NOT NULL, 
	total NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	abandoned_at TIMESTAMP WITH TIME ZONE, 
	converted_at TIMESTAMP WITH TIME ZONE, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_carts PRIMARY KEY (id), 
	CONSTRAINT ck_carts_carts_subtotal_non_negative CHECK (subtotal >= 0), 
	CONSTRAINT ck_carts_carts_discount_non_negative CHECK (discount >= 0), 
	CONSTRAINT ck_carts_carts_total_non_negative CHECK (total >= 0), 
	CONSTRAINT fk_carts_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE payments (
	customer_id UUID NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	provider_payment_id VARCHAR(255), 
	provider_order_id VARCHAR(255), 
	provider_payment_link_id VARCHAR(255), 
	amount NUMERIC(18, 2) NOT NULL, 
	provider_amount_minor BIGINT, 
	currency VARCHAR(3) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	payment_method VARCHAR(64), 
	failure_reason TEXT, 
	failure_code VARCHAR(64), 
	captured_at TIMESTAMP WITH TIME ZONE, 
	failed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_payments PRIMARY KEY (id), 
	CONSTRAINT ck_payments_payments_amount_non_negative CHECK (amount >= 0), 
	CONSTRAINT uq_payments_merchant_provider_payment_id UNIQUE (merchant_id, provider, provider_payment_id), 
	CONSTRAINT fk_payments_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE subscriptions (
	customer_id UUID NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	provider_subscription_id VARCHAR(255), 
	plan_id VARCHAR(128), 
	status VARCHAR(32) NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	billing_interval VARCHAR(32), 
	current_period_start TIMESTAMP WITH TIME ZONE, 
	current_period_end TIMESTAMP WITH TIME ZONE, 
	failed_attempt_count INTEGER NOT NULL, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	metadata JSONB, 
	failure_reason TEXT, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_subscriptions PRIMARY KEY (id), 
	CONSTRAINT ck_subscriptions_subscriptions_amount_non_negative CHECK (amount >= 0), 
	CONSTRAINT fk_subscriptions_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE cart_items (
	cart_id UUID NOT NULL, 
	sku VARCHAR(128), 
	name VARCHAR(255) NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(18, 2) NOT NULL, 
	subtotal NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_cart_items PRIMARY KEY (id), 
	CONSTRAINT ck_cart_items_cart_items_quantity_positive CHECK (quantity > 0), 
	CONSTRAINT ck_cart_items_cart_items_unit_price_non_negative CHECK (unit_price >= 0), 
	CONSTRAINT ck_cart_items_cart_items_subtotal_non_negative CHECK (subtotal >= 0), 
	CONSTRAINT fk_cart_items_cart_id_carts FOREIGN KEY(cart_id) REFERENCES carts (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE payment_attempts (
	payment_id UUID NOT NULL, 
	attempt_number INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	failure_reason TEXT, 
	failure_code VARCHAR(64), 
	attempted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_payment_attempts PRIMARY KEY (id), 
	CONSTRAINT ck_payment_attempts_payment_attempts_amount_non_negative CHECK (amount >= 0), 
	CONSTRAINT uq_payment_attempts_payment_attempt UNIQUE (payment_id, attempt_number), 
	CONSTRAINT fk_payment_attempts_payment_id_payments FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE recovery_cases (
	customer_id UUID NOT NULL, 
	payment_id UUID, 
	cart_id UUID, 
	subscription_id UUID, 
	case_type VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	amount_at_risk NUMERIC(18, 2) NOT NULL, 
	amount_recovered NUMERIC(18, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	priority INTEGER NOT NULL, 
	source_event_id UUID, 
	version INTEGER NOT NULL, 
	opened_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_recovery_cases PRIMARY KEY (id), 
	CONSTRAINT ck_recovery_cases_recovery_cases_amount_at_risk_non_negative CHECK (amount_at_risk >= 0), 
	CONSTRAINT ck_recovery_cases_recovery_cases_amount_recovered_non_negative CHECK (amount_recovered >= 0), 
	CONSTRAINT ck_recovery_cases_recovery_cases_recovered_lte_at_risk CHECK (amount_recovered <= amount_at_risk), 
	CONSTRAINT ck_recovery_cases_recovery_cases_has_subject CHECK ((payment_id IS NOT NULL)::int + (cart_id IS NOT NULL)::int + (subscription_id IS NOT NULL)::int >= 1), 
	CONSTRAINT fk_recovery_cases_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_recovery_cases_payment_id_payments FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE SET NULL, 
	CONSTRAINT fk_recovery_cases_cart_id_carts FOREIGN KEY(cart_id) REFERENCES carts (id) ON DELETE SET NULL, 
	CONSTRAINT fk_recovery_cases_subscription_id_subscriptions FOREIGN KEY(subscription_id) REFERENCES subscriptions (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE agent_runs (
	recovery_case_id UUID, 
	agent_name VARCHAR(128) NOT NULL, 
	agent_version VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	input_summary JSONB, 
	output_summary JSONB, 
	decision_factors JSONB, 
	error_message TEXT, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	latency_ms INTEGER, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_agent_runs PRIMARY KEY (id), 
	CONSTRAINT fk_agent_runs_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE audit_events (
	case_id UUID, 
	actor_type VARCHAR(32) NOT NULL, 
	actor_id VARCHAR(255), 
	event_type VARCHAR(128) NOT NULL, 
	action VARCHAR(128), 
	previous_state VARCHAR(64), 
	new_state VARCHAR(64), 
	summary TEXT NOT NULL, 
	metadata JSONB, 
	correlation_id VARCHAR(128), 
	idempotency_key VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	CONSTRAINT pk_audit_events PRIMARY KEY (id), 
	CONSTRAINT fk_audit_events_case_id_recovery_cases FOREIGN KEY(case_id) REFERENCES recovery_cases (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE notifications (
	customer_id UUID NOT NULL, 
	recovery_case_id UUID, 
	channel VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	provider VARCHAR(64), 
	provider_reference VARCHAR(255), 
	subject VARCHAR(255), 
	body_preview TEXT, 
	scheduled_for TIMESTAMP WITH TIME ZONE, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_notifications PRIMARY KEY (id), 
	CONSTRAINT fk_notifications_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_notifications_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE recovery_actions (
	recovery_case_id UUID NOT NULL, 
	action_type VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	idempotency_key VARCHAR(255) NOT NULL, 
	attempt_number INTEGER NOT NULL, 
	risk_level VARCHAR(16) NOT NULL, 
	provider VARCHAR(64), 
	provider_reference VARCHAR(255), 
	amount NUMERIC(18, 2), 
	currency VARCHAR(3) NOT NULL, 
	scheduled_for TIMESTAMP WITH TIME ZONE, 
	executed_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_recovery_actions PRIMARY KEY (id), 
	CONSTRAINT uq_recovery_actions_merchant_idempotency UNIQUE (merchant_id, idempotency_key), 
	CONSTRAINT ck_recovery_actions_recovery_actions_amount_non_negative CHECK (amount IS NULL OR amount >= 0), 
	CONSTRAINT fk_recovery_actions_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE policy_evaluations (
	recovery_case_id UUID, 
	recovery_action_id UUID, 
	policy_version VARCHAR(64) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	risk_level VARCHAR(16) NOT NULL, 
	allowed BOOLEAN NOT NULL, 
	requires_approval BOOLEAN NOT NULL, 
	reason TEXT, 
	policy_ids JSONB, 
	evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metadata JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_policy_evaluations PRIMARY KEY (id), 
	CONSTRAINT fk_policy_evaluations_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE SET NULL, 
	CONSTRAINT fk_policy_evaluations_recovery_action_id_recovery_actions FOREIGN KEY(recovery_action_id) REFERENCES recovery_actions (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE recovery_decisions (
	recovery_case_id UUID NOT NULL, 
	recovery_action_id UUID, 
	model_version VARCHAR(64), 
	agent_version VARCHAR(64), 
	decision_version VARCHAR(64) NOT NULL, 
	selected_action VARCHAR(64) NOT NULL, 
	confidence NUMERIC(18, 2), 
	candidate_actions JSONB NOT NULL, 
	expected_values JSONB NOT NULL, 
	selected_expected_value NUMERIC(18, 2), 
	policy_verdict VARCHAR(64), 
	explanation TEXT, 
	decision_factors JSONB, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_recovery_decisions PRIMARY KEY (id), 
	CONSTRAINT fk_recovery_decisions_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE CASCADE, 
	CONSTRAINT fk_recovery_decisions_recovery_action_id_recovery_actions FOREIGN KEY(recovery_action_id) REFERENCES recovery_actions (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE tool_calls (
	recovery_case_id UUID, 
	agent_run_id UUID, 
	tool_name VARCHAR(128) NOT NULL, 
	tool_version VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	request_payload JSONB, 
	response_payload JSONB, 
	idempotency_key VARCHAR(255), 
	correlation_id VARCHAR(128), 
	latency_ms INTEGER, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_tool_calls PRIMARY KEY (id), 
	CONSTRAINT fk_tool_calls_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE SET NULL, 
	CONSTRAINT fk_tool_calls_agent_run_id_agent_runs FOREIGN KEY(agent_run_id) REFERENCES agent_runs (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE approvals (
	recovery_case_id UUID NOT NULL, 
	recovery_action_id UUID, 
	policy_evaluation_id UUID, 
	status VARCHAR(32) NOT NULL, 
	requested_by VARCHAR(255), 
	decided_by VARCHAR(255), 
	decision_reason TEXT, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	merchant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_approvals PRIMARY KEY (id), 
	CONSTRAINT fk_approvals_recovery_case_id_recovery_cases FOREIGN KEY(recovery_case_id) REFERENCES recovery_cases (id) ON DELETE CASCADE, 
	CONSTRAINT fk_approvals_recovery_action_id_recovery_actions FOREIGN KEY(recovery_action_id) REFERENCES recovery_actions (id) ON DELETE SET NULL, 
	CONSTRAINT fk_approvals_policy_evaluation_id_policy_evaluations FOREIGN KEY(policy_evaluation_id) REFERENCES policy_evaluations (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE INDEX ix_agent_runs_merchant_id ON agent_runs (merchant_id)""")
    op.execute("""CREATE INDEX ix_agent_runs_recovery_case_id ON agent_runs (recovery_case_id)""")
    op.execute("""CREATE INDEX ix_approvals_merchant_id ON approvals (merchant_id)""")
    op.execute("""CREATE INDEX ix_approvals_merchant_status ON approvals (merchant_id, status)""")
    op.execute("""CREATE INDEX ix_approvals_recovery_case_id ON approvals (recovery_case_id)""")
    op.execute("""CREATE INDEX ix_approvals_status ON approvals (status)""")
    op.execute("""CREATE INDEX ix_audit_events_case_id ON audit_events (case_id)""")
    op.execute("""CREATE INDEX ix_audit_events_correlation_id ON audit_events (correlation_id)""")
    op.execute("""CREATE INDEX ix_audit_events_created_at ON audit_events (created_at)""")
    op.execute("""CREATE INDEX ix_audit_events_merchant_id ON audit_events (merchant_id)""")
    op.execute("""CREATE INDEX ix_cart_items_cart_id ON cart_items (cart_id)""")
    op.execute("""CREATE INDEX ix_carts_customer_id ON carts (customer_id)""")
    op.execute("""CREATE INDEX ix_carts_merchant_id ON carts (merchant_id)""")
    op.execute("""CREATE INDEX ix_customers_email ON customers (email)""")
    op.execute("""CREATE INDEX ix_customers_merchant_id ON customers (merchant_id)""")
    op.execute("""CREATE INDEX ix_idempotency_keys_merchant_id ON idempotency_keys (merchant_id)""")
    op.execute(
        """CREATE INDEX ix_merchant_memberships_merchant_id ON merchant_memberships (merchant_id)"""
    )
    op.execute("""CREATE INDEX ix_merchant_memberships_user_id ON merchant_memberships (user_id)""")
    op.execute("""CREATE INDEX ix_notifications_customer_id ON notifications (customer_id)""")
    op.execute("""CREATE INDEX ix_notifications_merchant_id ON notifications (merchant_id)""")
    op.execute(
        """CREATE INDEX ix_notifications_recovery_case_id ON notifications (recovery_case_id)"""
    )
    op.execute("""CREATE INDEX ix_payment_attempts_payment_id ON payment_attempts (payment_id)""")
    op.execute("""CREATE INDEX ix_payments_customer_id ON payments (customer_id)""")
    op.execute("""CREATE INDEX ix_payments_merchant_id ON payments (merchant_id)""")
    op.execute("""CREATE INDEX ix_payments_status ON payments (status)""")
    op.execute(
        """CREATE INDEX ix_policy_evaluations_merchant_id ON policy_evaluations (merchant_id)"""
    )
    op.execute(
        """CREATE INDEX ix_policy_evaluations_recovery_case_id ON policy_evaluations (recovery_case_id)"""
    )
    op.execute("""CREATE INDEX ix_recovery_actions_merchant_id ON recovery_actions (merchant_id)""")
    op.execute(
        """CREATE INDEX ix_recovery_actions_recovery_case_id ON recovery_actions (recovery_case_id)"""
    )
    op.execute("""CREATE INDEX ix_recovery_cases_case_type ON recovery_cases (case_type)""")
    op.execute("""CREATE INDEX ix_recovery_cases_customer_id ON recovery_cases (customer_id)""")
    op.execute(
        """CREATE INDEX ix_recovery_cases_merchant_created_at ON recovery_cases (merchant_id, created_at)"""
    )
    op.execute("""CREATE INDEX ix_recovery_cases_merchant_id ON recovery_cases (merchant_id)""")
    op.execute(
        """CREATE INDEX ix_recovery_cases_merchant_status ON recovery_cases (merchant_id, status)"""
    )
    op.execute(
        """CREATE INDEX ix_recovery_cases_merchant_type ON recovery_cases (merchant_id, case_type)"""
    )
    op.execute("""CREATE INDEX ix_recovery_cases_status ON recovery_cases (status)""")
    op.execute(
        """CREATE INDEX ix_recovery_decisions_merchant_id ON recovery_decisions (merchant_id)"""
    )
    op.execute(
        """CREATE INDEX ix_recovery_decisions_recovery_case_id ON recovery_decisions (recovery_case_id)"""
    )
    op.execute("""CREATE INDEX ix_subscriptions_customer_id ON subscriptions (customer_id)""")
    op.execute("""CREATE INDEX ix_subscriptions_merchant_id ON subscriptions (merchant_id)""")
    op.execute("""CREATE INDEX ix_subscriptions_status ON subscriptions (status)""")
    op.execute("""CREATE INDEX ix_tool_calls_merchant_id ON tool_calls (merchant_id)""")
    op.execute("""CREATE INDEX ix_tool_calls_recovery_case_id ON tool_calls (recovery_case_id)""")
    op.execute(
        """CREATE INDEX ix_webhook_events_correlation_id ON webhook_events (correlation_id)"""
    )
    op.execute("""CREATE INDEX ix_webhook_events_merchant_id ON webhook_events (merchant_id)""")
    op.execute("""CREATE INDEX ix_webhook_events_provider ON webhook_events (provider)""")
    op.execute("""CREATE INDEX ix_webhook_events_status ON webhook_events (status)""")
    op.execute(
        """CREATE UNIQUE INDEX uq_recovery_cases_open_cart ON recovery_cases (merchant_id, cart_id) WHERE cart_id IS NOT NULL AND closed_at IS NULL"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_recovery_cases_open_payment ON recovery_cases (merchant_id, payment_id) WHERE payment_id IS NOT NULL AND closed_at IS NULL"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_recovery_cases_open_subscription ON recovery_cases (merchant_id, subscription_id) WHERE subscription_id IS NOT NULL AND closed_at IS NULL"""
    )


def downgrade() -> None:
    op.execute("""DROP INDEX uq_recovery_cases_open_subscription""")
    op.execute("""DROP INDEX uq_recovery_cases_open_payment""")
    op.execute("""DROP INDEX uq_recovery_cases_open_cart""")
    op.execute("""DROP INDEX ix_webhook_events_status""")
    op.execute("""DROP INDEX ix_webhook_events_provider""")
    op.execute("""DROP INDEX ix_webhook_events_merchant_id""")
    op.execute("""DROP INDEX ix_webhook_events_correlation_id""")
    op.execute("""DROP INDEX ix_tool_calls_recovery_case_id""")
    op.execute("""DROP INDEX ix_tool_calls_merchant_id""")
    op.execute("""DROP INDEX ix_subscriptions_status""")
    op.execute("""DROP INDEX ix_subscriptions_merchant_id""")
    op.execute("""DROP INDEX ix_subscriptions_customer_id""")
    op.execute("""DROP INDEX ix_recovery_decisions_recovery_case_id""")
    op.execute("""DROP INDEX ix_recovery_decisions_merchant_id""")
    op.execute("""DROP INDEX ix_recovery_cases_status""")
    op.execute("""DROP INDEX ix_recovery_cases_merchant_type""")
    op.execute("""DROP INDEX ix_recovery_cases_merchant_status""")
    op.execute("""DROP INDEX ix_recovery_cases_merchant_id""")
    op.execute("""DROP INDEX ix_recovery_cases_merchant_created_at""")
    op.execute("""DROP INDEX ix_recovery_cases_customer_id""")
    op.execute("""DROP INDEX ix_recovery_cases_case_type""")
    op.execute("""DROP INDEX ix_recovery_actions_recovery_case_id""")
    op.execute("""DROP INDEX ix_recovery_actions_merchant_id""")
    op.execute("""DROP INDEX ix_policy_evaluations_recovery_case_id""")
    op.execute("""DROP INDEX ix_policy_evaluations_merchant_id""")
    op.execute("""DROP INDEX ix_payments_status""")
    op.execute("""DROP INDEX ix_payments_merchant_id""")
    op.execute("""DROP INDEX ix_payments_customer_id""")
    op.execute("""DROP INDEX ix_payment_attempts_payment_id""")
    op.execute("""DROP INDEX ix_notifications_recovery_case_id""")
    op.execute("""DROP INDEX ix_notifications_merchant_id""")
    op.execute("""DROP INDEX ix_notifications_customer_id""")
    op.execute("""DROP INDEX ix_merchant_memberships_user_id""")
    op.execute("""DROP INDEX ix_merchant_memberships_merchant_id""")
    op.execute("""DROP INDEX ix_idempotency_keys_merchant_id""")
    op.execute("""DROP INDEX ix_customers_merchant_id""")
    op.execute("""DROP INDEX ix_customers_email""")
    op.execute("""DROP INDEX ix_carts_merchant_id""")
    op.execute("""DROP INDEX ix_carts_customer_id""")
    op.execute("""DROP INDEX ix_cart_items_cart_id""")
    op.execute("""DROP INDEX ix_audit_events_merchant_id""")
    op.execute("""DROP INDEX ix_audit_events_created_at""")
    op.execute("""DROP INDEX ix_audit_events_correlation_id""")
    op.execute("""DROP INDEX ix_audit_events_case_id""")
    op.execute("""DROP INDEX ix_approvals_status""")
    op.execute("""DROP INDEX ix_approvals_recovery_case_id""")
    op.execute("""DROP INDEX ix_approvals_merchant_status""")
    op.execute("""DROP INDEX ix_approvals_merchant_id""")
    op.execute("""DROP INDEX ix_agent_runs_recovery_case_id""")
    op.execute("""DROP INDEX ix_agent_runs_merchant_id""")
    op.execute("""DROP TABLE approvals""")
    op.execute("""DROP TABLE tool_calls""")
    op.execute("""DROP TABLE recovery_decisions""")
    op.execute("""DROP TABLE policy_evaluations""")
    op.execute("""DROP TABLE recovery_actions""")
    op.execute("""DROP TABLE notifications""")
    op.execute("""DROP TABLE audit_events""")
    op.execute("""DROP TABLE agent_runs""")
    op.execute("""DROP TABLE recovery_cases""")
    op.execute("""DROP TABLE payment_attempts""")
    op.execute("""DROP TABLE cart_items""")
    op.execute("""DROP TABLE subscriptions""")
    op.execute("""DROP TABLE payments""")
    op.execute("""DROP TABLE carts""")
    op.execute("""DROP TABLE webhook_events""")
    op.execute("""DROP TABLE users""")
    op.execute("""DROP TABLE merchants""")
    op.execute("""DROP TABLE merchant_memberships""")
    op.execute("""DROP TABLE idempotency_keys""")
    op.execute("""DROP TABLE customers""")
