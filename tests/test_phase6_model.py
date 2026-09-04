from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from recoverai_db.enums import RecoveryActionType, RecoveryCaseStatus, RecoveryCaseType
from recoverai_db.models import Customer, Merchant, ModelVersion, Payment, RecoveryCase
from recoverai_db.repositories import ModelPredictionRepository, ModelVersionRepository
from recoverai_eval.constants import LEAKAGE_FIELDS, MODEL_FEATURE_COLUMNS
from recoverai_eval.data.generate import expand_with_labels, generate_cases
from recoverai_eval.data.split import split_by_customer, split_ids
from recoverai_eval.errors import InferenceError
from recoverai_eval.evaluation.business_sense import directional_recovery_checks
from recoverai_eval.evaluation.metrics import calibration_curve_points, classification_metrics
from recoverai_eval.features.dataset import feature_frame, rows_to_xy
from recoverai_eval.features.engineering import derive_features
from recoverai_eval.inference.api import (
    clear_model_cache,
    predict_recovery_probability,
)
from recoverai_eval.inference.fallback import FALLBACK_VERSION
from recoverai_eval.inference.persist import persist_prediction, prediction_fingerprint
from recoverai_eval.schema import CaseContext
from recoverai_eval.train import train
from recoverai_providers.models import FailureReason


def _isolate_ml_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "ml-models"
    monkeypatch.setenv("RECOVERAI_ML_DIR", str(target))
    clear_model_cache()
    return target


def test_dataset_generation_is_deterministic() -> None:
    first = expand_with_labels(generate_cases(seed=42, n_cases=50), seed=42)
    second = expand_with_labels(generate_cases(seed=42, n_cases=50), seed=42)
    assert first == second
    other = expand_with_labels(generate_cases(seed=43, n_cases=50), seed=43)
    assert first != other
    assert len(first) >= 50 * 7


def test_split_is_reproducible_and_grouped() -> None:
    rows = expand_with_labels(generate_cases(seed=7, n_cases=80), seed=7)
    a = split_by_customer(rows, seed=99)
    b = split_by_customer(rows, seed=99)
    assert split_ids(a) == split_ids(b)
    train_customers = {str(row["customer_id"]) for row in a["train"]}
    test_customers = {str(row["customer_id"]) for row in a["test"]}
    val_customers = {str(row["customer_id"]) for row in a["validation"]}
    assert not train_customers & test_customers
    assert not train_customers & val_customers
    assert not val_customers & test_customers


def test_no_target_leakage_in_features() -> None:
    rows = expand_with_labels(generate_cases(seed=3, n_cases=5), seed=3)
    derived = derive_features(rows[0], str(rows[0]["action"]))
    assert set(derived) & LEAKAGE_FIELDS == set()
    assert "recovered" not in MODEL_FEATURE_COLUMNS
    frame = feature_frame(rows_to_xy(rows)[0])
    assert "recovered" not in frame.columns
    assert "true_probability" not in frame.columns


def test_labels_are_action_conditioned() -> None:
    rows = expand_with_labels(generate_cases(seed=11, n_cases=40), seed=11)
    by_case: dict[str, set[int]] = {}
    for row in rows:
        by_case.setdefault(str(row["case_id"]), set()).add(int(row["recovered"]))
    # At least some cases get different outcomes across actions (not a constant label).
    assert any(len(values) > 1 for values in by_case.values())


def test_directional_synthetic_rates() -> None:
    rows = expand_with_labels(generate_cases(seed=42, n_cases=800), seed=42)
    checks = directional_recovery_checks(rows)
    assert checks["temp_bank_retry_gt_expired_retry"]["ok"] is True
    assert checks["expired_link_gt_expired_retry"]["ok"] is True
    assert checks["funds_later_gt_funds_now"]["ok"] is True


def test_train_and_inference_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_ml_dir(monkeypatch, tmp_path)
    result = train(
        seed=42,
        n_cases=160,
        model_version="recovery-v-test",
        overwrite=True,
        forest_estimators=12,
        publish=False,
    )
    assert result["n_cases"] == 160
    assert result["selected"] in {"logistic_regression", "random_forest"}
    assert "roc_auc" in result["test"]
    context = CaseContext(
        amount=499.0,
        failure_reason=FailureReason.TEMPORARY_BANK_ERROR.value,
        attempt_number=1,
        historical_success_rate=0.8,
        historical_recovery_rate=0.4,
        customer_lifetime_value=12000.0,
        communication_count=1,
        previous_discount_usage=0.1,
        hour_of_day=11,
        day_of_week=2,
        case_type="FAILED_PAYMENT",
        prior_failures=0,
        prior_captures=4,
    )
    scored = predict_recovery_probability(
        context,
        RecoveryActionType.RETRY_NOW.value,
        model_version="recovery-v-test",
        allow_fallback=False,
    )
    assert 0.0 <= scored.probability <= 1.0
    assert scored.model_version == "recovery-v-test"
    retry = scored.probability
    link = predict_recovery_probability(
        context,
        RecoveryActionType.SEND_PAYMENT_LINK.value,
        model_version="recovery-v-test",
        allow_fallback=False,
    ).probability
    expired = CaseContext(
        amount=499.0,
        failure_reason=FailureReason.EXPIRED_CARD.value,
        attempt_number=1,
        historical_success_rate=0.2,
        historical_recovery_rate=0.1,
        customer_lifetime_value=400.0,
        communication_count=2,
        previous_discount_usage=0.4,
        hour_of_day=11,
        day_of_week=2,
        case_type="FAILED_PAYMENT",
        prior_failures=3,
        prior_captures=1,
    )
    expired_retry = predict_recovery_probability(
        expired,
        RecoveryActionType.RETRY_NOW.value,
        model_version="recovery-v-test",
        allow_fallback=False,
    ).probability
    assert retry != link or retry != expired_retry
    again = predict_recovery_probability(
        context,
        RecoveryActionType.RETRY_NOW.value,
        model_version="recovery-v-test",
        allow_fallback=False,
    )
    assert again.probability == scored.probability
    cal = calibration_curve_points(
        [
            int(row["recovered"])
            for row in expand_with_labels(generate_cases(seed=1, n_cases=30), seed=1)[:40]
        ],
        [0.2] * 40,
    )
    assert "ece" in cal
    metrics = classification_metrics([0, 1, 1, 0], [0.1, 0.8, 0.7, 0.2])
    assert 0.0 <= metrics["brier"] <= 1.0


def test_held_out_features_exclude_labels() -> None:
    rows = expand_with_labels(generate_cases(seed=5, n_cases=40), seed=5)
    splits = split_by_customer(rows, seed=5)
    x_rows, y_true = rows_to_xy(splits["test"])
    frame = feature_frame(x_rows)
    assert "recovered" not in frame.columns
    assert len(y_true) == len(splits["test"])
    # Inference API does not accept a recovered/label argument.
    assert "recovered" not in predict_recovery_probability.__code__.co_varnames


def test_fallback_when_model_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_ml_dir(monkeypatch, tmp_path)
    context = CaseContext(
        amount=100.0,
        failure_reason=FailureReason.TEMPORARY_BANK_ERROR.value,
        attempt_number=1,
    )
    scored = predict_recovery_probability(context, RecoveryActionType.RETRY_NOW.value)
    assert scored.source == "MODEL_FALLBACK"
    assert scored.model_version == FALLBACK_VERSION
    assert 0.0 <= scored.probability <= 1.0
    other = predict_recovery_probability(context, RecoveryActionType.DO_NOTHING.value)
    assert other.probability != scored.probability


def test_malformed_features_rejected() -> None:
    with pytest.raises(InferenceError) as exc:
        predict_recovery_probability(
            {"amount": -1, "failure_reason": "X", "attempt_number": 1}, "RETRY_NOW"
        )
    assert exc.value.code == "MALFORMED_FEATURES"
    with pytest.raises(InferenceError) as exc:
        predict_recovery_probability(
            {"amount": 10, "failure_reason": "UNKNOWN", "attempt_number": 1, "recovered": 1},
            "RETRY_NOW",
        )
    assert exc.value.code == "MALFORMED_FEATURES"
    with pytest.raises(InferenceError) as exc:
        predict_recovery_probability(
            {"amount": 10, "failure_reason": "UNKNOWN", "attempt_number": 1},
            "INVENT_ACTION",
        )
    assert exc.value.code == "INVALID_ACTION"


def test_corrupt_artifact_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models = _isolate_ml_dir(monkeypatch, tmp_path)
    bad = models / "recovery-v-bad"
    bad.mkdir(parents=True)
    (bad / "model.joblib").write_bytes(b"not-a-model")
    (bad / "metadata.json").write_text('{"model_version":"recovery-v-bad"}', encoding="utf-8")
    context = CaseContext(amount=10.0, failure_reason="UNKNOWN", attempt_number=1)
    scored = predict_recovery_probability(context, "RETRY_NOW", model_version="recovery-v-bad")
    assert scored.source == "MODEL_FALLBACK"
    with pytest.raises(InferenceError) as exc:
        predict_recovery_probability(
            context,
            "RETRY_NOW",
            model_version="recovery-v-bad",
            allow_fallback=False,
        )
    assert exc.value.code == "MODEL_LOAD_FAILED"


def test_model_version_and_prediction_persistence(db_session: Session) -> None:
    merchant = Merchant(id=uuid4(), name="ml", slug=f"ml-{uuid4().hex[:8]}")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(
        id=uuid4(),
        merchant_id=merchant.id,
        email="ml@example.com",
        lifetime_value=Decimal("10.00"),
    )
    db_session.add(customer)
    db_session.flush()
    payment = Payment(
        id=uuid4(),
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("50.00"),
        status="FAILED",
        failure_code="TEMPORARY_BANK_ERROR",
        provider="simulator",
        provider_payment_id=f"pay_{uuid4().hex[:10]}",
    )
    db_session.add(payment)
    db_session.flush()
    case = RecoveryCase(
        id=uuid4(),
        merchant_id=merchant.id,
        customer_id=customer.id,
        payment_id=payment.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT.value,
        status=RecoveryCaseStatus.DETECTED.value,
        amount_at_risk=Decimal("50.00"),
        amount_recovered=Decimal("0.00"),
        opened_at=datetime.now(UTC),
    )
    db_session.add(case)
    db_session.flush()
    repo = ModelVersionRepository(db_session)
    row = ModelVersion(
        version="recovery-v-persist",
        algorithm="logistic_regression",
        dataset_version="dataset-v1-seed42-n160",
        feature_version="features-v1",
        seed=42,
        trained_at=datetime.now(UTC),
        artifact_path="/tmp/recovery-v-persist",
        quality_passed=True,
        is_production=False,
        metrics={"roc_auc": 0.8},
        configuration={"seed": 42},
    )
    repo.add(row)
    db_session.flush()
    loaded = repo.get_by_version("recovery-v-persist")
    assert loaded is not None
    assert loaded.seed == 42
    fingerprint = persist_prediction(
        db_session,
        merchant_id=merchant.id,
        recovery_case_id=case.id,
        action="RETRY_NOW",
        probability=0.42,
        model_version="recovery-v-persist",
        feature_version="features-v1",
        source="ml",
        diagnostics={"note": "test"},
    )
    persist_prediction(
        db_session,
        merchant_id=merchant.id,
        recovery_case_id=case.id,
        action="RETRY_NOW",
        probability=0.44,
        model_version="recovery-v-persist",
        feature_version="features-v1",
        source="ml",
        diagnostics={"note": "updated"},
    )
    db_session.flush()
    stored = ModelPredictionRepository(db_session).get_by_fingerprint(fingerprint)
    assert stored is not None
    assert float(stored.probability) == pytest.approx(0.44)
    assert (
        prediction_fingerprint(
            merchant_id=str(merchant.id),
            recovery_case_id=str(case.id),
            action="RETRY_NOW",
            model_version="recovery-v-persist",
            feature_version="features-v1",
        )
        == fingerprint
    )
    db_session.refresh(case)
    assert case.amount_recovered == Decimal("0.00")
