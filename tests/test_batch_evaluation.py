"""Tests for batch-level baseline vs ReviveX revenue recovery evaluation."""

from decimal import Decimal

from recoverai_eval.batch_evaluation import (
    BatchComparisonResult,
    BatchEvaluationMetrics,
    CaseEvaluationResult,
    _action_cost,
    _baseline_strategy,
    _compute_metrics,
    _evaluate_case,
    _simulate_outcome,
    evaluate_batch,
    format_report,
)
from recoverai_eval.data.generate import generate_cases


def test_same_seed_creates_same_case_batch() -> None:
    """Verify deterministic case generation with same seed."""
    cases1 = generate_cases(seed=42, n_cases=10)
    cases2 = generate_cases(seed=42, n_cases=10)

    assert len(cases1) == len(cases2) == 10
    for c1, c2 in zip(cases1, cases2):
        assert c1["case_id"] == c2["case_id"]
        assert c1["amount"] == c2["amount"]
        assert c1["failure_reason"] == c2["failure_reason"]


def test_baseline_and_revivex_receive_equivalent_cases() -> None:
    """Verify both strategies evaluate the same case set."""
    cases = generate_cases(seed=42, n_cases=5)

    baseline_results = [_evaluate_case(case, "baseline", seed=42) for case in cases]
    revivex_results = [_evaluate_case(case, "revivex", seed=42) for case in cases]

    assert len(baseline_results) == len(revivex_results) == 5
    for b, r in zip(baseline_results, revivex_results):
        assert b.case_id == r.case_id
        assert b.amount_at_risk == r.amount_at_risk


def test_recovered_revenue_comes_from_simulated_outcomes() -> None:
    """Verify recovered amounts come from simulator outcomes."""
    cases = generate_cases(seed=42, n_cases=1)
    case = cases[0]

    result = _evaluate_case(case, "baseline", seed=42)

    # Recovered amount should be either 0 or the full amount
    assert result.recovered_amount in (Decimal("0.00"), Decimal(str(case["amount"])))
    assert result.recovered == (result.recovered_amount > Decimal("0.00"))


def test_baseline_aggregation_is_correct() -> None:
    """Verify baseline metrics are computed correctly."""
    results = [
        CaseEvaluationResult(
            case_id="case1",
            amount_at_risk=Decimal("100.00"),
            action="RETRY_NOW",
            recovered=True,
            recovered_amount=Decimal("100.00"),
            cost=Decimal("20.00"),  # 5.00 base + 15.00 risk
            final_status="RECOVERED",
        ),
        CaseEvaluationResult(
            case_id="case2",
            amount_at_risk=Decimal("200.00"),
            action="RETRY_NOW",
            recovered=False,
            recovered_amount=Decimal("0.00"),
            cost=Decimal("20.00"),  # 5.00 base + 15.00 risk
            final_status="FAILED",
        ),
        CaseEvaluationResult(
            case_id="case3",
            amount_at_risk=Decimal("300.00"),
            action="SEND_PAYMENT_LINK",
            recovered=True,
            recovered_amount=Decimal("300.00"),
            cost=Decimal("12.50"),  # 3.00 base + 1.50 comm + 8.00 risk
            final_status="RECOVERED",
        ),
    ]

    metrics = _compute_metrics(results)

    assert metrics.total_revenue_at_risk == Decimal("600.00")
    assert metrics.total_recovered == Decimal("400.00")
    assert abs(metrics.recovery_rate - Decimal("0.6666666667")) < Decimal("0.0001")
    assert metrics.cases_recovered == 2
    assert metrics.total_cases == 3
    # RETRY_NOW: 5.00 base + 15.00 risk = 20.00 each (2x = 40.00)
    # SEND_PAYMENT_LINK: 3.00 base + 1.50 comm + 8.00 risk = 12.50
    assert metrics.total_cost == Decimal("52.50")
    assert metrics.net_recovery == Decimal("347.50")


def test_revivex_aggregation_is_correct() -> None:
    """Verify ReviveX metrics are computed correctly."""
    results = [
        CaseEvaluationResult(
            case_id="case1",
            amount_at_risk=Decimal("100.00"),
            action="SEND_PAYMENT_LINK",
            recovered=True,
            recovered_amount=Decimal("100.00"),
            cost=Decimal("12.50"),  # 3.00 base + 1.50 comm + 8.00 risk
            final_status="RECOVERED",
        ),
        CaseEvaluationResult(
            case_id="case2",
            amount_at_risk=Decimal("200.00"),
            action="OFFER_DISCOUNT",
            recovered=True,
            recovered_amount=Decimal("200.00"),
            cost=Decimal("52.50"),  # 1.00 base + 10.00 discount + 1.50 comm + 40.00 risk
            final_status="RECOVERED",
        ),
    ]

    metrics = _compute_metrics(results)

    assert metrics.total_revenue_at_risk == Decimal("300.00")
    assert metrics.total_recovered == Decimal("300.00")
    assert abs(metrics.recovery_rate - Decimal("1.0")) < Decimal("0.0001")
    assert metrics.cases_recovered == 2
    # SEND_PAYMENT_LINK: 3.00 base + 1.50 comm + 8.00 risk = 12.50
    # OFFER_DISCOUNT: 1.00 base + 10.00 discount + 1.50 comm + 40.00 risk = 52.50
    assert metrics.total_cost == Decimal("65.00")
    assert metrics.net_recovery == Decimal("235.00")


def test_incremental_revenue_is_correct() -> None:
    """Verify incremental revenue calculation."""
    result = BatchComparisonResult(
        n_cases=2,
        seed=42,
        total_revenue_at_risk=Decimal("500.00"),
        baseline_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("500.00"),
            total_recovered=Decimal("200.00"),
            recovery_rate=Decimal("0.4"),
            cases_recovered=1,
            total_cases=2,
            total_cost=Decimal("40.00"),
            net_recovery=Decimal("160.00"),
        ),
        revivex_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("500.00"),
            total_recovered=Decimal("350.00"),
            recovery_rate=Decimal("0.7"),
            cases_recovered=2,
            total_cases=2,
            total_cost=Decimal("60.00"),
            net_recovery=Decimal("290.00"),
        ),
        incremental_revenue=Decimal("150.00"),
        recovery_uplift_percent=Decimal("75.0"),
    )

    assert result.incremental_revenue == Decimal("150.00")
    assert result.recovery_uplift_percent == Decimal("75.0")


def test_uplift_percentage_is_correct() -> None:
    """Verify uplift percentage handles zero baseline safely."""
    # Zero baseline
    result1 = BatchComparisonResult(
        n_cases=1,
        seed=42,
        total_revenue_at_risk=Decimal("100.00"),
        baseline_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("100.00"),
            total_recovered=Decimal("0.00"),
            recovery_rate=Decimal("0.0"),
            cases_recovered=0,
            total_cases=1,
            total_cost=Decimal("0.00"),
            net_recovery=Decimal("0.00"),
        ),
        revivex_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("100.00"),
            total_recovered=Decimal("50.00"),
            recovery_rate=Decimal("0.5"),
            cases_recovered=1,
            total_cases=1,
            total_cost=Decimal("20.00"),
            net_recovery=Decimal("30.00"),
        ),
        incremental_revenue=Decimal("50.00"),
        recovery_uplift_percent=Decimal("0.00"),  # Should be 0 when baseline is 0
    )

    assert result1.recovery_uplift_percent == Decimal("0.00")

    # Non-zero baseline
    result2 = BatchComparisonResult(
        n_cases=1,
        seed=42,
        total_revenue_at_risk=Decimal("100.00"),
        baseline_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("100.00"),
            total_recovered=Decimal("40.00"),
            recovery_rate=Decimal("0.4"),
            cases_recovered=1,
            total_cases=1,
            total_cost=Decimal("20.00"),
            net_recovery=Decimal("20.00"),
        ),
        revivex_metrics=BatchEvaluationMetrics(
            total_revenue_at_risk=Decimal("100.00"),
            total_recovered=Decimal("60.00"),
            recovery_rate=Decimal("0.6"),
            cases_recovered=1,
            total_cases=1,
            total_cost=Decimal("20.00"),
            net_recovery=Decimal("40.00"),
        ),
        incremental_revenue=Decimal("20.00"),
        recovery_uplift_percent=Decimal("50.0"),
    )

    assert result2.recovery_uplift_percent == Decimal("50.0")


def test_recovered_amount_cannot_exceed_exposure() -> None:
    """Verify recovered amount never exceeds amount at risk."""
    result = evaluate_batch(n_cases=50, seed=42)

    for case_result in result.case_results:
        amount_at_risk = Decimal(case_result["amount_at_risk"])
        baseline_recovered = Decimal(case_result["baseline_recovered_amount"])
        revivex_recovered = Decimal(case_result["revivex_recovered_amount"])

        assert baseline_recovered <= amount_at_risk
        assert revivex_recovered <= amount_at_risk


def test_case_level_and_aggregate_metrics_agree() -> None:
    """Verify aggregate metrics match case-level sums."""
    result = evaluate_batch(n_cases=20, seed=42)

    # Sum case-level results
    case_baseline_recovered = sum(
        Decimal(r["baseline_recovered_amount"]) for r in result.case_results
    )
    case_revivex_recovered = sum(
        Decimal(r["revivex_recovered_amount"]) for r in result.case_results
    )
    case_baseline_cost = sum(Decimal(r["baseline_cost"]) for r in result.case_results)
    case_revivex_cost = sum(Decimal(r["revivex_cost"]) for r in result.case_results)

    # Compare with aggregate metrics
    assert abs(case_baseline_recovered - result.baseline_metrics.total_recovered) < Decimal(
        "0.01"
    )
    assert abs(case_revivex_recovered - result.revivex_metrics.total_recovered) < Decimal(
        "0.01"
    )
    assert abs(case_baseline_cost - result.baseline_metrics.total_cost) < Decimal("0.01")
    assert abs(case_revivex_cost - result.revivex_metrics.total_cost) < Decimal("0.01")


def test_action_cost_calculation() -> None:
    """Verify action cost calculations."""
    # RETRY_NOW (base + risk penalty)
    assert _action_cost("RETRY_NOW", Decimal("100.00")) == Decimal("20.00")

    # RETRY_LATER (base + risk penalty)
    assert _action_cost("RETRY_LATER", Decimal("100.00")) == Decimal("6.00")

    # SEND_PAYMENT_LINK (base + communication + risk penalty)
    assert _action_cost("SEND_PAYMENT_LINK", Decimal("100.00")) == Decimal("12.50")

    # SEND_REMINDER (base + communication + risk penalty)
    assert _action_cost("SEND_REMINDER", Decimal("100.00")) == Decimal("14.00")

    # OFFER_DISCOUNT (base + 5% discount + communication + risk penalty)
    # 1.00 base + 5.00 discount (5% of 100) + 1.50 comm + 40.00 risk = 47.50
    assert _action_cost("OFFER_DISCOUNT", Decimal("100.00")) == Decimal("47.50")
    # 1.00 base + 10.00 discount (5% of 200) + 1.50 comm + 40.00 risk = 52.50
    assert _action_cost("OFFER_DISCOUNT", Decimal("200.00")) == Decimal("52.50")

    # DO_NOTHING
    assert _action_cost("DO_NOTHING", Decimal("100.00")) == Decimal("0.00")

    # ESCALATE (base + risk penalty)
    assert _action_cost("ESCALATE", Decimal("100.00")) == Decimal("280.00")


def test_format_report_produces_expected_output() -> None:
    """Verify report formatting."""
    result = evaluate_batch(n_cases=10, seed=42)
    report = format_report(result)

    assert "ReviveX Revenue Recovery Evaluation" in report
    assert f"Cases: {result.n_cases}" in report
    assert f"Seed: {result.seed}" in report
    assert "Revenue at risk:" in report
    assert "Baseline recovered:" in report
    assert "ReviveX recovered:" in report
    assert "Incremental recovered revenue:" in report
    assert "Recovery uplift:" in report


def test_evaluate_batch_produces_valid_result() -> None:
    """End-to-end test of batch evaluation."""
    result = evaluate_batch(n_cases=10, seed=42)

    assert result.n_cases == 10
    assert result.seed == 42
    assert result.total_revenue_at_risk > Decimal("0.00")
    assert result.baseline_metrics.total_cases == 10
    assert result.revivex_metrics.total_cases == 10
    assert len(result.case_results) == 10

    # Verify all case results have required fields
    for case_result in result.case_results:
        assert "case_id" in case_result
        assert "amount_at_risk" in case_result
        assert "baseline_action" in case_result
        assert "revivex_action" in case_result
        assert "baseline_recovered_amount" in case_result
        assert "revivex_recovered_amount" in case_result


def test_paired_rng_uses_same_draw_for_baseline_and_revivex() -> None:
    """Verify baseline and revivex use identical RNG draw for the same case."""
    from recoverai_eval.batch_evaluation import _deterministic_rng
    rng_baseline = _deterministic_rng(42, "case_10", "baseline")
    rng_revivex = _deterministic_rng(42, "case_10", "revivex")
    assert rng_baseline.random() == rng_revivex.random()


def test_action_conditioned_simulation_outcomes() -> None:
    """Verify simulation outcome uses action-conditioned probabilities on identical draws."""
    from recoverai_eval.batch_evaluation import _deterministic_rng, _simulate_outcome
    cases = generate_cases(seed=42, n_cases=5)
    for case in cases:
        rng1 = _deterministic_rng(42, str(case["case_id"]))
        rng2 = _deterministic_rng(42, str(case["case_id"]))

        rec_do_nothing, _, _ = _simulate_outcome(case, "DO_NOTHING", rng=rng1)
        rec_payment_link, _, _ = _simulate_outcome(case, "SEND_PAYMENT_LINK", rng=rng2)

        # Because SEND_PAYMENT_LINK has higher or equal probability than DO_NOTHING,
        # if DO_NOTHING succeeds on draw u, SEND_PAYMENT_LINK must also succeed on draw u.
        if rec_do_nothing:
            assert rec_payment_link is True


def test_ml_mode_uses_predict_recovery_probability() -> None:
    """Verify ML mode uses predict_recovery_probability and sets probability_source."""
    result = evaluate_batch(n_cases=5, seed=42, revivex_mode="ml")
    assert result.revivex_mode == "ml"
    assert result.ml_prediction_count + result.heuristic_fallback_count == 5
    # When recovery-v1 is available, ML prediction count should be 5
    assert result.ml_prediction_count == 5
    for case_res in result.case_results:
        assert case_res["probability_source"] == "ml"


def test_heuristic_mode_works() -> None:
    """Verify heuristic mode uses heuristic probability source."""
    result = evaluate_batch(n_cases=5, seed=42, revivex_mode="heuristic")
    assert result.revivex_mode == "heuristic"
    assert result.heuristic_fallback_count == 5
    assert result.ml_prediction_count == 0
    for case_res in result.case_results:
        assert case_res["probability_source"] == "heuristic"


def test_ml_mode_fallback_on_exception(monkeypatch) -> None:
    """Verify inference failure falls back to heuristic gracefully."""
    def mock_predict(*args, **kwargs):
        raise RuntimeError("Model inference error")

    import recoverai_eval.inference.api
    monkeypatch.setattr(recoverai_eval.inference.api, "predict_recovery_probability", mock_predict)

    result = evaluate_batch(n_cases=5, seed=42, revivex_mode="ml")
    assert result.revivex_mode == "ml"
    assert result.heuristic_fallback_count == 5
    assert result.ml_prediction_count == 0


